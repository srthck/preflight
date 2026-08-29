from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from preflight.decision import (
    DecisionExplanationInput,
    DecisionRequest,
    DecisionState,
    FindingCategory,
    FindingSeverity,
    NormalizedFinding,
    canonical_decision_json,
    decide,
    decision_sha256,
    normalize_findings,
)


def finding(
    rule="RULE",
    category=FindingCategory.SCHEMA,
    severity=FindingSeverity.LOW,
    *,
    blocking=False,
    confidence=1.0,
    entity="users.email",
):
    return NormalizedFinding(
        finding_id=rule + entity,
        category=category,
        severity=severity,
        confidence=confidence,
        rule_id=rule,
        title=rule,
        description="structured evidence",
        affected_entities=(entity,),
        evidence=({"source_file": "fixture.sql", "line": 1},),
        source_module="test",
        blocking=blocking,
    )


def test_empty_analysis_is_unknown():
    assert decide(DecisionRequest()).decision == DecisionState.UNKNOWN


def test_explicit_clean_analysis_is_safe():
    report = decide(DecisionRequest(findings=(finding("ADDITIVE", severity=FindingSeverity.INFO),)))
    assert report.decision == DecisionState.SAFE
    assert report.risk_score == 0


def test_safe_additive_database_change():
    report = decide(
        DecisionRequest(findings=(finding("ADD_COLUMN", severity=FindingSeverity.LOW),))
    )
    assert report.decision == DecisionState.SAFE


def test_safe_additive_api_change():
    report = decide(
        DecisionRequest(
            findings=(
                finding("API-ENDPOINT-ADDED", FindingCategory.API_CONTRACT, FindingSeverity.LOW),
            )
        )
    )
    assert report.decision == DecisionState.SAFE


def test_caution_moderate_risk():
    report = decide(
        DecisionRequest(
            findings=(
                finding("BLAST", FindingCategory.BLAST_RADIUS, FindingSeverity.CRITICAL),
                finding("CONSTRAINT", severity=FindingSeverity.MEDIUM),
            )
        )
    )
    assert report.decision == DecisionState.CAUTION
    assert 40 <= report.risk_score < 70


def test_critical_drop_column_blocks():
    report = decide(
        DecisionRequest(
            findings=(finding("DROP_COLUMN", severity=FindingSeverity.CRITICAL, blocking=True),)
        )
    )
    assert report.decision == DecisionState.DO_NOT_DEPLOY
    assert "CRITICAL_BLOCKING_FINDING" in report.policy_rules_triggered


def test_rollback_unsafe_blocks_with_destructive_change():
    report = decide(
        DecisionRequest(
            findings=(
                finding(
                    "DROP_COLUMN", FindingCategory.DATABASE, FindingSeverity.CRITICAL, blocking=True
                ),
                finding(
                    "RB-SCHEMA-REMOVED-OLD-DEPENDENCY",
                    FindingCategory.ROLLBACK,
                    FindingSeverity.CRITICAL,
                    blocking=True,
                ),
            )
        )
    )
    assert report.decision == DecisionState.DO_NOT_DEPLOY
    assert report.risk_features.rollback_unsafety == 1.0


def test_compound_rollback_schema_is_visible():
    report = decide(
        DecisionRequest(
            findings=(
                finding(
                    "DROP_COLUMN", FindingCategory.DATABASE, FindingSeverity.CRITICAL, blocking=True
                ),
                finding(
                    "RB-SCHEMA-REMOVED-OLD-DEPENDENCY",
                    FindingCategory.ROLLBACK,
                    FindingSeverity.CRITICAL,
                    blocking=True,
                ),
            )
        )
    )
    assert any(compound.id == "COMPOUND-ROLLBACK-SCHEMA" for compound in report.compound_risks)
    assert report.compound_adjustment > 0


def test_compound_api_schema_is_visible():
    report = decide(
        DecisionRequest(
            findings=(
                finding(
                    "DROP_COLUMN", FindingCategory.DATABASE, FindingSeverity.HIGH, blocking=True
                ),
                finding(
                    "API-PROPERTY-REMOVED",
                    FindingCategory.API_CONTRACT,
                    FindingSeverity.HIGH,
                    blocking=True,
                ),
            )
        )
    )
    assert any(compound.id == "COMPOUND-API-SCHEMA" for compound in report.compound_risks)


def test_unknown_component_does_not_become_safe():
    report = decide(DecisionRequest(unavailable_components=("api_contract",)))
    assert report.decision == DecisionState.UNKNOWN
    assert report.risk_features.unknown_finding_count == 1


def test_unknown_finding_is_preserved():
    report = decide(
        DecisionRequest(
            findings=(finding("DYNAMIC", FindingCategory.DYNAMIC_REFERENCE, confidence=0.0),)
        )
    )
    assert report.decision == DecisionState.UNKNOWN
    assert "DYNAMIC" in report.unknowns


