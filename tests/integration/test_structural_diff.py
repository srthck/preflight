"""P0.5 §4 — syntax-aware structural source diffing.

The governing rule: a structural change may only be reported when the parser
established it. A file that could not be parsed on either side must produce
NO symbol claims — "we could not read it" must never be rendered as "it was
removed", which is the failure mode a naive text diff would produce.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from preflight.orchestration.pipeline import run_snapshot_comparison
from preflight.structural_diff import (
    StructuralAnalysisStatus,
    StructuralChangeKind,
    compare_source_structure,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FLEET = REPO_ROOT / "fixtures" / "fleet-ops"

REMOVABLE_METHOD = '''    def submit_for_compliance_check(self, depot_code: str) -> None:
        """HTTP_CALL: DispatchService --> ComplianceAPI."""
        payload = self.load_dispatchable_drivers(depot_code)
        _http_post("http://compliance-api/v1/verify-dispatch", payload)
'''
DISPATCH = Path("dispatch-service/src/dispatch_service.py")


def _pair(tmp_path: Path) -> tuple[Path, Path]:
    old_root, new_root = tmp_path / "old", tmp_path / "new"
    shutil.copytree(FLEET, old_root)
    shutil.copytree(FLEET, new_root)
    (old_root / "database" / "migration.sql").unlink()
    return old_root, new_root


def test_removed_method_is_detected_with_source_location(tmp_path: Path) -> None:
    old_root, new_root = _pair(tmp_path)
    source = new_root / DISPATCH
    source.write_text(source.read_text(encoding="utf-8").replace(REMOVABLE_METHOD, ""), "utf-8")

    diff = compare_source_structure(old_root, new_root)
    removed = [c for c in diff.changes if c.kind == StructuralChangeKind.METHOD_REMOVED]
    assert len(removed) == 1
    change = removed[0]
    assert change.symbol == "DispatchService.submit_for_compliance_check"
    assert change.file == DISPATCH.as_posix()
    assert change.line is not None and change.line > 0
    assert change.language == "python"
    assert change.established_by == "tree-sitter"


def test_added_class_and_method_are_detected(tmp_path: Path) -> None:
    old_root, new_root = _pair(tmp_path)
    (new_root / "dispatch-service" / "src" / "optimizer.py").write_text(
        "class RouteOptimizer:\n    def plan(self):\n        pass\n", encoding="utf-8"
    )

    diff = compare_source_structure(old_root, new_root)
    kinds = {(c.kind, c.symbol) for c in diff.changes}
    assert (StructuralChangeKind.CLASS_ADDED, "RouteOptimizer") in kinds
    assert (StructuralChangeKind.METHOD_ADDED, "RouteOptimizer.plan") in kinds


def test_no_source_change_produces_no_structural_changes(tmp_path: Path) -> None:
    old_root, new_root = _pair(tmp_path)
    diff = compare_source_structure(old_root, new_root)
    assert diff.changes == ()
    # ...but the files were genuinely analyzed — zero changes is not zero analysis.
    assert diff.analyzed_file_count > 0
    assert all(s.status == StructuralAnalysisStatus.ANALYZED for s in diff.file_statuses)


def test_comment_only_edit_produces_no_structural_change(tmp_path: Path) -> None:
    """Text changed, structure did not — the parser must not invent a change."""
    old_root, new_root = _pair(tmp_path)
    source = new_root / DISPATCH
    source.write_text(
        source.read_text(encoding="utf-8") + "\n# an appended comment\n", encoding="utf-8"
    )
    assert compare_source_structure(old_root, new_root).changes == ()


def test_unparseable_file_makes_no_symbol_claims(tmp_path: Path) -> None:
    """The critical anti-fabrication case for structural diffing."""
    old_root, new_root = _pair(tmp_path)
    (new_root / DISPATCH).write_text(
        "class DispatchService:\n    def broken(  <<<< not python\n", encoding="utf-8"
    )

    diff = compare_source_structure(old_root, new_root)
    # No claim may be made about the broken file...
    assert not any(c.file == DISPATCH.as_posix() for c in diff.changes)
    # ...and it must be explicitly reported as unparseable rather than ignored.
    status = next(s for s in diff.file_statuses if s.file == DISPATCH.as_posix())
    assert status.status == StructuralAnalysisStatus.PARSE_ERROR
    assert diff.unsupported_file_count >= 1


def test_structural_diff_is_deterministic(tmp_path: Path) -> None:
    a_old, a_new = _pair(tmp_path / "a")
    b_old, b_new = _pair(tmp_path / "b")
    for root in (a_new, b_new):
        (root / "svc.py").write_text("def added():\n    pass\n", encoding="utf-8")

    diff_a = compare_source_structure(a_old, a_new)
    diff_b = compare_source_structure(b_old, b_new)
    assert [c.sort_key for c in diff_a.changes] == [c.sort_key for c in diff_b.changes]


def test_structural_diff_reaches_the_api_response(tmp_path: Path) -> None:
    old_root, new_root = _pair(tmp_path)
    source = new_root / DISPATCH
    source.write_text(source.read_text(encoding="utf-8").replace(REMOVABLE_METHOD, ""), "utf-8")

    payload = run_snapshot_comparison(old_root, new_root, case_id="s").to_response_payload()
    structural = payload["structural_diff"]
    assert structural is not None
    assert any(
        c["kind"] == "METHOD_REMOVED"
        and c["symbol"] == "DispatchService.submit_for_compliance_check"
        for c in structural["changes"]
    )
