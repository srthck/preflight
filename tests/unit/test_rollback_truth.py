from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from time import perf_counter

from preflight.api_contract import parse_openapi_document
from preflight.domain.entities import Entity
from preflight.domain.enums import EdgeKind, EntityKind
from preflight.domain.graph_models import DependencyEdge
from preflight.graph.builder import GraphBuilder
from preflight.rollback_truth import (
    ApplicationSnapshot,
    RollbackRequest,
    RollbackStatus,
    RollbackWindow,
    analyze_forward_only,
    analyze_rollback,
    canonical_rollback_json,
    rollback_truth_sha256,
)
from preflight.schema import (
    ColumnSchema,
    DeploymentFinding,
    SchemaChangeKind,
    SchemaModel,
    TableSchema,
)


def schema(column="phone_number", data_type="TEXT", nullable=True):
    columns = (
        ()
        if column is None
        else (ColumnSchema(name=column, data_type=data_type, nullable=nullable),)
    )
    return SchemaModel(tables=(TableSchema(name="users", columns=columns),))


def api(field="phone_number", endpoint=True):
    properties = {} if field is None else {field: {"type": "string"}}
    paths = (
        {
            "/profile/{id}": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object", "properties": properties}
                                }
                            },
                        }
                    }
                }
            }
        }
        if endpoint
        else {}
    )
    return parse_openapi_document(
        {"openapi": "3.0.0", "info": {"title": "demo", "version": "1"}, "paths": paths}
    )


def request(
    old_app=None,
    new_app=None,
    old_schema=None,
    new_schema=None,
    old_api=None,
    new_api=None,
    **kwargs,
):
    return RollbackRequest(
        old_application=old_app
        or ApplicationSnapshot(version="v1", schema_dependencies=("users.phone_number",)),
        new_application=new_app or ApplicationSnapshot(version="v2"),
        old_schema=old_schema or schema(),
        new_schema=new_schema or schema(None),
        old_api=old_api or api(),
        new_api=new_api or api(),
        deployment_context=kwargs.pop(
            "deployment_context", RollbackWindow(enabled=True, rollback_versions=("v1",))
        ),
        **kwargs,
    )


def test_killer_new_app_safe_but_rollback_unsafe():
    report = analyze_rollback(request())
    assert report.forward_compatibility == RollbackStatus.SAFE
    assert report.rollback_compatibility == RollbackStatus.UNSAFE
    assert report.status == RollbackStatus.UNSAFE
    assert any(f.rule_id == "RB-SCHEMA-REMOVED-OLD-DEPENDENCY" for f in report.findings)


def test_removed_schema_rule_is_generic_not_phone_specific():
    app = ApplicationSnapshot(version="v1", schema_dependencies=("users.email",))
    report = analyze_rollback(
        request(old_app=app, old_schema=schema("email"), new_schema=schema(None))
    )
    assert report.findings[0].entity == "users.email"


def test_additive_schema_is_safe():
    report = analyze_rollback(request(old_schema=schema(None), new_schema=schema()))
    assert report.rollback_compatibility == RollbackStatus.SAFE


def test_type_change_is_caution_not_proven_failure():
    report = analyze_rollback(request(new_schema=schema(data_type="VARCHAR(50)")))
    assert report.status == RollbackStatus.CAUTION
    assert report.findings[0].rule_id == "RB-SCHEMA-TYPE-CHANGED"


def test_not_null_change_is_caution():
    report = analyze_rollback(request(new_schema=schema(nullable=False)))
    assert report.status == RollbackStatus.CAUTION
    assert report.findings[0].rule_id == "RB-SCHEMA-NOT-NULL-OLD-DEPENDENCY"


def test_missing_old_application_is_unknown():
    report = analyze_rollback(RollbackRequest(deployment_context=RollbackWindow(enabled=True)))
    assert report.status == RollbackStatus.UNKNOWN
    assert any("old_application" in finding.missing_evidence for finding in report.findings)


def test_missing_rollback_window_is_unknown_finding():
    report = analyze_rollback(request(deployment_context=None))
    assert any(f.rule_id == "RB-ROLLBACK-WINDOW-UNKNOWN" for f in report.findings)


def test_dynamic_dependency_is_unknown():
    app = ApplicationSnapshot(version="v1", dynamic_dependencies=("reflection",))
    report = analyze_rollback(request(old_app=app))
    assert any(f.rule_id == "RB-DYNAMIC-DEPENDENCY" for f in report.findings)


def test_old_api_endpoint_removed_is_unsafe():
    app = ApplicationSnapshot(version="v1", api_dependencies=("GET /profile/{id}",))
    report = analyze_rollback(request(old_app=app, new_api=api(endpoint=False)))
    assert any(f.rule_id == "RB-API-ENDPOINT-REMOVED" for f in report.findings)


def test_old_api_response_field_removed_is_unsafe():
    app = ApplicationSnapshot(version="v1", api_dependencies=("GET /profile/{id}#phone_number",))
    report = analyze_rollback(request(old_app=app, new_api=api(field="name")))
    assert any(f.rule_id == "RB-API-FIELD-REMOVED" for f in report.findings)


def test_api_field_retained_is_safe():
    app = ApplicationSnapshot(version="v1", api_dependencies=("GET /profile/{id}#phone_number",))
    report = analyze_rollback(request(old_app=app))
    assert not any(f.rule_id == "RB-API-FIELD-REMOVED" for f in report.findings)


def test_forward_direction_is_explicit():
    report = analyze_rollback(request())
    forward = analyze_forward_only(request())
    assert report.forward_compatibility == RollbackStatus.SAFE
    assert all(f.direction == "FORWARD" for f in forward)
    assert all(
        f.application_version.value == "OLD" for f in report.findings if f.category == "SCHEMA"
    )


