"""Unit tests for the P0.3 ``ChangeSet``/``RepositoryDiff`` comparator.

Covers: content-identity diffing (never filename-only), domain
classification, and determinism independent of filesystem walk order.
"""

from __future__ import annotations

from pathlib import Path

from preflight.diffing import build_change_set, classify_change_domain, compare_repositories
from preflight.domain.blast_radius import (
    BlastRadiusFinding,
    BlastRadiusReport,
    ImpactCategory,
    ImpactPath,
    ImpactSummary,
)
from preflight.domain.change_set import ChangeDomain, ChangeSource, FileChangeStatus
from preflight.domain.enums import EdgeKind
from preflight.orchestration.pipeline import _detect_convergence, _merge_blast_radius


def _write_tree(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Content-identity diffing
# ---------------------------------------------------------------------------


def test_diff_classifies_added_removed_modified_and_same(tmp_path: Path) -> None:
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    _write_tree(old_root, {"a.py": "x = 1\n", "b.py": "y = 2\n", "gone.py": "z = 3\n"})
    _write_tree(new_root, {"a.py": "x = 1\n", "b.py": "y = 999\n", "new.py": "w = 4\n"})

    diff = compare_repositories(old_root, new_root, old_label="old", new_label="new")
    by_path = {f.path: f.status for f in diff.files}

    assert by_path["a.py"] == FileChangeStatus.SAME
    assert by_path["b.py"] == FileChangeStatus.MODIFIED
    assert by_path["gone.py"] == FileChangeStatus.REMOVED
    assert by_path["new.py"] == FileChangeStatus.ADDED
    assert diff.added_count == 1
    assert diff.removed_count == 1
    assert diff.modified_count == 1
    assert diff.same_count == 1
    assert diff.diff_hash


def test_diff_uses_content_identity_not_filename_or_mtime(tmp_path: Path) -> None:
    """Identical bytes under the same path are SAME even after a touch/rewrite."""
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    _write_tree(old_root, {"same.py": "identical\n"})
    _write_tree(new_root, {"same.py": "identical\n"})

    diff = compare_repositories(old_root, new_root, old_label="old", new_label="new")
    assert diff.files[0].status == FileChangeStatus.SAME
    assert diff.files[0].old_sha256 == diff.files[0].new_sha256


def test_diff_ignores_build_and_vcs_directories(tmp_path: Path) -> None:
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    _write_tree(old_root, {"src/a.py": "1\n"})
    _write_tree(new_root, {"src/a.py": "1\n", "node_modules/pkg/index.js": "junk\n"})

    diff = compare_repositories(old_root, new_root, old_label="old", new_label="new")
    assert all("node_modules" not in f.path for f in diff.files)


# ---------------------------------------------------------------------------
# Determinism — walk order must never affect the hash
# ---------------------------------------------------------------------------


def test_diff_hash_is_stable_regardless_of_file_creation_order(tmp_path: Path) -> None:
    old_a, new_a = tmp_path / "a_old", tmp_path / "a_new"
    old_b, new_b = tmp_path / "b_old", tmp_path / "b_new"

    # Same content, files written in reverse order between the two trials.
    for name, content in [("z.py", "1\n"), ("m.py", "2\n"), ("a.py", "3\n")]:
        _write_tree(old_a, {name: content})
        _write_tree(new_a, {name: content + "x"})
    for name, content in [("a.py", "3\n"), ("m.py", "2\n"), ("z.py", "1\n")]:
        _write_tree(old_b, {name: content})
        _write_tree(new_b, {name: content + "x"})

    diff_a = compare_repositories(old_a, new_a, old_label="old", new_label="new")
    diff_b = compare_repositories(old_b, new_b, old_label="old", new_label="new")
    assert diff_a.diff_hash == diff_b.diff_hash


def test_change_set_hash_is_deterministic(tmp_path: Path) -> None:
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    _write_tree(old_root, {"db/migration.sql": "SELECT 1;\n"})
    _write_tree(new_root, {"db/migration.sql": "SELECT 2;\n"})

    diff = compare_repositories(old_root, new_root, old_label="old", new_label="new")
    change_set_1 = build_change_set(diff)
    change_set_2 = build_change_set(diff)
    assert change_set_1.change_set_hash == change_set_2.change_set_hash
    assert ChangeDomain.DATABASE in change_set_1.changed_domains
    assert change_set_1.source == ChangeSource.SNAPSHOT_PAIR


# ---------------------------------------------------------------------------
# Domain classification — real filename evidence, never a guess
# ---------------------------------------------------------------------------


def test_classify_change_domain_by_real_naming_convention() -> None:
    assert classify_change_domain("service.py") == (ChangeDomain.SOURCE,)
    assert classify_change_domain("db/migration.sql") == (ChangeDomain.DATABASE,)
    assert classify_change_domain("api/openapi.yaml") == (ChangeDomain.API,)
    assert classify_change_domain("Dockerfile") == (ChangeDomain.DEPLOYMENT,)
    assert classify_change_domain("docker-compose.yml") == (ChangeDomain.DEPLOYMENT,)
    assert classify_change_domain("infra/main.tf") == (ChangeDomain.DEPLOYMENT,)
    assert classify_change_domain("package.json") == (ChangeDomain.DEPENDENCY,)
    assert classify_change_domain("requirements.txt") == (ChangeDomain.DEPENDENCY,)
    assert classify_change_domain(".env") == (ChangeDomain.CONFIG,)
    assert classify_change_domain("config.yaml") == (ChangeDomain.CONFIG,)
    assert classify_change_domain("README.md") == (ChangeDomain.UNKNOWN,)


# ---------------------------------------------------------------------------
# Multi-target blast-radius merge and convergence detection
# ---------------------------------------------------------------------------


def _finding(target: str, entity: str, hop: int) -> BlastRadiusFinding:
    return BlastRadiusFinding(
        target=target,
        affected_entity=entity,
        severity=0.5,
        hop_distance=hop,
        category=ImpactCategory.DIRECT if hop == 1 else ImpactCategory.INDIRECT,
        path=ImpactPath(nodes=(target, entity), edge_types=(EdgeKind.DB_READ,)),
        reason="test",
    )


def _report(target: str, findings: tuple[BlastRadiusFinding, ...]) -> BlastRadiusReport:
    direct = sum(1 for f in findings if f.category == ImpactCategory.DIRECT)
    indirect = len(findings) - direct
    return BlastRadiusReport(
        target=target,
        max_hops=3,
        max_paths=100,
        findings=findings,
        summary=ImpactSummary(direct_count=direct, indirect_count=indirect, affected_count=len(findings)),
    )


def test_merge_blast_radius_dedupes_affected_count_across_targets() -> None:
    report_a = _report("db.col", (_finding("db.col", "ServiceX", 1), _finding("db.col", "ServiceY", 2)))
    report_b = _report("api.route", (_finding("api.route", "ServiceX", 1),))

    merged = _merge_blast_radius([report_a, report_b], {"db.col", "api.route"})
    # ServiceX reached from both targets -> one distinct affected entity, not two.
    assert merged.summary.affected_count == 2
    assert len(merged.findings) == 3


def test_detect_convergence_flags_entities_reached_from_multiple_targets() -> None:
    report_a = _report("db.col", (_finding("db.col", "ServiceX", 1),))
    report_b = _report("api.route", (_finding("api.route", "ServiceX", 1), _finding("api.route", "ServiceZ", 1)))

    convergence = _detect_convergence([report_a, report_b])
    assert len(convergence) == 1
    assert convergence[0]["entity"] == "ServiceX"
    assert set(convergence[0]["targets"]) == {"db.col", "api.route"}


def test_detect_convergence_empty_when_targets_do_not_overlap() -> None:
    report_a = _report("db.col", (_finding("db.col", "ServiceX", 1),))
    report_b = _report("api.route", (_finding("api.route", "ServiceZ", 1),))
    assert _detect_convergence([report_a, report_b]) == ()
