"""End-to-end proof that /api/analyze runs the real orchestration pipeline.

These tests exist to make one claim falsifiable: "PreFlight actually
analyzes a change" rather than returning a scripted report. Every test here
either changes a real fixture input and checks the output changes with it,
or feeds the pipeline broken/missing evidence and checks it degrades to a
structured ``UNKNOWN`` instead of crashing or fabricating a verdict.
"""

from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path

import pytest

from preflight.decision import DecisionState
from preflight.orchestration.errors import FixtureUnavailableError, UnknownScenarioError
from preflight.orchestration.models import AnalysisInput, ScenarioConfig
from preflight.orchestration.pipeline import SCENARIOS, run_analysis
from preflight.rollback_truth import RollbackStatus
from preflight.semantic import SemanticAnalyzer

REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL = "demo-commerce-phone-number-removal"
SAFE_SCENARIO = "demo-commerce-phone-verified-addition"


@pytest.fixture()
def fixture_copy(tmp_path: Path) -> Path:
    """A disposable copy of fixtures/demo-commerce so tests can mutate inputs."""

    dest = tmp_path / "fixtures" / "demo-commerce"
    shutil.copytree(REPO_ROOT / "fixtures" / "demo-commerce", dest)
    return tmp_path


# ---------------------------------------------------------------------------
# Phase 12 — killer_report() is gone from the production request path
# ---------------------------------------------------------------------------


def test_killer_report_removed_from_production_api_module() -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    module = importlib.import_module("preflight_api")
    importlib.reload(module)
    assert not hasattr(module, "killer_report")
    assert not hasattr(module, "build_demo_commerce_graph")
    source = (REPO_ROOT / "scripts" / "preflight_api.py").read_text(encoding="utf-8")
    assert "killer_report" not in source
    assert "build_demo_commerce_graph" not in source
    assert "NormalizedFinding(" not in source


def test_repository_has_no_hardcoded_findings_in_production_paths() -> None:
    production_files = [
        REPO_ROOT / "scripts" / "preflight_api.py",
        REPO_ROOT / "src" / "preflight" / "orchestration" / "pipeline.py",
        REPO_ROOT / "src" / "preflight" / "orchestration" / "models.py",
    ]
    forbidden = (
        "NormalizedFinding(",
        "RB-SCHEMA-REMOVED-OLD-DEPENDENCY\"",
        "DecisionState.DO_NOT_DEPLOY",
        "killer_report",
        "build_demo_commerce_graph",
    )
    for path in production_files:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path} contains forbidden literal {token!r}"


# ---------------------------------------------------------------------------
# Phase 14 — the most important test: change input, output must change
# ---------------------------------------------------------------------------


def test_canonical_scenario_end_to_end() -> None:
    result = run_analysis(AnalysisInput(case_id="PF-1", scenario=CANONICAL))
    assert result.deployment_finding.change == "DROP_COLUMN"
    assert result.deployment_finding.schema_object == "users.phone_number"
    assert result.deployment_finding.deployment_status == "UNSAFE"
    assert result.rollback.status == RollbackStatus.UNSAFE
    assert any(f.rule_id == "RB-SCHEMA-REMOVED-OLD-DEPENDENCY" for f in result.rollback.findings)
    assert {f.affected_entity for f in result.blast_radius.findings} == {
        "user-service.UserService",
        "profile-api.ProfileAPI",
        "android-client.ProfileClient",
    }
    assert result.decision.decision == DecisionState.DO_NOT_DEPLOY
    assert result.decision.risk_score > 0


