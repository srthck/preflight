#!/usr/bin/env python3
"""PreFlight static analysis inspection CLI.

Usage:
    python scripts/inspect.py <path>           # human-readable output
    python scripts/inspect.py <path> --json    # machine-readable JSON to stdout

All log/diagnostic messages go to stderr when --json is active.
All human-readable output goes to stdout.

The analysis is deterministic: running this command multiple times on the
same directory must produce identical JSON output (and identical DVH).

Security:
    Source files are read but never executed, imported, or evaluated.
    No external tools (compilers, linters) are invoked.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from preflight.graph.builder import GraphBuilder  # noqa: E402
from preflight.graph.parsers.extractor import SourceExtractor  # noqa: E402
from preflight.graph.serialization import canonical_sha256  # noqa: E402


def _sep(char: str = "─", width: int = 48) -> str:
    return char * width


def run_human(root_path: Path) -> int:
    extractor = SourceExtractor()
    result = extractor.extract(root_path)

    # Build a graph from the extracted entities/edges to get the DVH.
    builder = GraphBuilder()
    for entity in result.entities:
        try:
            builder.add_entity(entity)
        except Exception:  # noqa: BLE001
            pass  # duplicate entities are skipped silently
    for edge in result.edges:
        try:
            builder.add_dependency(edge)
        except Exception:  # noqa: BLE001
            pass

    graph = builder.build()
    dvh = canonical_sha256(graph) if graph.node_count > 0 else "(no entities)"

    print("PreFlight Static Analysis")
    print(_sep())
    print(f"Path      : {root_path}")
    print(f"Files     : {result.file_count}")

    lang_counts = result.language_counts
    for lang, count in sorted(lang_counts.items()):
        print(f"  {lang:<10}: {count}")

    print(f"Symbols   : {result.symbol_count}")
    print(f"References: {result.reference_count}")
    print(f"Resolved  : {result.resolved_count}")
    print(f"Unresolved: {result.unresolved_count}")
    print(f"Diagnostics: {len(result.diagnostics)}")
    print(_sep())
    print(f"Graph Entities: {graph.node_count}")
    print(f"Graph Edges   : {graph.edge_count}")
    print(f"DVH           : {dvh}")
    print(_sep())
    print("Performance")
    for k, v in result.performance.to_dict().items():
        print(f"  {k:<22}: {v}")
    print(_sep())

    if result.diagnostics:
        print("Diagnostics:")
        for d in result.diagnostics:
            loc = f"{d.file_path}:{d.line or '?'}"
            print(f"  [{d.severity.value}] {d.code.value} @ {loc}: {d.message[:80]}")

    return 0


def run_json(root_path: Path) -> int:
    extractor = SourceExtractor()
    result = extractor.extract(root_path)

    builder = GraphBuilder()
    for entity in result.entities:
        try:
            builder.add_entity(entity)
        except Exception:  # noqa: BLE001
            pass
    for edge in result.edges:
        try:
            builder.add_dependency(edge)
        except Exception:  # noqa: BLE001
            pass

    graph = builder.build()
    dvh = canonical_sha256(graph) if graph.node_count > 0 else None

    output = {
        "path": str(root_path),
        "file_count": result.file_count,
        "language_counts": result.language_counts,
        "symbol_count": result.symbol_count,
        "reference_count": result.reference_count,
        "resolved_count": result.resolved_count,
        "unresolved_count": result.unresolved_count,
        "diagnostic_count": len(result.diagnostics),
        "graph": {
            "node_count": graph.node_count,
            "edge_count": graph.edge_count,
            "dvh": dvh,
            "entities": sorted(graph.entity_ids),
        },
        "diagnostics": [
            {
                "code": d.code.value,
                "severity": d.severity.value,
                "message": d.message,
                "file": d.file_path,
                "line": d.line,
                "column": d.column,
            }
            for d in result.diagnostics
        ],
        "performance": result.performance.to_dict(),
    }

    # Deterministic JSON — sorted keys, compact.
    print(json.dumps(output, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("Usage: python scripts/inspect.py <path> [--json]", file=sys.stderr)
        return 2

    json_mode = "--json" in args
    path_args = [a for a in args if a != "--json"]
    if not path_args:
        print("Error: no path specified.", file=sys.stderr)
        return 2

    root_path = Path(path_args[0]).resolve()
    if not root_path.exists():
        print(f"Error: path does not exist: {root_path}", file=sys.stderr)
        return 2

    if json_mode:
        return run_json(root_path)
    return run_human(root_path)


if __name__ == "__main__":
    sys.exit(main())
