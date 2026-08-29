"""DAY P0.2 forensics — locks in the exact contradiction that was found and fixed.

The observed bug: an uploaded project with zero supported source and no
migration/schema/API evidence reported `capabilities.blast_radius.status
== "NOT_APPLICABLE"` (or UNAVAILABLE) *and* `blast_radius.summary.affected_count
== 0`, while the AI explanation simultaneously said "3 affected entities."

Root cause, confirmed by forensic trace: `DecisionReport.affected_entities`
(and `risk_features.affected_entity_count`, which the explanation layer
read directly) was accumulating *sentinel placeholder strings* —
`"UNKNOWN"` (DeploymentAnalyzer's PARSE_ERROR/NO_CHANGE schema_object
placeholder) and `"old_schema/new_schema"` / `"old_api/new_api"`
(rollback_truth.py's `_unknown()` helper reusing its `entity` field to
*describe what evidence is missing*) — as if they were real graph entity
IDs. Three placeholder strings, unioned, produced the "3" the explanation
then mislabeled as "blast radius."

These tests prove: (1) the sentinel strings never reach
`affected_entities` again, and (2) the explanation's blast-radius sentence
is grounded in the real, category-scoped, full-findings-list computation —
never the decision-wide cross-category aggregate — so it can no longer
contradict `capabilities.blast_radius`.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from preflight.decision import DecisionRequest, FindingCategory, decide
from preflight.ingestion import extracted_project
from preflight.orchestration import run_project_analysis
from preflight.rollback_truth import RollbackRequest, RollbackStatus, analyze_rollback

REPO_ROOT = Path(__file__).resolve().parents[2]
UPLOADS = REPO_ROOT / "fixtures" / "uploads"


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# The exact reported contradiction, reproduced with a synthetic archive
# (not the user's real file — same shape: zero supported source, zero SQL,
# zero API contract).
# ---------------------------------------------------------------------------


def test_no_evidence_project_never_shows_phantom_affected_entities() -> None:
    data = _zip_bytes(
        {
            "site/index.html": b"<html></html>",
            "site/app.js": b"console.log('hi');\n",
        }
    )
    with extracted_project(data) as root:
        result = run_project_analysis(root, case_id="c", scenario_label="no-evidence")
    payload = result.to_response_payload()

    # The core contradiction: these three must now agree.
    assert payload["blast_radius"]["summary"]["affected_count"] == 0
    assert payload["capabilities"]["blast_radius"]["status"] != "ANALYZED"
    assert payload["decision_report"]["risk_features"]["affected_entity_count"] == 0
    assert payload["decision_report"]["affected_entities"] == []

    # No sentinel/placeholder string anywhere in affected_entities.
    for forbidden in ("UNKNOWN", "old_schema/new_schema", "old_api/new_api"):
        assert forbidden not in payload["decision_report"]["affected_entities"]

    # The explanation must not contradict the deterministic report.
    summary = payload["explanation"]["response"]["blast_radius_summary"]
    assert "affected entities" not in summary or summary.startswith("0")
    assert "could not be established" in summary or summary.startswith("Blast radius was analyzed")
    assert "3 affected entities" not in summary  # the exact reported bug


def test_deployment_placeholder_schema_object_is_never_an_affected_entity() -> None:
    """Directly exercises decision.py's normalize_findings with a PARSE_ERROR
    deployment finding — proves the fix at the unit level, not just via ZIP."""
    from preflight.schema import DeploymentFinding

    placeholder = DeploymentFinding(
        finding_id="x",
        category="UNSUPPORTED",
        severity="MEDIUM",
        schema_object="UNKNOWN",
        change="PARSE_ERROR",
        explanation_key="parse_error",
        deployment_status="UNKNOWN",
    )
    report = decide(DecisionRequest(deployment_findings=(placeholder,)))
    database_findings = [f for f in report.findings if f.category == FindingCategory.DATABASE]
    assert database_findings
    assert database_findings[0].affected_entities == ()


def test_rollback_missing_evidence_entity_is_never_an_affected_entity() -> None:
    """Directly exercises analyze_rollback + decision.py normalization with
    zero schema/API evidence — proves the fix without going through ZIP/HTTP."""
    from preflight.rollback_truth import ApplicationSnapshot

    rollback_report = analyze_rollback(
        RollbackRequest(old_application=ApplicationSnapshot(version="v1"))
    )
    assert rollback_report.status == RollbackStatus.UNKNOWN
    missing = [f for f in rollback_report.findings if f.missing_evidence]
    assert missing  # sanity: the scenario actually produces missing-evidence findings

    report = decide(DecisionRequest(rollback=rollback_report))
    rollback_findings = [f for f in report.findings if f.category == FindingCategory.ROLLBACK]
    for finding in rollback_findings:
        assert finding.affected_entities == () or "/" not in "".join(finding.affected_entities)


# ---------------------------------------------------------------------------
# Frontend-visible contract: capabilities.database must be the authoritative
# status even though the raw DeploymentFinding.change is a generic
# PARSE_ERROR whether a file was malformed or simply never existed.
# ---------------------------------------------------------------------------


def test_missing_migration_file_is_unavailable_not_just_parse_error() -> None:
    data = _zip_bytes({"app/service.py": b"class Service:\n    pass\n"})
    with extracted_project(data) as root:
        result = run_project_analysis(root, case_id="c", scenario_label="no-migration")
    # The raw analyzer output is a generic PARSE_ERROR (empty-string input) —
    # but the orchestration-level capability must say UNAVAILABLE, and it is
    # this field the frontend must treat as authoritative.
    assert result.deployment_finding.change == "PARSE_ERROR"
    assert result.capabilities["database"]["status"] == "UNAVAILABLE"
    # A genuinely missing migration must never spend real weighted risk
    # (previously: DeploymentAnalyzer.analyze("") produced a MEDIUM-severity,
    # 0.5-confidence PARSE_ERROR finding for *absent* SQL — indistinguishable
    # from a real, present-but-broken migration — silently contributing
    # ~9/100 of "risk" for evidence that was never actually present).
    assert result.decision.risk_features.deployment_severity == 0.0
    assert "deployment_rehearsal" in result.unavailable_components


def test_present_but_malformed_migration_still_contributes_real_risk() -> None:
    """The fix must not also silence a genuinely present, broken migration —
    only a wholly absent one."""
    data = _zip_bytes(
        {
            "app/service.py": b"class Service:\n    pass\n",
            "db/migration.sql": b"ALTER TABLE ADD COLUMN;;;not valid sql(((",
        }
    )
    with extracted_project(data) as root:
        result = run_project_analysis(root, case_id="c", scenario_label="broken-migration")
    assert result.deployment_finding.change == "PARSE_ERROR"
    assert result.capabilities["database"]["status"] == "PARSE_ERROR"
    assert result.decision.risk_features.deployment_severity > 0.0
    assert "deployment_rehearsal" not in result.unavailable_components


# ---------------------------------------------------------------------------
# Canonical (working) scenario: the fix must not perturb real evidence.
# ---------------------------------------------------------------------------


def test_canonical_destructive_scenario_blast_radius_is_still_consistent() -> None:
    data = (UPLOADS / "destructive-release.zip").read_bytes()
    with extracted_project(data) as root:
        result = run_project_analysis(root, case_id="c", scenario_label="destructive")
    payload = result.to_response_payload()

    real_count = payload["blast_radius"]["summary"]["affected_count"]
    assert real_count == 3
    assert payload["capabilities"]["blast_radius"]["status"] == "ANALYZED"
    summary = payload["explanation"]["response"]["blast_radius_summary"]
    assert str(real_count) in summary
    # The old bug: this would previously read a decision-wide count that
    # could differ from the real blast-radius-specific number.
    assert "could not be established" not in summary