def test_removing_the_migration_changes_the_result_and_restoring_it_reverts(
    fixture_copy: Path,
) -> None:
    config = ScenarioConfig(
        name="mutable",
        fixture_root=Path("fixtures/demo-commerce"),
        migration_path=Path("fixtures/demo-commerce/database/migration.sql"),
        schema_path=Path("fixtures/demo-commerce/database/schema.sql"),
        api_contract_path=Path("fixtures/demo-commerce/profile-api/openapi.yaml"),
    )
    scenarios = {"mutable": config}
    migration_file = fixture_copy / config.migration_path
    original_sql = migration_file.read_text(encoding="utf-8")

    before = run_analysis(
        AnalysisInput(case_id="PF-1", scenario="mutable"),
        repo_root=fixture_copy,
        scenarios=scenarios,
    )
    assert before.deployment_finding.change == "DROP_COLUMN"
    assert before.decision.decision == DecisionState.DO_NOT_DEPLOY

    migration_file.write_text("-- migration removed\n")
    after = run_analysis(
        AnalysisInput(case_id="PF-1", scenario="mutable"),
        repo_root=fixture_copy,
        scenarios=scenarios,
    )
    assert after.deployment_finding.change != "DROP_COLUMN"
    assert after.decision.decision != before.decision.decision
    assert after.decision.risk_score < before.decision.risk_score
    assert after.decision.deterministic_hash != before.decision.deterministic_hash

    migration_file.write_text(original_sql, encoding="utf-8")
    restored = run_analysis(
        AnalysisInput(case_id="PF-1", scenario="mutable"),
        repo_root=fixture_copy,
        scenarios=scenarios,
    )
    assert restored.decision.deterministic_hash == before.decision.deterministic_hash
    assert restored.decision.decision == DecisionState.DO_NOT_DEPLOY


def test_removing_a_source_dependency_changes_blast_radius(fixture_copy: Path) -> None:
    """Deleting the consumer that reads phone_number must shrink blast radius."""

    config = SCENARIOS[CANONICAL]
    before = run_analysis(
        AnalysisInput(case_id="PF-1", scenario=CANONICAL), repo_root=fixture_copy
    )
    assert before.blast_radius.summary.affected_count == 3

    # Remove the API layer entirely: profile-api and android-client no longer exist.
    shutil.rmtree(fixture_copy / "fixtures/demo-commerce/profile-api")
    shutil.rmtree(fixture_copy / "fixtures/demo-commerce/android-client")

    after = run_analysis(AnalysisInput(case_id="PF-1", scenario=CANONICAL), repo_root=fixture_copy)
    assert after.blast_radius.summary.affected_count < before.blast_radius.summary.affected_count
    assert "android-client.ProfileClient" not in {
        f.affected_entity for f in after.blast_radius.findings
    }
    _ = config


# ---------------------------------------------------------------------------
# Phase 15 — a second, real, safe scenario
# ---------------------------------------------------------------------------


def test_safe_additive_migration_scenario() -> None:
    result = run_analysis(AnalysisInput(case_id="PF-2", scenario=SAFE_SCENARIO))
    assert result.deployment_finding.change == "ADD_COLUMN"
    assert result.deployment_finding.deployment_status == "SAFE"
    assert not any(f.rule_id in {"DROP_COLUMN", "DROP_TABLE"} for f in result.decision.findings)
    assert not any(
        f.status == RollbackStatus.UNSAFE for f in result.rollback.findings
    )
    assert result.decision.decision == DecisionState.SAFE
    assert result.decision.risk_score < 40


# ---------------------------------------------------------------------------
# Phase 16 — failure modes degrade to structured UNKNOWN, never a crash
# ---------------------------------------------------------------------------


def test_unknown_scenario_raises_typed_error() -> None:
    with pytest.raises(UnknownScenarioError):
        run_analysis(AnalysisInput(case_id="PF-x", scenario="does-not-exist"))


def test_missing_fixture_root_raises_typed_error(tmp_path: Path) -> None:
    config = ScenarioConfig(
        name="missing",
        fixture_root=Path("fixtures/does-not-exist"),
        migration_path=Path("fixtures/does-not-exist/migration.sql"),
        schema_path=Path("fixtures/does-not-exist/schema.sql"),
        api_contract_path=Path("fixtures/does-not-exist/openapi.yaml"),
    )
    with pytest.raises(FixtureUnavailableError):
        run_analysis(
            AnalysisInput(case_id="PF-x", scenario="missing"),
            repo_root=tmp_path,
            scenarios={"missing": config},
        )


