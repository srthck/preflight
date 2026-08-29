"""P0.3 end-to-end proof: SNAPSHOT_PAIR analysis on the real demo-commerce fixture.

OLD = the demo-commerce repository as it exists in production today (no
migration file present at all — nothing has been proposed yet). NEW = the
same repository plus the real ``database/migration.sql`` (``ALTER TABLE
users DROP COLUMN phone_number``). This is not a synthetic toy: it is the
exact fixture the canonical single-repository demo already proves, replayed
as a genuine two-repository comparison to prove the new ``ChangeSet``/
``run_snapshot_comparison`` path produces the same causal result through a
completely different code path (real content diffing, real dual semantic
analysis, real OLD-graph blast-radius traversal) rather than one hand-tuned
for a single scenario.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from preflight.decision import DecisionState
from preflight.domain.change_set import ChangeDomain, FileChangeStatus
from preflight.orchestration.models import AnalysisRunResult
from preflight.orchestration.pipeline import run_snapshot_comparison

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "fixtures" / "demo-commerce"


def _build_old_new(tmp_path: Path) -> tuple[Path, Path]:
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    shutil.copytree(FIXTURE, old_root)
    shutil.copytree(FIXTURE, new_root)
    # OLD: nothing proposed yet — remove both migration candidates.
    (old_root / "database" / "migration.sql").unlink()
    (old_root / "database" / "migration_safe.sql").unlink()
    # NEW: only the real destructive migration is proposed.
    (new_root / "database" / "migration_safe.sql").unlink()
    return old_root, new_root


@pytest.fixture()
def snapshot_pair(tmp_path: Path) -> AnalysisRunResult:
    old_root, new_root = _build_old_new(tmp_path)
    return run_snapshot_comparison(old_root, new_root, case_id="p03-test")


def test_change_set_correctly_identifies_the_added_migration(
    snapshot_pair: AnalysisRunResult,
) -> None:
    change_set = snapshot_pair.change_set
    assert change_set is not None
    diff = change_set.repository_diff
    assert diff is not None

    migration_change = next(f for f in diff.files if f.path == "database/migration.sql")
    assert migration_change.status == FileChangeStatus.ADDED
    assert ChangeDomain.DATABASE in migration_change.domains

    # The unrelated files (service source, API contract, README) must be SAME —
    # only the migration was actually added between OLD and NEW.
    unrelated = [f for f in diff.files if f.path != "database/migration.sql"]
    assert all(f.status == FileChangeStatus.SAME for f in unrelated)
    assert diff.added_count == 1
    assert diff.removed_count == 0
    assert diff.modified_count == 0


def test_snapshot_pair_reaches_the_same_causal_verdict_as_the_canonical_demo(
    snapshot_pair: AnalysisRunResult,
) -> None:
    payload = snapshot_pair.to_response_payload()

    assert snapshot_pair.deployment_finding.change == "DROP_COLUMN"
    assert snapshot_pair.deployment_finding.schema_object == "users.phone_number"
    assert payload["capabilities"]["database"]["status"] == "ANALYZED"

    # Blast radius traversed over the OLD graph — the same 3-entity chain
    # (UserService -> ProfileAPI -> AndroidClient) the canonical demo proves.
    assert payload["blast_radius"]["summary"]["affected_count"] == 3
    assert payload["capabilities"]["blast_radius"]["status"] == "ANALYZED"

    assert snapshot_pair.decision.decision == DecisionState.DO_NOT_DEPLOY
    assert "users.phone_number" in payload["decision_report"]["affected_entities"]


def test_snapshot_pair_determinism_across_independent_extractions(tmp_path: Path) -> None:
    old_a, new_a = _build_old_new(tmp_path / "run-a")
    old_b, new_b = _build_old_new(tmp_path / "run-b")

    result_a = run_snapshot_comparison(old_a, new_a, case_id="a")
    result_b = run_snapshot_comparison(old_b, new_b, case_id="b")

    assert result_a.change_set is not None and result_b.change_set is not None
    assert result_a.change_set.change_set_hash == result_b.change_set.change_set_hash
    assert result_a.decision.deterministic_hash == result_b.decision.deterministic_hash


def test_unchanged_repository_pair_is_safe_with_zero_blast_radius(tmp_path: Path) -> None:
    """OLD == NEW (nothing proposed) must never manufacture a phantom finding."""
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    shutil.copytree(FIXTURE, old_root)
    shutil.copytree(FIXTURE, new_root)
    for root in (old_root, new_root):
        (root / "database" / "migration.sql").unlink()
        (root / "database" / "migration_safe.sql").unlink()

    result = run_snapshot_comparison(old_root, new_root, case_id="no-op")
    payload = result.to_response_payload()

    assert result.change_set is not None
    diff = result.change_set.repository_diff
    assert diff is not None and len(diff.changed_files) == 0
    assert payload["capabilities"]["database"]["status"] == "UNAVAILABLE"
    # The semantic graph ran fine (real source exists on both sides); there is
    # simply no change to compute impact for — NOT_APPLICABLE, not UNAVAILABLE
    # (see DAY_P0.2 forensics for why these two must never be conflated).
    assert payload["capabilities"]["blast_radius"]["status"] == "NOT_APPLICABLE"
    assert payload["blast_radius"]["summary"]["affected_count"] == 0
    assert payload["decision_report"]["affected_entities"] == []
