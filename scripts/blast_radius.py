#!/usr/bin/env python3
"""Developer CLI for deterministic blast-radius analysis."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))

from preflight.blast_radius import BlastRadiusEngine, blast_radius_sha256  # noqa: E402
from preflight.domain.blast_radius import BlastRadiusRequest  # noqa: E402
from preflight.semantic import SemanticAnalyzer  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(prog="preflight blast-radius")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--max-hops", type=int, default=3)
    parser.add_argument("--max-paths", type=int, default=100)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    root = args.root if args.root.is_absolute() else repo_root / args.root
    graph = SemanticAnalyzer().analyze(root).graph
    report = BlastRadiusEngine().analyze(
        graph,
        BlastRadiusRequest(
            target=args.target,
            max_hops=args.max_hops,
            max_paths=args.max_paths,
        ),
    )
    if args.as_json:
        print(json.dumps(report.model_dump(mode="json"), sort_keys=True, separators=(",", ":")))
    else:
        print("PRE-FLIGHT BLAST RADIUS")
        print(f"Changed: {report.target}")
        print(f"Affected: {report.summary.affected_count}")
        for finding in report.findings:
            print(
                f"{finding.category.value} {finding.affected_entity} "
                f"({finding.hop_distance} hops, severity {finding.severity:.6f})"
            )
            print(f"  Path: {' -> '.join(finding.path.nodes)}")
            print(f"  Why: {finding.reason}")
        print(f"BLAST_RADIUS_DVH: {blast_radius_sha256(report)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
