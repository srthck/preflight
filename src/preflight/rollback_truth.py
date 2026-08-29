"""Deterministic rollback compatibility analysis.

The engine compares the previous application snapshot with the post-deployment
schema and API snapshots. It consumes existing graph, schema, and API models;
it does not perform Git operations or duplicate their parsers.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from preflight.api_contract import APIEndpoint, OpenAPIContract
from preflight.graph.builder import PreFlightGraph
from preflight.graph.traversal import find_downstream_paths
from preflight.schema import DeploymentFinding, SchemaModel


class RollbackStatus(str, Enum):
    SAFE = "SAFE"
    CAUTION = "CAUTION"
    UNSAFE = "UNSAFE"
    UNKNOWN = "UNKNOWN"


class SnapshotVersion(str, Enum):
    OLD = "OLD"
    NEW = "NEW"


class ApplicationSnapshot(BaseModel):
    """Structured application evidence, suitable for a future Git adapter."""

    model_config = {"frozen": True}

    version: str = Field(..., min_length=1)
    commit: str | None = None
    schema_dependencies: tuple[str, ...] = Field(default_factory=tuple)
    api_dependencies: tuple[str, ...] = Field(default_factory=tuple)
    provenance: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    dynamic_dependencies: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _normalize(self) -> ApplicationSnapshot:
        object.__setattr__(
            self, "schema_dependencies", tuple(sorted(set(self.schema_dependencies)))
        )
        object.__setattr__(self, "api_dependencies", tuple(sorted(set(self.api_dependencies))))
        object.__setattr__(
            self, "dynamic_dependencies", tuple(sorted(set(self.dynamic_dependencies)))
        )
        object.__setattr__(self, "provenance", tuple(_canonical_provenance(self.provenance)))
        return self


class RollbackWindow(BaseModel):
    model_config = {"frozen": True}

    enabled: bool | None = None
    rollback_versions: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _normalize(self) -> RollbackWindow:
        object.__setattr__(self, "rollback_versions", tuple(sorted(set(self.rollback_versions))))
        return self


class RollbackRequest(BaseModel):
    """All evidence required by rollback truth analysis."""

    model_config = {"frozen": True, "arbitrary_types_allowed": True}

    old_application: ApplicationSnapshot | None = None
    new_application: ApplicationSnapshot | None = None
    old_schema: SchemaModel | None = None
    new_schema: SchemaModel | None = None
    old_api: OpenAPIContract | None = None
    new_api: OpenAPIContract | None = None
    migration_findings: tuple[DeploymentFinding, ...] = Field(default_factory=tuple)
    graph: PreFlightGraph | None = None
    deployment_context: RollbackWindow | None = None


class RollbackFinding(BaseModel):
    model_config = {"frozen": True}

    rule_id: str = Field(..., min_length=1)
    severity: str = Field(..., min_length=1)
    status: RollbackStatus
    category: str = Field(..., min_length=1)
    entity: str = Field(..., min_length=1)
    old_state: str = Field(..., min_length=1)
    new_state: str = Field(..., min_length=1)
    evidence: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    reason: str = Field(..., min_length=1)
    provenance: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    missing_evidence: tuple[str, ...] = Field(default_factory=tuple)
    recommended_next_observation: str | None = None
    direction: str = "ROLLBACK"
    application_version: SnapshotVersion = SnapshotVersion.OLD
    database_state: SnapshotVersion = SnapshotVersion.NEW
    api_state: SnapshotVersion = SnapshotVersion.NEW
    direct: bool = True


class RollbackReport(BaseModel):
    model_config = {"frozen": True}

    schema_version: str = "1.0"
    status: RollbackStatus
    findings: tuple[RollbackFinding, ...] = Field(default_factory=tuple)
    unsafe_dependencies: tuple[str, ...] = Field(default_factory=tuple)
    compatible_changes: tuple[str, ...] = Field(default_factory=tuple)
    unknown_changes: tuple[str, ...] = Field(default_factory=tuple)
    evidence: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    affected_entities: tuple[str, ...] = Field(default_factory=tuple)
    forward_compatibility: RollbackStatus = RollbackStatus.UNKNOWN
    rollback_compatibility: RollbackStatus = RollbackStatus.UNKNOWN
    deterministic_hash: str = ""

    def with_hash(self) -> RollbackReport:
        payload = self.model_dump(mode="json", exclude={"deterministic_hash"})
        digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        return self.model_copy(update={"deterministic_hash": digest})


def analyze_rollback(request: RollbackRequest) -> RollbackReport:
    """Analyze OLD APP against NEW DB/API, with a separate forward verdict."""

    findings: list[RollbackFinding] = []
    if request.old_application is None:
        findings.append(
            _unknown(
                "RB-MISSING-OLD-APPLICATION",
                "The old application snapshot is unavailable.",
                "old_application",
            )
        )
    if request.deployment_context is None:
        findings.append(
            _unknown(
                "RB-ROLLBACK-WINDOW-UNKNOWN",
                "Deployment rollback expectations were not provided.",
                "deployment_context",
            )
        )
    if request.old_schema is None or request.new_schema is None:
        findings.append(
            _unknown(
                "RB-MISSING-SCHEMA-SNAPSHOT",
                "Both old and new schema snapshots are required.",
                "old_schema/new_schema",
            )
        )
    if request.old_api is None or request.new_api is None:
        findings.append(
            _unknown(
                "RB-MISSING-API-SNAPSHOT",
                "Both old and new API snapshots are required.",
                "old_api/new_api",
            )
        )

    if request.old_application and request.old_schema and request.new_schema:
        findings.extend(
            _compare_schema_dependencies(
                request.old_application, request.old_schema, request.new_schema, request.graph
            )
        )
    if request.old_application and request.old_api and request.new_api:
        findings.extend(
            _compare_api_dependencies(request.old_application, request.old_api, request.new_api)
        )
    if request.old_application and request.new_schema and request.new_application:
        findings.extend(_compare_forward_schema(request.new_application, request.new_schema))
    if (
        request.old_application
        and request.new_application
        and request.old_schema
        and request.new_schema
    ):
        findings.extend(_expand_contract_findings(request))
    if request.old_application and request.old_application.dynamic_dependencies:
        findings.append(
            _unknown(
                "RB-DYNAMIC-DEPENDENCY",
                "Dynamic or reflective dependency evidence cannot be resolved statically.",
                "old_application.dynamic_dependencies",
            )
        )

    findings = sorted(findings, key=_finding_key)
    rollback_status = _status_for(findings)
    forward_status = _forward_status(request)
    affected_set = {entity for finding in findings for entity in _finding_entities(finding)}
    for finding in findings:
        affected_set.update(_graph_context(request.graph, finding.entity))
    affected = sorted(affected_set)
    report = RollbackReport(
        status=rollback_status,
        findings=tuple(findings),
        unsafe_dependencies=tuple(
            sorted(f.entity for f in findings if f.status == RollbackStatus.UNSAFE)
        ),
        compatible_changes=tuple(
            sorted(f.entity for f in findings if f.status == RollbackStatus.SAFE)
        ),
        unknown_changes=tuple(
            sorted(f.entity for f in findings if f.status == RollbackStatus.UNKNOWN)
        ),
        evidence=tuple(item for finding in findings for item in finding.evidence),
        affected_entities=tuple(affected),
        forward_compatibility=forward_status,
        rollback_compatibility=rollback_status,
    )
    return report.with_hash()


def _compare_schema_dependencies(
    application: ApplicationSnapshot,
    old_schema: SchemaModel,
    new_schema: SchemaModel,
    graph: PreFlightGraph | None,
) -> list[RollbackFinding]:
    findings: list[RollbackFinding] = []
    for dependency in application.schema_dependencies:
        table, _, column = dependency.partition(".")
        old_exists = (
            old_schema.find_column(table, column) is not None
            if column
            else old_schema.find_table(table) is not None
        )
        new_exists = (
            new_schema.find_column(table, column) is not None
            if column
            else new_schema.find_table(table) is not None
        )
        provenance = _dependency_provenance(application, dependency)
        evidence = [
            {
                "source": "old_application",
                "entity": dependency,
                "version": application.version,
                "operation": "SCHEMA_DEPENDENCY",
            },
            {
                "source": "new_schema",
                "entity": dependency,
                "operation": "PRESENT" if new_exists else "REMOVED",
            },
        ]
        if old_exists and not new_exists:
            findings.append(
                _finding(
                    "RB-SCHEMA-REMOVED-OLD-DEPENDENCY",
                    "CRITICAL",
                    RollbackStatus.UNSAFE,
                    "SCHEMA",
                    dependency,
                    "PRESENT",
                    "REMOVED",
                    evidence,
                    "The old application depends on a schema object removed by the "
                    "new database state.",
                    provenance,
                    graph,
                    True,
                )
            )
        elif old_exists and new_exists:
            old_column = old_schema.find_column(table, column) if column else None
            new_column = new_schema.find_column(table, column) if column else None
            if old_column and new_column and old_column.data_type != new_column.data_type:
                findings.append(
                    _finding(
                        "RB-SCHEMA-TYPE-CHANGED",
                        "MEDIUM",
                        RollbackStatus.CAUTION,
                        "SCHEMA",
                        dependency,
                        old_column.data_type,
                        new_column.data_type,
                        evidence,
                        "The old application dependency remains present but its database "
                        "type changed; static evidence cannot prove runtime failure.",
                        provenance,
                        graph,
                        True,
                    )
                )
            elif old_column and new_column and old_column.nullable and not new_column.nullable:
                findings.append(
                    _finding(
                        "RB-SCHEMA-NOT-NULL-OLD-DEPENDENCY",
                        "MEDIUM",
                        RollbackStatus.CAUTION,
                        "SCHEMA",
                        dependency,
                        "NULLABLE",
                        "NOT_NULL",
                        evidence,
                        "The old dependency remains present but the new constraint may "
                        "affect writes; this is not proof of rollback failure.",
                        provenance,
                        graph,
                        True,
                    )
                )
    return findings


def _compare_api_dependencies(
    application: ApplicationSnapshot, old_api: OpenAPIContract, new_api: OpenAPIContract
) -> list[RollbackFinding]:
    old_endpoints = {(endpoint.path, endpoint.method): endpoint for endpoint in old_api.paths}
    new_endpoints = {(endpoint.path, endpoint.method): endpoint for endpoint in new_api.paths}
    findings: list[RollbackFinding] = []
    for dependency in application.api_dependencies:
        path, method, _, field = _parse_api_dependency(dependency)
        old_endpoint = old_endpoints.get((path, method))
        new_endpoint = new_endpoints.get((path, method))
        if old_endpoint is None:
            continue
        evidence = [
            {
                "source": "old_application",
                "entity": dependency,
                "version": application.version,
                "operation": "API_DEPENDENCY",
            },
            {
                "source": "new_api",
                "entity": f"{method} {path}",
                "operation": "PRESENT" if new_endpoint else "REMOVED",
            },
        ]
        if new_endpoint is None:
            findings.append(
                _finding(
                    "RB-API-ENDPOINT-REMOVED",
                    "CRITICAL",
                    RollbackStatus.UNSAFE,
                    "API",
                    dependency,
                    "PRESENT",
                    "REMOVED",
                    evidence,
                    "The old application expects an endpoint removed from the new API state.",
                    _dependency_provenance(application, dependency),
                    None,
                    True,
                )
            )
        elif field and not _endpoint_has_field(new_endpoint, field):
            findings.append(
                _finding(
                    "RB-API-FIELD-REMOVED",
                    "HIGH",
                    RollbackStatus.UNSAFE,
                    "API",
                    dependency,
                    "PRESENT",
                    "REMOVED",
                    evidence,
                    "The old application expects an API field no longer present in "
                    "the new response or request schema.",
                    _dependency_provenance(application, dependency),
                    None,
                    True,
                )
            )
    return findings


def _compare_forward_schema(
    application: ApplicationSnapshot, schema: SchemaModel
) -> list[RollbackFinding]:
    findings: list[RollbackFinding] = []
    for dependency in application.schema_dependencies:
        table, _, column = dependency.partition(".")
        exists = (
            schema.find_column(table, column) is not None
            if column
            else schema.find_table(table) is not None
        )
        if not exists:
            findings.append(
                _finding(
                    "RB-FORWARD-MISSING-DEPENDENCY",
                    "CRITICAL",
                    RollbackStatus.UNSAFE,
                    "FORWARD_SCHEMA",
                    dependency,
                    "EXPECTED",
                    "MISSING",
                    [
                        {
                            "source": "new_application",
                            "entity": dependency,
                            "operation": "SCHEMA_DEPENDENCY",
                        }
                    ],
                    "The new application depends on a schema object absent from the "
                    "new database state.",
                    (),
                    None,
                    True,
                    direction="FORWARD",
                    application_version=SnapshotVersion.NEW,
                    database_state=SnapshotVersion.NEW,
                )
            )
    return findings


def _expand_contract_findings(request: RollbackRequest) -> list[RollbackFinding]:
    if not request.migration_findings or request.old_application is None:
        return []
    findings: list[RollbackFinding] = []
    old_dependencies = set(request.old_application.schema_dependencies)
    for migration in request.migration_findings:
        if (
            migration.change in {"DROP_COLUMN", "DROP_TABLE"}
            and migration.schema_object in old_dependencies
        ):
            findings.append(
                _finding(
                    "EXPAND_CONTRACT_VIOLATION",
                    "HIGH",
                    RollbackStatus.UNSAFE,
                    "MIGRATION_SEQUENCE",
                    migration.schema_object or "UNKNOWN",
                    "OLD_STRUCTURE_PRESENT",
                    "DROPPED_IN_CONTRACT",
                    [
                        {
                            "source": "old_application",
                            "entity": migration.schema_object,
                            "operation": "DEPENDENCY",
                        },
                        {
                            "source": "migration",
                            "entity": migration.schema_object,
                            "operation": migration.change,
                        },
                    ],
                    "A contract-phase removal occurs while the previous application "
                    "still depends on the old structure.",
                    (),
                    None,
                    True,
                )
            )
    return findings


def _forward_status(request: RollbackRequest) -> RollbackStatus:
    if (
        request.new_application is not None
        and request.new_schema is not None
        and not request.new_application.schema_dependencies
    ):
        return RollbackStatus.SAFE
    findings = [
        finding for finding in analyze_forward_only(request) if finding.direction == "FORWARD"
    ]
    return _status_for(findings) if findings else RollbackStatus.UNKNOWN


def analyze_forward_only(request: RollbackRequest) -> tuple[RollbackFinding, ...]:
    if request.new_application is None or request.new_schema is None:
        return (
            _unknown(
                "RB-FORWARD-EVIDENCE-MISSING",
                "Forward compatibility requires new application and schema snapshots.",
                "new_application/new_schema",
                direction="FORWARD",
                application_version=SnapshotVersion.NEW,
                database_state=SnapshotVersion.NEW,
            ),
        )
    return tuple(_compare_forward_schema(request.new_application, request.new_schema))


def _finding(
    rule_id: str,
    severity: str,
    status: RollbackStatus,
    category: str,
    entity: str,
    old_state: str,
    new_state: str,
    evidence: list[dict[str, Any]],
    reason: str,
    provenance: Iterable[dict[str, Any]],
    graph: PreFlightGraph | None,
    direct: bool,
    *,
    direction: str = "ROLLBACK",
    application_version: SnapshotVersion = SnapshotVersion.OLD,
    database_state: SnapshotVersion = SnapshotVersion.NEW,
) -> RollbackFinding:
    affected = _graph_context(graph, entity)
    if affected and not direct:
        entity = affected[0]
    return RollbackFinding(
        rule_id=rule_id,
        severity=severity,
        status=status,
        category=category,
        entity=entity,
        old_state=old_state,
        new_state=new_state,
        evidence=tuple(_redact(evidence)),
        reason=reason,
        provenance=tuple(_canonical_provenance(provenance)),
        direct=direct,
        direction=direction,
        application_version=application_version,
        database_state=database_state,
    )


def _unknown(
    rule_id: str,
    reason: str,
    missing: str,
    *,
    direction: str = "ROLLBACK",
    application_version: SnapshotVersion = SnapshotVersion.OLD,
    database_state: SnapshotVersion = SnapshotVersion.NEW,
) -> RollbackFinding:
    return RollbackFinding(
        rule_id=rule_id,
        severity="MEDIUM",
        status=RollbackStatus.UNKNOWN,
        category="MISSING_EVIDENCE",
        entity=missing,
        old_state="UNKNOWN",
        new_state="UNKNOWN",
        reason=reason,
        evidence=(),
        provenance=(),
        missing_evidence=(missing,),
        recommended_next_observation=f"Provide structured evidence for {missing}.",
        direction=direction,
        application_version=application_version,
        database_state=database_state,
    )


def _status_for(findings: Iterable[RollbackFinding]) -> RollbackStatus:
    values = [finding.status for finding in findings]
    if RollbackStatus.UNSAFE in values:
        return RollbackStatus.UNSAFE
    if RollbackStatus.UNKNOWN in values:
        return RollbackStatus.UNKNOWN
    if RollbackStatus.CAUTION in values:
        return RollbackStatus.CAUTION
    return RollbackStatus.SAFE


def _finding_key(finding: RollbackFinding) -> tuple[str, str, str]:
    return finding.rule_id, finding.entity, finding.direction


def _finding_entities(finding: RollbackFinding) -> tuple[str, ...]:
    return (finding.entity,)


def _graph_context(graph: PreFlightGraph | None, entity: str) -> tuple[str, ...]:
    if graph is None or entity not in graph.entity_ids:
        return ()
    context = {entity}
    for dependency_path in find_downstream_paths(graph, entity):
        context.update(dependency_path.nodes)
    return tuple(sorted(context))


def _dependency_provenance(
    application: ApplicationSnapshot, dependency: str
) -> tuple[dict[str, Any], ...]:
    return tuple(
        item
        for item in application.provenance
        if item.get("entity") == dependency or not item.get("entity")
    )


def _canonical_provenance(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted((_redact(item) for item in items), key=lambda item: _canonical_json(item))


def _canonical_json(value: Any) -> str:  # noqa: ANN401
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _redact(value: Any) -> Any:  # noqa: ANN401
    secret = re.compile(r"(?i)(password|token|secret|api[_-]?key|authorization|database_url)")
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if secret.search(str(key)) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str) and (
        "Bearer " in value or "postgres://" in value or "mysql://" in value
    ):
        return "[REDACTED]"
    return value


def _parse_api_dependency(value: str) -> tuple[str, str, str, str | None]:
    parts = value.split("#", 1)
    endpoint = parts[0].strip().split(" ", 1)
    method, path = (
        (endpoint[0].upper(), endpoint[1]) if len(endpoint) == 2 else ("GET", endpoint[0])
    )
    return path, method, value, parts[1] if len(parts) == 2 else None


def _endpoint_has_field(endpoint: APIEndpoint, field: str) -> bool:
    schemas = [status.get("schema", {}) for status in endpoint.responses]
    if endpoint.request_body:
        schemas.append(endpoint.request_body)
    return any(_schema_has_field(schema, field) for schema in schemas)


def _schema_has_field(schema: Any, field: str) -> bool:  # noqa: ANN401
    if not isinstance(schema, dict):
        return False
    properties = schema.get("properties", {})
    if isinstance(properties, dict) and field in properties:
        return True
    return (
        any(_schema_has_field(value, field) for value in properties.values())
        if isinstance(properties, dict)
        else False
    )


def canonical_rollback_json(report: RollbackReport) -> str:
    return _canonical_json(report.model_dump(mode="json", exclude={"deterministic_hash"}))


def rollback_truth_sha256(report: RollbackReport) -> str:
    return hashlib.sha256(canonical_rollback_json(report).encode("utf-8")).hexdigest()


__all__ = [
    "ApplicationSnapshot",
    "RollbackFinding",
    "RollbackReport",
    "RollbackRequest",
    "RollbackStatus",
    "RollbackWindow",
    "analyze_forward_only",
    "analyze_rollback",
    "canonical_rollback_json",
    "rollback_truth_sha256",
]