def test_reordering_findings_preserves_hash():
    values = (finding("A", entity="a"), finding("B", entity="b"))
    assert decision_sha256(decide(DecisionRequest(findings=values))) == decision_sha256(
        decide(DecisionRequest(findings=tuple(reversed(values))))
    )


def test_meaningful_evidence_changes_hash():
    first = decide(DecisionRequest(findings=(finding("A", entity="a"),)))
    second = decide(DecisionRequest(findings=(finding("B", entity="a"),)))
    assert decision_sha256(first) != decision_sha256(second)


def test_adding_critical_finding_cannot_reduce_risk():
    safe = decide(DecisionRequest(findings=(finding("A", severity=FindingSeverity.LOW),)))
    risky = decide(
        DecisionRequest(
            findings=(
                finding("A", severity=FindingSeverity.LOW),
                finding("DROP_COLUMN", severity=FindingSeverity.CRITICAL, blocking=True),
            )
        )
    )
    assert risky.risk_score >= safe.risk_score


def test_nonimpacting_info_does_not_increase_risk():
    base = decide(DecisionRequest(findings=(finding("A", severity=FindingSeverity.MEDIUM),)))
    extra = decide(
        DecisionRequest(
            findings=(
                finding("A", severity=FindingSeverity.MEDIUM),
                finding("NOTE", severity=FindingSeverity.INFO),
            )
        )
    )
    assert extra.risk_score == base.risk_score


def test_evidence_chain_reaches_verdict():
    report = decide(
        DecisionRequest(
            findings=(finding("DROP_COLUMN", severity=FindingSeverity.CRITICAL, blocking=True),)
        )
    )
    assert report.evidence_chain[-1].target == "verdict"
    assert report.evidence_chain[-1].value == "DO_NOT_DEPLOY"


def test_explanation_input_is_structured_only():
    report = decide(DecisionRequest(findings=(finding("A"),)))
    explanation = DecisionExplanationInput(
        decision=report.decision,
        risk_score=report.risk_score,
        risk_features=report.risk_features,
        findings=report.findings,
        evidence_chain=report.evidence_chain,
        policy_rules=report.policy_rules_triggered,
        recommendations=report.recommendations,
    )
    assert explanation.decision == report.decision


def test_normalization_preserves_source_module():
    normalized = normalize_findings(DecisionRequest(findings=(finding("A"),)))
    assert normalized[0].source_module == "test"
    assert normalized[0].evidence[0]["source_file"] == "fixture.sql"


def test_features_are_bounded():
    report = decide(DecisionRequest(findings=(finding("A", severity=FindingSeverity.CRITICAL),)))
    assert 0 <= report.risk_features.deployment_severity <= 1
    assert 0 <= report.risk_score <= 100


def test_canonical_json_is_valid_json():
    report = decide(DecisionRequest(findings=(finding("A"),)))
    assert json.loads(canonical_decision_json(report))["decision"] == "SAFE"


def test_hash_excludes_report_hash_field():
    report = decide(DecisionRequest(findings=(finding("A"),)))
    assert decision_sha256(report) == report.deterministic_hash


def test_normalization_redacts_secrets_before_risk_report():
    report = decide(
        DecisionRequest(
            findings=(
                NormalizedFinding(
                    finding_id="secret",
                    category=FindingCategory.CONFIGURATION,
                    severity=FindingSeverity.MEDIUM,
                    rule_id="CONFIG",
                    title="config",
                    description="config",
                    evidence=({"api_key": "private-value", "value": "Bearer private-value"},),
                    source_module="test",
                ),
            )
        )
    )
    assert "private-value" not in json.dumps(report.model_dump(mode="json"))


def test_ten_identical_decisions():
    hashes = [
        decide(
            DecisionRequest(findings=(finding("A", severity=FindingSeverity.HIGH),))
        ).deterministic_hash
        for _ in range(10)
    ]
    assert len(set(hashes)) == 1


def test_report_is_immutable():
    report = decide(DecisionRequest(findings=(finding("A"),)))
    try:
        report.risk_score = 10
    except Exception:
        pass
    assert report.risk_score == 0


def test_decision_cli_emits_machine_readable_json(tmp_path: Path):
    analysis = tmp_path / "analysis.json"
    analysis.write_text(
        json.dumps(
            {
                "findings": [
                    finding(
                        "DROP_COLUMN",
                        FindingCategory.DATABASE,
                        FindingSeverity.CRITICAL,
                        blocking=True,
                    ).model_dump(mode="json")
                ]
            }
        )
    )
    result = subprocess.run(
        [sys.executable, "scripts/preflight_decide.py", "--analysis", str(analysis), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["decision"] == "DO_NOT_DEPLOY"
    assert payload["deterministic_hash"]
