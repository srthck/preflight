"""P0.4 §25 — adversarial mutation tests.

Each test mutates exactly one real input and asserts the analysis genuinely
follows. The purpose is to prove the evidence chain is causal rather than
coincidental: if changing a source statement did not change the graph, or
changing a migration statement did not change the ChangeSet, the pipeline
would be reporting something other than what it read.

All mutations operate on ``fixtures/fleet-ops`` — a repository unrelated to
the canonical demo, so none of these proofs depend on demo-specific shapes.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from preflight.orchestration.models import AnalysisRunResult
from preflight.orchestration.pipeline import run_snapshot_comparison

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "fixtures" / "fleet-ops"

DISPATCH_SOURCE = Path("dispatch-service/src/dispatch_service.py")
MIGRATION = Path("database/migration.sql")


def _pair(tmp_path: Path) -> tuple[Path, Path]:
    old_root, new_root = tmp_path / "old", tmp_path / "new"
    shutil.copytree(FIXTURE, old_root)
    shutil.copytree(FIXTURE, new_root)
    (old_root / MIGRATION).unlink()
    return old_root, new_root


def _analyze(old_root: Path, new_root: Path) -> AnalysisRunResult:
    return run_snapshot_comparison(old_root, new_root, case_id="mutation")


# ---------------------------------------------------------------------------
# Source mutation
# ---------------------------------------------------------------------------


def test_changing_a_selected_column_changes_the_graph_and_the_decision(
    tmp_path: Path,
) -> None:
    """Rewrite the SELECT so DispatchService reads a different column."""
    baseline_old, baseline_new = _pair(tmp_path / "baseline")
    baseline = _analyze(baseline_old, baseline_new)

    mutated_old, mutated_new = _pair(tmp_path / "mutated")
    for root in (mutated_old, mutated_new):
        source = root / DISPATCH_SOURCE
        source.write_text(
            source.read_text(encoding="utf-8").replace(
                "SELECT id, full_name, license_number FROM drivers",
                "SELECT id, full_name, depot_code FROM drivers",
            ),
            encoding="utf-8",
        )
    mutated = _analyze(mutated_old, mutated_new)

    # The DB_READ edge moved to a different column, so license_number no
    # longer has a consumer and is no longer a resolvable blast target.
    assert "drivers.license_number" in baseline.blast_radius_targets
    assert "drivers.license_number" not in mutated.blast_radius_targets
    assert baseline.decision.deterministic_hash != mutated.decision.deterministic_hash


def test_removing_a_consumer_reduces_the_blast_radius(tmp_path: Path) -> None:
    baseline_old, baseline_new = _pair(tmp_path / "baseline")
    baseline = _analyze(baseline_old, baseline_new)

    reduced_old, reduced_new = _pair(tmp_path / "reduced")
    for root in (reduced_old, reduced_new):
        shutil.rmtree(root / "audit-service")
    reduced = _analyze(reduced_old, reduced_new)

    baseline_affected = set(baseline.decision.affected_entities)
    reduced_affected = set(reduced.decision.affected_entities)
    assert reduced_affected < baseline_affected
    assert "audit-service.AuditService" in baseline_affected
    assert "audit-service.AuditService" not in reduced_affected


def test_removing_the_http_call_breaks_the_downstream_chain(tmp_path: Path) -> None:
    """Delete the HTTP_CALL and ComplianceAPI must drop out of the impact set."""
    old_root, new_root = _pair(tmp_path)
    for root in (old_root, new_root):
        for service in ("dispatch-service/src/dispatch_service.py", "audit-service/src/audit_service.py"):
            source = root / service
            text = source.read_text(encoding="utf-8")
            text = text.replace('_http_post("http://compliance-api/v1/verify-dispatch", payload)', "pass")
            text = text.replace('_http_post("http://compliance-api/v1/verify-audit", payload)', "pass")
            source.write_text(text, encoding="utf-8")

    result = _analyze(old_root, new_root)
    assert "compliance-api.ComplianceAPI" not in result.decision.affected_entities
    assert result.convergent_entities == ()


# ---------------------------------------------------------------------------
# Migration mutation
# ---------------------------------------------------------------------------


def test_destructive_to_additive_migration_removes_the_destructive_finding(
    tmp_path: Path,
) -> None:
    destructive_old, destructive_new = _pair(tmp_path / "destructive")
    destructive = _analyze(destructive_old, destructive_new)

    additive_old, additive_new = _pair(tmp_path / "additive")
    (additive_new / MIGRATION).write_text(
        "ALTER TABLE drivers ADD COLUMN telematics_id TEXT;\n", encoding="utf-8"
    )
    additive = _analyze(additive_old, additive_new)

    destructive_rules = {f.rule_id for f in destructive.decision.findings}
    additive_rules = {f.rule_id for f in additive.decision.findings}
    assert "DROP_COLUMN" in destructive_rules
    assert "DROP_COLUMN" not in additive_rules
    assert destructive.decision.risk_score > additive.decision.risk_score


def test_adding_a_statement_to_a_migration_changes_the_changeset(tmp_path: Path) -> None:
    one_old, one_new = _pair(tmp_path / "one")
    (one_new / MIGRATION).write_text(
        "ALTER TABLE drivers DROP COLUMN license_number;\n", encoding="utf-8"
    )
    one = _analyze(one_old, one_new)

    two_old, two_new = _pair(tmp_path / "two")
    two = _analyze(two_old, two_new)  # fixture migration drops both columns

    assert len(one.schema_changes) == 1
    assert len(two.schema_changes) == 2
    assert one.change_set is not None and two.change_set is not None
    assert one.change_set.change_set_hash != two.change_set.change_set_hash
    assert one.decision.deterministic_hash != two.decision.deterministic_hash


# ---------------------------------------------------------------------------
# Irrelevant mutation: must NOT change the analysis
# ---------------------------------------------------------------------------


def test_irrelevant_documentation_change_does_not_alter_the_decision(
    tmp_path: Path,
) -> None:
    """A README edit changes the repository diff but must not change the verdict."""
    baseline_old, baseline_new = _pair(tmp_path / "baseline")
    baseline = _analyze(baseline_old, baseline_new)

    noisy_old, noisy_new = _pair(tmp_path / "noisy")
    (noisy_new / "README.md").write_text("# Fleet Ops\n\nDocs only.\n", encoding="utf-8")
    noisy = _analyze(noisy_old, noisy_new)

    # The ChangeSet legitimately differs (a file really was added)...
    assert baseline.change_set is not None and noisy.change_set is not None
    assert baseline.change_set.change_set_hash != noisy.change_set.change_set_hash
    # ...but nothing about the causal analysis or the verdict may move.
    assert baseline.decision.deterministic_hash == noisy.decision.deterministic_hash
    assert baseline.convergent_entities == noisy.convergent_entities
    assert baseline.blast_radius_targets == noisy.blast_radius_targets


def test_analysis_is_independent_of_extraction_directory(tmp_path: Path) -> None:
    """Different temp roots, identical bytes -> identical decision hash."""
    a_old, a_new = _pair(tmp_path / "location-a")
    b_old, b_new = _pair(tmp_path / "deeply" / "nested" / "location-b")

    assert _analyze(a_old, a_new).decision.deterministic_hash == (
        _analyze(b_old, b_new).decision.deterministic_hash
    )
