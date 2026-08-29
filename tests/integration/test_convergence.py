"""P0.4 — end-to-end convergence proof on a real, non-demo fixture.

P0.3 disclosed that convergence detection was unit-proven but NOT
fixture-proven end-to-end. This module closes that gap with
``fixtures/fleet-ops``: a repository deliberately unrelated to
demo-commerce in domain, table names, column names, and service names.

The causal structure, all derived by the real parsers from real source
files — nothing here is hand-encoded in the orchestrator:

    drivers.license_number --DB_READ--> DispatchService --HTTP_CALL--> ComplianceAPI
    drivers.medical_cert   --DB_READ--> AuditService    --HTTP_CALL--> ComplianceAPI

A migration dropping BOTH columns is two structurally independent changes
that converge on one downstream entity. The tests below prove the
convergence exists, that ComplianceAPI is counted once but retains both
causal paths, and — critically — that removing one upstream dependency
makes the convergence disappear.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from preflight.orchestration.models import AnalysisRunResult
from preflight.orchestration.pipeline import run_snapshot_comparison

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "fixtures" / "fleet-ops"

SHARED_API = "compliance-api.ComplianceAPI"
LICENCE_COLUMN = "drivers.license_number"
MEDICAL_COLUMN = "drivers.medical_cert"


def _build_pair(tmp_path: Path, *, migration: str | None = None) -> tuple[Path, Path]:
    """OLD = fixture with no migration proposed; NEW = fixture + the migration."""
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    shutil.copytree(FIXTURE, old_root)
    shutil.copytree(FIXTURE, new_root)
    (old_root / "database" / "migration.sql").unlink()
    if migration is not None:
        (new_root / "database" / "migration.sql").write_text(migration, encoding="utf-8")
    return old_root, new_root


@pytest.fixture()
def converging(tmp_path: Path) -> AnalysisRunResult:
    old_root, new_root = _build_pair(tmp_path)
    return run_snapshot_comparison(old_root, new_root, case_id="p04-convergence")


# ---------------------------------------------------------------------------
# The core proof
# ---------------------------------------------------------------------------


def test_migration_produces_two_independent_change_objects(converging: AnalysisRunResult) -> None:
    """A two-statement migration must never collapse into one 'primary' change."""
    payload = converging.to_response_payload()
    changes = payload["schema_changes"]
    assert len(changes) == 2
    assert {c["schema_object"] for c in changes} == {LICENCE_COLUMN, MEDICAL_COLUMN}
    assert all(c["kind"] == "DROP_COLUMN" for c in changes)
    # Both changes must resolve to real graph targets, not just be listed.
    assert all(c["resolved_as_blast_target"] for c in changes)


def test_both_changes_become_independent_blast_radius_targets(
    converging: AnalysisRunResult,
) -> None:
    payload = converging.to_response_payload()
    assert set(payload["blast_radius_targets"]) == {LICENCE_COLUMN, MEDICAL_COLUMN}
    assert payload["capabilities"]["blast_radius"]["status"] == "ANALYZED"


def test_two_independent_causes_converge_on_the_shared_api(
    converging: AnalysisRunResult,
) -> None:
    """The headline P0.4 claim, proven from real files rather than asserted."""
    payload = converging.to_response_payload()
    convergence = payload["convergence"]

    shared = [c for c in convergence if c["entity"] == SHARED_API]
    assert shared, f"expected {SHARED_API} to be convergent, got {convergence}"
    assert set(shared[0]["targets"]) == {LICENCE_COLUMN, MEDICAL_COLUMN}


def test_shared_api_counted_once_but_retains_both_causal_paths(
    converging: AnalysisRunResult,
) -> None:
    """Deduplicated in the aggregate count, never deduplicated in the evidence."""
    payload = converging.to_response_payload()

    affected = payload["decision_report"]["affected_entities"]
    assert affected.count(SHARED_API) == 1

    # ...but both independent causal paths survive in the findings.
    paths_to_shared = [
        f["path"]
        for f in payload["blast_radius"]["findings"]
        if f["affected_entity"] == SHARED_API
    ]
    assert len(paths_to_shared) == 2
    origins = {path["nodes"][0] for path in paths_to_shared}
    assert origins == {LICENCE_COLUMN, MEDICAL_COLUMN}


# ---------------------------------------------------------------------------
# Adversarial: the convergence must be causally real, not incidental
# ---------------------------------------------------------------------------


def test_dropping_only_one_column_removes_the_convergence(tmp_path: Path) -> None:
    """One change cannot converge with itself — a single target must yield none."""
    old_root, new_root = _build_pair(
        tmp_path, migration="ALTER TABLE drivers DROP COLUMN license_number;\n"
    )
    result = run_snapshot_comparison(old_root, new_root, case_id="single-target")
    payload = result.to_response_payload()

    assert payload["blast_radius_targets"] == [LICENCE_COLUMN]
    assert payload["convergence"] == []
    # The shared API is still affected — just no longer by two causes.
    assert SHARED_API in payload["decision_report"]["affected_entities"]


def test_removing_one_consumer_removes_the_convergence(tmp_path: Path) -> None:
    """Delete AuditService's dependency and the convergence must disappear.

    This is the strongest form of the proof: the convergence is a property of
    the real dependency graph, so removing one real upstream edge must remove
    it — if it survived, it would not have been derived from evidence.
    """
    old_root, new_root = _build_pair(tmp_path)
    for root in (old_root, new_root):
        shutil.rmtree(root / "audit-service")

    result = run_snapshot_comparison(old_root, new_root, case_id="consumer-removed")
    payload = result.to_response_payload()

    assert payload["convergence"] == []
    # medical_cert no longer has any reader, so it is no longer a graph target.
    assert payload["blast_radius_targets"] == [LICENCE_COLUMN]
    assert SHARED_API in payload["decision_report"]["affected_entities"]


def test_additive_migration_produces_no_destructive_convergence(tmp_path: Path) -> None:
    """ADD COLUMN touches nothing that exists — no targets, no convergence."""
    old_root, new_root = _build_pair(
        tmp_path, migration="ALTER TABLE drivers ADD COLUMN telematics_id TEXT;\n"
    )
    result = run_snapshot_comparison(old_root, new_root, case_id="additive")
    payload = result.to_response_payload()

    assert payload["convergence"] == []
    assert payload["blast_radius_targets"] == []
    assert payload["blast_radius"]["summary"]["affected_count"] == 0


def test_convergence_is_deterministic_across_runs(tmp_path: Path) -> None:
    old_a, new_a = _build_pair(tmp_path / "a")
    old_b, new_b = _build_pair(tmp_path / "b")
    result_a = run_snapshot_comparison(old_a, new_a, case_id="a")
    result_b = run_snapshot_comparison(old_b, new_b, case_id="b")

    assert result_a.convergent_entities == result_b.convergent_entities
    assert result_a.blast_radius_targets == result_b.blast_radius_targets
    assert result_a.decision.deterministic_hash == result_b.decision.deterministic_hash


# ---------------------------------------------------------------------------
# No demo leakage: this fixture must never produce demo-commerce vocabulary
# ---------------------------------------------------------------------------


def test_fleet_ops_analysis_contains_no_demo_commerce_vocabulary(
    converging: AnalysisRunResult,
) -> None:
    """An unrelated repository must never inherit the demo fixture's names."""
    import json

    serialized = json.dumps(converging.to_response_payload())
    for leaked in ("demo-commerce", "ProfileAPI", "UserService", "ProfileClient", "phone_number"):
        assert leaked not in serialized, f"{leaked!r} leaked into an unrelated repository's analysis"
