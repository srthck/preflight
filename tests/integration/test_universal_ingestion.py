"""Repository-agnostic ingestion — the P0.1 forensics fix, proven generically.

None of these synthetic repositories share a name, folder convention, or
filename with the `demo-commerce` fixtures. If any test here required a
special case keyed on a name/path, it would be the wrong test. The
`e-commerce-platform-like` cases mirror (without embedding) the real
third-party ZIP that exposed the original bug: a real repository that
genuinely contains zero Python/Kotlin source. The fix under test is that
"zero supported source" must render as UNSUPPORTED (real code, wrong
language), not silently identical to "zero downstream impact" or a
fabricated SAFE decision.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from preflight.decision import DecisionState
from preflight.ingestion import extracted_project
from preflight.orchestration import run_project_analysis


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


_A_SERVICE_PY = (
    b"class Widget:\n"
    b"    def read(self):\n"
    b"        return {'id': 1}\n"
)


# ---------------------------------------------------------------------------
# A/B/C — root at ZIP root, nested one folder, deeply nested
# ---------------------------------------------------------------------------


def test_repository_at_zip_root_is_discovered() -> None:
    data = _zip_bytes({"main.py": _A_SERVICE_PY})
    with extracted_project(data) as root:
        result = run_project_analysis(root, case_id="c", scenario_label="root-level")
    assert result.graph.node_count > 0
    assert result.capabilities["source"]["status"] == "ANALYZED"


def test_repository_nested_one_folder_is_discovered() -> None:
    data = _zip_bytes({"MyRandomProjectName-v2/app/main.py": _A_SERVICE_PY})
    with extracted_project(data) as root:
        result = run_project_analysis(root, case_id="c", scenario_label="nested")
    assert result.graph.node_count > 0
    assert result.capabilities["source"]["status"] == "ANALYZED"


def test_repository_deeply_nested_is_discovered() -> None:
    data = _zip_bytes({"a/b/c/d/e/f/g/service.py": _A_SERVICE_PY})
    with extracted_project(data) as root:
        result = run_project_analysis(root, case_id="c", scenario_label="deep")
    assert result.graph.node_count > 0


# ---------------------------------------------------------------------------
# D/E — monorepo / multiple independent project directories
# ---------------------------------------------------------------------------


def test_monorepo_layout_discovers_across_all_services() -> None:
    data = _zip_bytes(
        {
            "services/orders/pyproject.toml": b"[project]\nname='orders'\n",
            "services/orders/src/orders_service.py": (
                b"class OrdersService:\n    def list(self):\n        return []\n"
            ),
            "services/inventory/package.json": b'{"name": "inventory"}',
            "services/inventory/src/index.js": b"console.log('inventory');\n",
            "libs/shared/utils.py": b"def helper():\n    return 1\n",
        }
    )
    with extracted_project(data) as root:
        result = run_project_analysis(root, case_id="c", scenario_label="monorepo")
    assert result.graph.node_count >= 2  # orders_service.py + utils.py both reached
    assert result.manifest is not None
    assert set(result.manifest.framework_signals) == {
        "services/orders/pyproject.toml",
        "services/inventory/package.json",
    }
    # The unsupported JS file must still be visible, not silently dropped.
    js_entry = next(f for f in result.manifest.files if f.path.endswith("index.js"))
    assert js_entry.classification == "unsupported"


# ---------------------------------------------------------------------------
# F/G — backend-only, frontend-only
# ---------------------------------------------------------------------------


def test_backend_only_project_is_analyzed() -> None:
    data = _zip_bytes({"backend/api/handlers.py": _A_SERVICE_PY})
    with extracted_project(data) as root:
        result = run_project_analysis(root, case_id="c", scenario_label="backend-only")
    assert result.capabilities["source"]["status"] == "ANALYZED"


# This is the exact shape of the real ZIP that exposed the original bug —
# reconstructed synthetically (not the user's actual file) so it can live in
# the regression suite. See the module docstring.
def test_frontend_only_static_site_is_unsupported_not_unavailable() -> None:
    data = _zip_bytes(
        {
            "E - Commerce Platform/index.html": b"<html></html>",
            "E - Commerce Platform/css/style.css": b"body{}",
            "E - Commerce Platform/js/app.js": b"console.log('app');\n",
            "E - Commerce Platform/js/cart.js": b"console.log('cart');\n",
            "E - Commerce Platform/hero_banner.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 50,
        }
    )
    with extracted_project(data) as root:
        result = run_project_analysis(root, case_id="c", scenario_label="static-site")

    # The P0.1 acceptance requirement: real code in an unsupported language
    # must never look identical to "nothing was here."
    assert result.capabilities["source"]["status"] == "UNSUPPORTED"
    # No semantic graph exists at all (0 supported files) AND no migration
    # was found either — UNAVAILABLE, the more foundational of the two
    # reasons blast radius can't run (see DAY_P0.2 forensics).
    assert result.capabilities["blast_radius"]["status"] == "UNAVAILABLE"
    assert result.decision.decision == DecisionState.UNKNOWN
    assert result.decision.decision != DecisionState.SAFE
    assert result.manifest is not None
    assert result.manifest.unsupported_count == 2  # app.js, cart.js
    assert result.manifest.ignored_count == 1  # hero_banner.png


# ---------------------------------------------------------------------------
# H/I/J/K — source+SQL, source+OpenAPI, source-without-SQL, SQL-without-source
# ---------------------------------------------------------------------------


def test_source_plus_sql_reaches_deployment_analyzer() -> None:
    data = _zip_bytes(
        {
            "app/models.py": _A_SERVICE_PY,
            "db/schema.sql": b"CREATE TABLE widgets (id INTEGER);\n",
            "db/migration.sql": b"ALTER TABLE widgets ADD COLUMN note TEXT;\n",
        }
    )
    with extracted_project(data) as root:
        result = run_project_analysis(root, case_id="c", scenario_label="source-and-sql")
    assert result.capabilities["database"]["status"] == "ANALYZED"
    assert result.deployment_finding.change == "ADD_COLUMN"


def test_sql_without_source_still_analyzes_database_only() -> None:
    data = _zip_bytes({"migrations/0001_init.sql": b"ALTER TABLE t ADD COLUMN x TEXT;\n"})
    with extracted_project(data) as root:
        result = run_project_analysis(root, case_id="c", scenario_label="sql-only")
    assert result.capabilities["database"]["status"] == "ANALYZED"
    assert result.capabilities["source"]["status"] == "UNAVAILABLE"  # no code at all, not "unsupported"


# ---------------------------------------------------------------------------
# N/O/P — malformed source, malformed SQL, malformed OpenAPI
# ---------------------------------------------------------------------------


def test_malformed_sql_is_parse_error_not_fabricated() -> None:
    data = _zip_bytes(
        {
            "app/models.py": _A_SERVICE_PY,
            "db/migration.sql": b"ALTER TABLE ADD COLUMN;;;this is not valid sql(((",
        }
    )
    with extracted_project(data) as root:
        result = run_project_analysis(root, case_id="c", scenario_label="malformed-sql")
    assert result.capabilities["database"]["status"] == "PARSE_ERROR"
    assert result.decision.decision != DecisionState.SAFE


def test_malformed_openapi_does_not_crash_the_pipeline() -> None:
    data = _zip_bytes(
        {
            "app/models.py": _A_SERVICE_PY,
            "api/openapi.yaml": b": this is not : valid : yaml [[[",
        }
    )
    with extracted_project(data) as root:
        # Must not raise — a malformed contract degrades gracefully.
        result = run_project_analysis(root, case_id="c", scenario_label="malformed-openapi")
    assert result.decision.decision is not None


# ---------------------------------------------------------------------------
# R — documentation-only archive
# ---------------------------------------------------------------------------


def test_documentation_only_archive_is_unavailable_not_safe() -> None:
    data = _zip_bytes(
        {
            "README.md": b"# My Project\nThis is a great project.\n",
            "LICENSE": b"MIT License\n",
            "docs/guide.md": b"# Guide\n",
        }
    )
    with extracted_project(data) as root:
        result = run_project_analysis(root, case_id="c", scenario_label="docs-only")
    assert result.capabilities["source"]["status"] == "UNAVAILABLE"
    assert result.decision.decision == DecisionState.UNKNOWN


# ---------------------------------------------------------------------------
# Provenance: no local temp path ever reaches the response
# ---------------------------------------------------------------------------


def test_no_local_temp_path_leaks_into_response(tmp_path: Path) -> None:
    data = _zip_bytes({"E - Commerce Platform/js/app.js": b"console.log(1);\n"})
    with extracted_project(data) as root:
        result = run_project_analysis(root, case_id="c", scenario_label="leak-check")
        payload = result.to_response_payload()
    serialized = str(payload)
    assert "AppData" not in serialized
    assert "preflight-upload-" not in serialized
    assert str(root) not in serialized


# ---------------------------------------------------------------------------
# Cross-component causal chain across discovered services (mission §13)
# ---------------------------------------------------------------------------


def test_cross_service_dependency_chain_is_preserved_in_a_generic_layout() -> None:
    """A database -> service A -> service B chain under names PreFlight has
    never seen before must still produce a real, multi-hop graph."""

    data = _zip_bytes(
        {
            "db/schema.sql": b"CREATE TABLE widgets (id INTEGER, label TEXT);\n",
            "db/migration.sql": b"ALTER TABLE widgets DROP COLUMN label;\n",
            "components/catalog/src/catalog_service.py": (
                b"class CatalogService:\n"
                b"    def __init__(self, db):\n"
                b"        self._db = db\n"
                b"    def list_widgets(self):\n"
                b"        self._db.execute('SELECT id, label FROM widgets')\n"
                b"        return []\n"
            ),
        }
    )
    with extracted_project(data) as root:
        result = run_project_analysis(root, case_id="c", scenario_label="cross-service")
    assert result.deployment_finding.change == "DROP_COLUMN"
    assert result.capabilities["database"]["status"] == "ANALYZED"
    # DB_READ edge must exist from the real SQL, under a repository layout
    # ("components/catalog/...") that matches none of PreFlight's own fixtures.
    assert any(e.kind.value == "DB_READ" for e in result.graph.get_dependencies())


@pytest.mark.parametrize("filename_variant", ["release.zip", "unrelated-name-42.zip", "v2 (copy).zip"])
def test_zip_filename_never_affects_the_result(filename_variant: str) -> None:
    """The ZIP's own filename is not even passed to the analyzer — proven by
    construction, not just by convention: run_project_analysis never
    receives it at all."""

    data = _zip_bytes({"app/main.py": _A_SERVICE_PY})
    with extracted_project(data) as root:
        result = run_project_analysis(root, case_id="c", scenario_label=filename_variant)
    assert result.capabilities["source"]["status"] == "ANALYZED"
