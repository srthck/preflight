"""P0.4 §24 — the universal engine must not know the canonical demo exists.

A real leak was found and fixed this turn: ``semantic.py::_infer_api_class_name``
returned the literal strings ``"ProfileAPI"``/``"UserService"`` for *any*
repository's HTTP call, and every database entity in every repository was
labelled ``service="demo-commerce-db"``. An unrelated inventory repository
therefore produced an entity called ``pricing-engine.ProfileAPI``.

These tests lock that fix in: entity names must be derived from evidence
actually present in the analyzed repository (the URL's own host), never from
a fixed default borrowed from a fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

from preflight.ingestion import discovery
from preflight.orchestration import run_project_analysis
from preflight.semantic import SemanticAnalyzer

DEMO_VOCABULARY = (
    "demo-commerce",
    "ProfileAPI",
    "ProfileClient",
    "UserService",
    "phone_number",
    "QuickMart",
)


def _write(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


INVENTORY_REPO = {
    "inventory-service/src/inventory.py": '''
class InventoryTracker:
    def __init__(self, db):
        self._db = db

    def load_stock(self, sku_id: int):
        self._db.execute("SELECT sku, warehouse_qty FROM stock WHERE sku = ?")
        return {"sku": sku_id}

    def push_to_pricing(self, sku_id: int) -> None:
        _http_post("http://pricing-engine/v1/recalculate", self.load_stock(sku_id))


def _http_post(url: str, payload) -> None:
    pass
''',
}


def test_arbitrary_repository_never_inherits_demo_entity_names(tmp_path: Path) -> None:
    """The regression that was actually found: pricing-engine.ProfileAPI."""
    _write(tmp_path, INVENTORY_REPO)
    result = SemanticAnalyzer().analyze(tmp_path, files=discovery.find_semantic_files(tmp_path))

    entity_ids = set(result.graph.entity_ids)
    for leaked in DEMO_VOCABULARY:
        assert not any(leaked in entity_id for entity_id in entity_ids), (
            f"{leaked!r} leaked into an unrelated repository's graph: {sorted(entity_ids)}"
        )

    # The remote API entity must be named from its own real URL host.
    assert "pricing-engine.PricingEngine" in entity_ids


def test_database_entities_are_not_labelled_with_a_fixtures_database_name(
    tmp_path: Path,
) -> None:
    _write(tmp_path, INVENTORY_REPO)
    result = SemanticAnalyzer().analyze(tmp_path, files=discovery.find_semantic_files(tmp_path))

    db_entities = [
        result.graph.get_entity(entity_id)
        for entity_id in result.graph.entity_ids
        if result.graph.get_entity(entity_id).kind.value == "DATABASE"
    ]
    assert db_entities
    for entity in db_entities:
        assert entity.service == "database", f"unexpected database service label: {entity.service}"


def test_api_entity_name_tracks_the_actual_host(tmp_path: Path) -> None:
    """Change the URL host, and the derived entity name must change with it."""
    _write(
        tmp_path,
        {
            "svc/src/a.py": (
                'def go():\n    _http_post("http://fraud-detection/v2/score", {})\n\n\n'
                "def _http_post(url, payload):\n    pass\n"
            )
        },
    )
    result = SemanticAnalyzer().analyze(tmp_path, files=discovery.find_semantic_files(tmp_path))
    assert "fraud-detection.FraudDetection" in set(result.graph.entity_ids)


def test_full_uploaded_project_response_contains_no_demo_vocabulary(tmp_path: Path) -> None:
    """End-to-end: the entire serialized API response must be demo-free."""
    _write(
        tmp_path,
        {
            **INVENTORY_REPO,
            "db/schema.sql": "CREATE TABLE stock (sku INTEGER PRIMARY KEY, warehouse_qty INTEGER);",
            "db/migration.sql": "ALTER TABLE stock DROP COLUMN warehouse_qty;",
        },
    )
    result = run_project_analysis(tmp_path, case_id="c", scenario_label="inventory")
    serialized = json.dumps(result.to_response_payload())

    for leaked in DEMO_VOCABULARY:
        assert leaked not in serialized, f"{leaked!r} leaked into an arbitrary project's response"