def test_directionality_cannot_use_new_app_for_rollback():
    old_app = ApplicationSnapshot(version="v1", schema_dependencies=("users.phone_number",))
    new_app = ApplicationSnapshot(version="v2", schema_dependencies=())
    report = analyze_rollback(request(old_app=old_app, new_app=new_app))
    assert report.rollback_compatibility == RollbackStatus.UNSAFE


def test_expand_contract_violation():
    migration = DeploymentFinding(
        finding_id="x",
        category="DESTRUCTIVE",
        severity="HIGH",
        schema_object="users.phone_number",
        change=SchemaChangeKind.DROP_COLUMN.value,
    )
    report = analyze_rollback(request(migration_findings=(migration,)))
    assert any(f.rule_id == "EXPAND_CONTRACT_VIOLATION" for f in report.findings)


def test_graph_context_marks_downstream_entities():
    builder = GraphBuilder()
    builder.add_entity(
        Entity(
            entity_id="users.phone_number",
            name="phone_number",
            kind=EntityKind.DATABASE,
            service="db",
        )
    )
    builder.add_entity(
        Entity(entity_id="svc.Service", name="Service", kind=EntityKind.SERVICE, service="svc")
    )
    builder.add_dependency(
        DependencyEdge(source="users.phone_number", target="svc.Service", kind=EdgeKind.DB_READ)
    )
    report = analyze_rollback(request(graph=builder.build()))
    assert "svc.Service" in report.affected_entities


def test_provenance_is_preserved():
    app = ApplicationSnapshot(
        version="v1",
        schema_dependencies=("users.phone_number",),
        provenance=(
            {
                "source_file": "user_service.py",
                "line": 48,
                "entity": "users.phone_number",
                "operation": "DB_READ",
                "version": "v1",
                "resolution_rule": "static",
            },
        ),
    )
    report = analyze_rollback(request(old_app=app))
    assert report.findings[0].provenance[0]["source_file"] == "user_service.py"


def test_redaction_removes_secret_values():
    app = ApplicationSnapshot(
        version="v1",
        schema_dependencies=("users.phone_number",),
        provenance=({"source_file": "x.py", "token": "super-secret", "operation": "DB_READ"},),
    )
    report = analyze_rollback(request(old_app=app))
    assert "super-secret" not in json.dumps(report.model_dump(mode="json"))


def test_canonical_json_is_valid_and_stable():
    report = analyze_rollback(request())
    payload = canonical_rollback_json(report)
    assert json.loads(payload) == json.loads(payload)
    assert payload == canonical_rollback_json(report)


def test_hash_excludes_existing_hash_field():
    report = analyze_rollback(request())
    assert rollback_truth_sha256(report) == report.deterministic_hash


def test_reordered_dependencies_have_same_hash():
    first = analyze_rollback(
        request(
            old_app=ApplicationSnapshot(
                version="v1", schema_dependencies=("users.phone_number", "users.email")
            ),
            old_schema=SchemaModel(
                tables=(
                    TableSchema(
                        name="users",
                        columns=(ColumnSchema(name="phone_number"), ColumnSchema(name="email")),
                    ),
                )
            ),
            new_schema=SchemaModel(tables=(TableSchema(name="users"),)),
        )
    )
    second = analyze_rollback(
        request(
            old_app=ApplicationSnapshot(
                version="v1", schema_dependencies=("users.email", "users.phone_number")
            ),
            old_schema=SchemaModel(
                tables=(
                    TableSchema(
                        name="users",
                        columns=(ColumnSchema(name="email"), ColumnSchema(name="phone_number")),
                    ),
                )
            ),
            new_schema=SchemaModel(tables=(TableSchema(name="users"),)),
        )
    )
    assert rollback_truth_sha256(first) == rollback_truth_sha256(second)


def test_safe_report_has_no_false_unsafe_dependency():
    report = analyze_rollback(
        request(
            old_app=ApplicationSnapshot(version="v1", schema_dependencies=()),
            old_schema=schema(None),
            new_schema=schema(None),
        )
    )
    assert report.rollback_compatibility == RollbackStatus.SAFE
    assert report.unsafe_dependencies == ()


def test_malformed_partial_request_never_defaults_to_safe():
    report = analyze_rollback(RollbackRequest(deployment_context=RollbackWindow(enabled=True)))
    assert report.status in {RollbackStatus.UNKNOWN, RollbackStatus.CAUTION}


def test_cli_emits_valid_json(tmp_path: Path):
    old_app = tmp_path / "old_app.json"
    new_app = tmp_path / "new_app.json"
    old_schema = tmp_path / "old_schema.json"
    new_schema = tmp_path / "new_schema.json"
    old_app.write_text(json.dumps({"version": "v1", "schema_dependencies": ["users.phone_number"]}))
    new_app.write_text(json.dumps({"version": "v2", "schema_dependencies": []}))
    old_schema.write_text(json.dumps(schema().model_dump(mode="json")))
    new_schema.write_text(json.dumps(schema(None).model_dump(mode="json")))
    result = subprocess.run(
        [sys.executable, "scripts/rollback_check.py", "--old-app", str(old_app), "--new-app", str(new_app), "--old-schema", str(old_schema), "--new-schema", str(new_schema), "--json"],
        capture_output=True, text=True, check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["status"] == "UNSAFE"
    assert payload["deterministic_hash"]


def test_ten_runs_have_identical_dvh_and_measurement():
    request_value = request()
    started = perf_counter()
    hashes = [analyze_rollback(request_value).deterministic_hash for _ in range(10)]
    elapsed = perf_counter() - started
    assert len(set(hashes)) == 1
    assert elapsed >= 0