def test_missing_migration_file_yields_unknown_not_crash(fixture_copy: Path) -> None:
    (fixture_copy / "fixtures/demo-commerce/database/migration.sql").unlink()
    result = run_analysis(AnalysisInput(case_id="PF-x", scenario=CANONICAL), repo_root=fixture_copy)
    assert result.decision.decision == DecisionState.UNKNOWN
    assert result.decision.decision != DecisionState.DO_NOT_DEPLOY
    assert result.decision.decision != DecisionState.SAFE


def test_malformed_migration_sql_yields_unknown_not_crash(fixture_copy: Path) -> None:
    (fixture_copy / "fixtures/demo-commerce/database/migration.sql").write_text(
        "ALTER TABLE users DROP COLUMN;"  # missing column name -> parser error
    )
    result = run_analysis(AnalysisInput(case_id="PF-x", scenario=CANONICAL), repo_root=fixture_copy)
    assert result.decision.decision == DecisionState.UNKNOWN
    assert result.deployment_finding.change == "PARSE_ERROR"


def test_missing_source_tree_yields_unknown_not_crash(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixtures" / "demo-commerce"
    (fixture_root / "database").mkdir(parents=True)
    (fixture_root / "database" / "schema.sql").write_text(
        (REPO_ROOT / "fixtures/demo-commerce/database/schema.sql").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (fixture_root / "database" / "migration.sql").write_text(
        "ALTER TABLE users DROP COLUMN phone_number;", encoding="utf-8"
    )
    config = ScenarioConfig(
        name="no-source",
        fixture_root=Path("fixtures/demo-commerce"),
        migration_path=Path("fixtures/demo-commerce/database/migration.sql"),
        schema_path=Path("fixtures/demo-commerce/database/schema.sql"),
        api_contract_path=Path("fixtures/demo-commerce/profile-api/openapi.yaml"),
    )
    result = run_analysis(
        AnalysisInput(case_id="PF-x", scenario="no-source"),
        repo_root=tmp_path,
        scenarios={"no-source": config},
    )
    assert "semantic_analysis" in result.unavailable_components
    assert result.decision.decision == DecisionState.UNKNOWN


def test_missing_api_contract_yields_unknown_component(fixture_copy: Path) -> None:
    (fixture_copy / "fixtures/demo-commerce/profile-api/openapi.yaml").unlink()
    result = run_analysis(AnalysisInput(case_id="PF-x", scenario=CANONICAL), repo_root=fixture_copy)
    assert "api_contract" in result.unavailable_components
    assert any(f.rule_id == "ANALYZER-UNAVAILABLE" for f in result.decision.findings)
    # Other independently-proven evidence (rollback UNSAFE) still correctly blocks
    # deployment; a missing analyzer must never make the report look safer.
    assert result.decision.decision != DecisionState.SAFE


def test_missing_schema_snapshot_yields_unknown_component(fixture_copy: Path) -> None:
    (fixture_copy / "fixtures/demo-commerce/database/schema.sql").unlink()
    result = run_analysis(AnalysisInput(case_id="PF-x", scenario=CANONICAL), repo_root=fixture_copy)
    assert "schema_snapshot" in result.unavailable_components
    assert any(f.rule_id == "RB-MISSING-SCHEMA-SNAPSHOT" for f in result.rollback.findings)


def test_invalid_fixture_empty_directory_yields_unknown(tmp_path: Path) -> None:
    empty_root = tmp_path / "fixtures" / "empty"
    empty_root.mkdir(parents=True)
    config = ScenarioConfig(
        name="empty",
        fixture_root=Path("fixtures/empty"),
        migration_path=Path("fixtures/empty/migration.sql"),
        schema_path=Path("fixtures/empty/schema.sql"),
        api_contract_path=Path("fixtures/empty/openapi.yaml"),
    )
    result = run_analysis(
        AnalysisInput(case_id="PF-x", scenario="empty"),
        repo_root=tmp_path,
        scenarios={"empty": config},
    )
    assert result.decision.decision == DecisionState.UNKNOWN
    assert result.decision.decision not in {DecisionState.SAFE, DecisionState.DO_NOT_DEPLOY}


def test_ai_unavailable_never_fails_analysis() -> None:
    """No AI provider is wired in this repo: explanation must fall back, not fail analysis."""

    result = run_analysis(AnalysisInput(case_id="PF-1", scenario=CANONICAL))
    assert result.explanation.quality.value in {"DETERMINISTIC_FALLBACK", "AI_UNAVAILABLE"}
    assert result.explanation.response is not None
    assert result.decision.decision == DecisionState.DO_NOT_DEPLOY  # verdict unaffected
    payload = result.to_response_payload()
    assert payload["ai_available"] is False


# ---------------------------------------------------------------------------
# Phase 17 — determinism
# ---------------------------------------------------------------------------


def test_ten_runs_produce_identical_hash() -> None:
    hashes = {
        run_analysis(AnalysisInput(case_id="PF-1", scenario=CANONICAL)).decision.deterministic_hash
        for _ in range(10)
    }
    assert len(hashes) == 1


def test_reversed_and_shuffled_file_discovery_order_is_identical() -> None:
    root = REPO_ROOT / "fixtures" / "demo-commerce"
    files = sorted(p for p in root.rglob("*") if p.suffix.lower() in {".py", ".kt"})

    forward = SemanticAnalyzer().analyze(root, files=files)
    reversed_result = SemanticAnalyzer().analyze(root, files=list(reversed(files)))
    shuffled = [files[1], files[0]] + files[2:] if len(files) > 1 else files
    shuffled_result = SemanticAnalyzer().analyze(root, files=shuffled)

    from preflight.graph.serialization import canonical_sha256

    forward_hash = canonical_sha256(forward.graph)
    assert forward_hash == canonical_sha256(reversed_result.graph)
    assert forward_hash == canonical_sha256(shuffled_result.graph)


def test_repeated_http_style_requests_share_deterministic_hash() -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from preflight_api import analyze as http_analyze

    status_a, payload_a = http_analyze(CANONICAL)
    status_b, payload_b = http_analyze(CANONICAL)
    assert status_a == status_b == 200
    assert payload_a["decision_report"]["deterministic_hash"] == (
        payload_b["decision_report"]["deterministic_hash"]
    )


# ---------------------------------------------------------------------------
# Phase 18 — provenance: every finding traces to a real file
# ---------------------------------------------------------------------------


def test_drop_column_evidence_points_to_the_migration_file() -> None:
    result = run_analysis(AnalysisInput(case_id="PF-1", scenario=CANONICAL))
    evidence_files = {item[0] for item in result.deployment_finding.evidence}
    assert "migration.sql" in evidence_files


def test_rollback_evidence_points_to_real_application_source() -> None:
    result = run_analysis(AnalysisInput(case_id="PF-1", scenario=CANONICAL))
    schema_findings = [f for f in result.rollback.findings if f.category == "SCHEMA"]
    assert schema_findings
    provenance_files = {
        item.get("source_file") for f in schema_findings for item in f.provenance
    }
    assert any(f and "user_service.py" in f for f in provenance_files)


def test_blast_radius_evidence_points_to_real_source_files() -> None:
    result = run_analysis(AnalysisInput(case_id="PF-1", scenario=CANONICAL))
    for finding in result.blast_radius.findings:
        source_files = {item.get("source_file") for item in finding.path.evidence}
        assert source_files, f"no evidence for {finding.affected_entity}"
        for source_file in source_files:
            assert source_file is not None
            assert (REPO_ROOT / "fixtures/demo-commerce" / source_file).exists()
