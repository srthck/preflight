#!/usr/bin/env python3
"""PreFlight Day 1 smoke test.

Run with:
    python scripts/smoke.py

Every value printed here is derived from the actual graph.
No values are hard-coded or fabricated.
"""

from __future__ import annotations

import sys
import textwrap

# ---------------------------------------------------------------------------
# Ensure src/ is on the path when running from the repo root without install.
# ---------------------------------------------------------------------------
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# E402: imports must follow the sys.path manipulation above — this is intentional.
from preflight.domain.enums import EdgeKind  # noqa: E402
from preflight.fixtures.loader import (  # noqa: E402
    ENTITY_ANDROID_CLIENT,
    ENTITY_DB_COLUMN,
)
from preflight.graph.serialization import canonical_json, canonical_sha256  # noqa: E402
from preflight.graph.traversal import find_canonical_path  # noqa: E402
from preflight.semantic import SemanticAnalyzer  # noqa: E402


def _separator(char: str = "=", width: int = 48) -> str:
    return char * width


def run_smoke() -> int:
    """Execute the Day 1 smoke test. Returns 0 on pass, 1 on failure."""
    print(_separator())
    print("PRE-FLIGHT  DAY 3 SMOKE TEST")
    print(_separator())

    failures: list[str] = []

    # ------------------------------------------------------------------
    # 1. Build the canonical fixture graph
    # ------------------------------------------------------------------
    print("\nBuilding demo-commerce semantic graph...")
    try:
        semantic_result = SemanticAnalyzer().analyze(_REPO_ROOT / "fixtures" / "demo-commerce")
        graph = semantic_result.graph
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL: graph construction raised {type(exc).__name__}: {exc}")
        return 1

    print(f"  Graph nodes : {graph.node_count}")
    print(f"  Graph edges : {graph.edge_count}")

    if not semantic_result.edges:
        failures.append("Semantic analysis produced no edges")

    # ------------------------------------------------------------------
    # 2. Canonical 3-hop path traversal
    # ------------------------------------------------------------------
    print("\nTraversing canonical dependency path...")
    try:
        path = find_canonical_path(
            graph,
            origin=ENTITY_DB_COLUMN,
            terminal=ENTITY_ANDROID_CLIENT,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL: traversal raised {type(exc).__name__}: {exc}")
        return 1

    print("  Canonical dependency chain:")
    for i, node_id in enumerate(path.nodes):
        prefix = "  " if i == 0 else f"  --{path.edges[i - 1].value}-->"
        print(f"  {prefix} {node_id}")

    print(f"\n  Hop count   : {path.hop_count}")

    # Lowercase names to satisfy N806; these are module-level constants in spirit
    # but must be lowercase inside a function body per PEP 8 for local vars.
    expected_edges = (EdgeKind.DB_READ, EdgeKind.HTTP_CALL, EdgeKind.API_CONSUMES)

    if path.nodes[0] != ENTITY_DB_COLUMN or path.nodes[-1] != ENTITY_ANDROID_CLIENT:
        failures.append(f"Unexpected path endpoints: {path.nodes[0]} -> {path.nodes[-1]}")
    if path.edges != expected_edges:
        failures.append(
            f"Path edge kinds mismatch.\n  Expected: {expected_edges}\n  Got: {path.edges}"
        )
    if path.hop_count != 3:
        failures.append(f"Expected hop_count 3, got {path.hop_count}")

    canonical_path_status = "PASS" if not failures else "FAIL"
    print(f"  Canonical path check : {canonical_path_status}")

    # ------------------------------------------------------------------
    # 3. Deterministic serialization
    # ------------------------------------------------------------------
    print("\nVerifying deterministic serialization...")
    graph_b = SemanticAnalyzer().analyze(_REPO_ROOT / "fixtures" / "demo-commerce").graph
    json_a = canonical_json(graph)
    json_b = canonical_json(graph_b)
    sha_a = canonical_sha256(graph)
    sha_b = canonical_sha256(graph_b)

    det_ok = json_a == json_b and sha_a == sha_b
    det_status = "PASS" if det_ok else "FAIL"
    print(f"  canonical_json match : {det_status}")
    print(f"  SHA-256              : {sha_a}")

    if not det_ok:
        failures.append("Deterministic serialization failed: two builds produced different output.")

    # ------------------------------------------------------------------
    # 4. Summary
    # ------------------------------------------------------------------
    print()
    print(_separator())
    print("Fixture       : demo-commerce")
    print(f"Graph nodes   : {graph.node_count}")
    print(f"Graph edges   : {graph.edge_count}")
    print(f"Hop count     : {path.hop_count}")
    print(f"Determinism   : {det_status}")
    print(f"Canonical path: {canonical_path_status}")
    print()
    if failures:
        print("FAILURES:")
        for f in failures:
            for line in textwrap.wrap(f, width=46, initial_indent="  x ", subsequent_indent="    "):
                print(line)
        print()
        print("STATUS: DAY 1 FOUNDATION FAIL")
    else:
        print("STATUS: DAY 3 SEMANTIC PIPELINE PASS")
    print(_separator())

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(run_smoke())
