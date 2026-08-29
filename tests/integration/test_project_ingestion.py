"""ZIP -> ingestion -> orchestration -> decision, end to end.

These tests prove the claim this feature exists to make: the uploaded
*project contents* determine the result, not a scenario label — and the
result is exactly as deterministic through an archive upload as it is
through the fixture-scenario path proven in
``test_orchestration_pipeline.py``.
"""

from __future__ import annotations

import io
import random
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from preflight.decision import DecisionState
from preflight.ingestion import extracted_project
from preflight.orchestration import run_project_analysis
from preflight.orchestration.models import AnalysisRunResult
from preflight.rollback_truth import RollbackStatus

REPO_ROOT = Path(__file__).resolve().parents[2]
UPLOADS = REPO_ROOT / "fixtures" / "uploads"


def _analyze_zip(
    zip_path: Path, *, case_id: str = "test", scenario_label: str = "test"
) -> AnalysisRunResult:
    data = zip_path.read_bytes()
    with extracted_project(data) as root:
        return run_project_analysis(root, case_id=case_id, scenario_label=scenario_label)


# ---------------------------------------------------------------------------
# The killer proof: same migration text, different real dependency, different result.
# ---------------------------------------------------------------------------


def test_destructive_zip_is_do_not_deploy() -> None:
    result = _analyze_zip(UPLOADS / "destructive-release.zip")
    assert result.deployment_finding.change == "DROP_COLUMN"
    assert result.decision.decision == DecisionState.DO_NOT_DEPLOY
    assert result.rollback.status == RollbackStatus.UNSAFE
    assert result.blast_radius.summary.affected_count > 0


def test_safe_zip_is_safe() -> None:
    result = _analyze_zip(UPLOADS / "safe-release.zip")
    assert result.deployment_finding.change == "ADD_COLUMN"
    assert result.decision.decision == DecisionState.SAFE


def test_remediated_zip_changes_the_decision_via_real_dependency_removal() -> None:
    """Same DROP_COLUMN SQL as the destructive ZIP — the only real difference
    is that no source file references the column any more."""

    destructive = _analyze_zip(UPLOADS / "destructive-release.zip")
    remediated = _analyze_zip(UPLOADS / "remediated-release.zip")

    assert destructive.deployment_finding.change == remediated.deployment_finding.change == "DROP_COLUMN"
    assert destructive.decision.decision != remediated.decision.decision
    assert destructive.decision.risk_score > remediated.decision.risk_score
    assert destructive.rollback.status == RollbackStatus.UNSAFE
    assert remediated.rollback.status != RollbackStatus.UNSAFE
    assert destructive.blast_radius.summary.affected_count > remediated.blast_radius.summary.affected_count
    assert destructive.decision.deterministic_hash != remediated.decision.deterministic_hash


def test_renaming_the_upload_does_not_change_the_result() -> None:
    """The backend must never infer behavior from a filename/scenario label."""

    data = (UPLOADS / "destructive-release.zip").read_bytes()
    with extracted_project(data) as root:
        as_destructive = run_project_analysis(root, case_id="c", scenario_label="destructive")
    with extracted_project(data) as root:
        as_random_name = run_project_analysis(root, case_id="c", scenario_label="random-project-42")
    with extracted_project(data) as root:
        as_safe_label = run_project_analysis(root, case_id="c", scenario_label="safe")

    assert as_destructive.decision.deterministic_hash == as_random_name.decision.deterministic_hash
    assert as_destructive.decision.deterministic_hash == as_safe_label.decision.deterministic_hash
    assert as_safe_label.decision.decision == DecisionState.DO_NOT_DEPLOY  # label lied; evidence didn't


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_ten_runs_of_the_same_zip_produce_one_hash() -> None:
    data = (UPLOADS / "destructive-release.zip").read_bytes()
    hashes = set()
    for _ in range(10):
        with extracted_project(data) as root:
            result = run_project_analysis(root, case_id="c", scenario_label="s")
        hashes.add(result.decision.deterministic_hash)
    assert len(hashes) == 1


def test_shuffled_zip_entry_order_produces_the_same_hash() -> None:
    original = (UPLOADS / "destructive-release.zip").read_bytes()
    with zipfile.ZipFile(io.BytesIO(original)) as zf:
        entries = [(info.filename, zf.read(info.filename)) for info in zf.infolist()]

    shuffled_entries = list(entries)
    random.Random(7).shuffle(shuffled_entries)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in shuffled_entries:
            zf.writestr(name, content)
    shuffled = buf.getvalue()

    with extracted_project(original) as root:
        forward = run_project_analysis(root, case_id="c", scenario_label="s")
    with extracted_project(shuffled) as root:
        reordered = run_project_analysis(root, case_id="c", scenario_label="s")

    assert forward.decision.deterministic_hash == reordered.decision.deterministic_hash
    assert forward.manifest.manifest_hash == reordered.manifest.manifest_hash


def test_irrelevant_file_change_does_not_change_the_decision_hash() -> None:
    original = (UPLOADS / "destructive-release.zip").read_bytes()
    with zipfile.ZipFile(io.BytesIO(original)) as zf:
        entries = [(info.filename, zf.read(info.filename)) for info in zf.infolist()]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries:
            zf.writestr(name, content)
        zf.writestr("NOTES.txt", "This file is new and irrelevant to the analysis.\n")
    modified = buf.getvalue()

    with extracted_project(original) as root:
        before = run_project_analysis(root, case_id="c", scenario_label="s")
    with extracted_project(modified) as root:
        after = run_project_analysis(root, case_id="c", scenario_label="s")

    assert before.decision.deterministic_hash == after.decision.deterministic_hash
    assert before.manifest.manifest_hash != after.manifest.manifest_hash  # manifest sees the new file


def test_relevant_source_change_and_restore_roundtrips_the_hash() -> None:
    original = (UPLOADS / "destructive-release.zip").read_bytes()
    with zipfile.ZipFile(io.BytesIO(original)) as zf:
        entries = {info.filename: zf.read(info.filename) for info in zf.infolist()}

    def build(entries_map: dict[str, bytes]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in sorted(entries_map.items()):
                zf.writestr(name, content)
        return buf.getvalue()

    with extracted_project(build(entries)) as root:
        before = run_project_analysis(root, case_id="c", scenario_label="s")

    mutated = dict(entries)
    migration_key = next(k for k in mutated if k.endswith("database/migration.sql"))
    mutated[migration_key] = b"-- no-op\nSELECT 1;\n"
    with extracted_project(build(mutated)) as root:
        changed = run_project_analysis(root, case_id="c", scenario_label="s")

    assert changed.deployment_finding.change != "DROP_COLUMN"
    assert changed.decision.deterministic_hash != before.decision.deterministic_hash

    with extracted_project(build(entries)) as root:
        restored = run_project_analysis(root, case_id="c", scenario_label="s")
    assert restored.decision.deterministic_hash == before.decision.deterministic_hash


# ---------------------------------------------------------------------------
# Graceful degradation — UNKNOWN, never fabricated SAFE/DO_NOT_DEPLOY
# ---------------------------------------------------------------------------


def _build_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_empty_project_yields_unknown() -> None:
    data = _build_zip({"README.md": b"# empty project\n"})
    with extracted_project(data) as root:
        result = run_project_analysis(root, case_id="c", scenario_label="empty")
    assert result.decision.decision == DecisionState.UNKNOWN
    assert "semantic_analysis" in result.unavailable_components


def test_project_with_no_migration_continues_without_db_findings() -> None:
    data = _build_zip(
        {
            "app/main.py": (
                b"class UserService:\n"
                b"    def get(self):\n"
                b"        return {'id': 1}\n"
            ),
        }
    )
    with extracted_project(data) as root:
        result = run_project_analysis(root, case_id="c", scenario_label="no-migration")
    assert result.deployment_finding.change in {"PARSE_ERROR", "NO_CHANGE"}
    assert result.decision.decision != DecisionState.DO_NOT_DEPLOY


def test_project_with_no_openapi_reports_unavailable_not_fabricated_safe() -> None:
    data = _build_zip(
        {
            "app/main.py": b"class UserService:\n    pass\n",
            "db/schema.sql": b"CREATE TABLE users (id INTEGER);\n",
            "db/migration.sql": b"ALTER TABLE users ADD COLUMN note TEXT;\n",
        }
    )
    with extracted_project(data) as root:
        result = run_project_analysis(root, case_id="c", scenario_label="no-openapi")
    assert result.api_contract is None
    assert "api_contract" in result.unavailable_components
    # Missing evidence must surface as UNKNOWN, never be silently treated as SAFE.
    assert result.decision.decision == DecisionState.UNKNOWN


# ---------------------------------------------------------------------------
# HTTP boundary — scripts/preflight_api.py::analyze_project
# ---------------------------------------------------------------------------


HttpAnalyzeProject = Callable[..., tuple[int, dict[str, Any]]]


@pytest.fixture()
def http_analyze_project() -> HttpAnalyzeProject:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from preflight_api import analyze_project

    return analyze_project


def test_http_layer_accepts_a_real_upload_and_returns_full_payload(
    http_analyze_project: HttpAnalyzeProject,
) -> None:
    data = (UPLOADS / "destructive-release.zip").read_bytes()
    status, payload = http_analyze_project(data, case_id="PF-http-test")
    assert status == 200
    assert payload["decision_report"]["decision"] == "DO_NOT_DEPLOY"
    assert payload["project_manifest"]["file_count"] > 0
    assert payload["deterministic_hash"] == payload["decision_report"]["deterministic_hash"]


def test_http_layer_maps_malformed_archive_to_400(http_analyze_project: HttpAnalyzeProject) -> None:
    status, payload = http_analyze_project(b"not a zip", case_id="PF-http-test")
    assert status == 400
    assert payload["error"] == "INVALID_ARCHIVE"


def test_http_layer_maps_path_traversal_to_400(http_analyze_project: HttpAnalyzeProject) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../etc/escape.txt", "pwned")
    status, payload = http_analyze_project(buf.getvalue(), case_id="PF-http-test")
    assert status == 400
    assert payload["error"] == "UNSAFE_ARCHIVE"


def test_http_layer_never_returns_a_raw_traceback(http_analyze_project: HttpAnalyzeProject) -> None:
    status, payload = http_analyze_project(b"\x00\x01\x02garbage", case_id="PF-http-test")
    assert status in {400, 500}
    assert "Traceback" not in payload.get("detail", "")
    assert set(payload) == {"error", "detail"}
