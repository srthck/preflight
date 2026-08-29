"""PreFlight CI gate — ``python scripts/preflight_check.py old.zip new.zip [--json]``.

Turns the real ``run_snapshot_comparison`` pipeline into a deployment gate
with a deterministic exit code, so a CI job can block a merge/deploy on
PreFlight's verdict instead of a human reading a dashboard. This file owns
no analysis logic — it reads two archive files from disk, extracts them
through the same secure ``extracted_project`` boundary the HTTP API uses,
and prints the same ``AnalysisRunResult.to_response_payload()`` contract the
frontend consumes.

Exit codes:
    SAFE          -> 0
    CAUTION       -> 1  (documented as non-blocking-by-default; a CI config
                          that wants CAUTION to pass should treat exit 1
                          specially rather than treat any nonzero as fatal)
    DO_NOT_DEPLOY -> 2
    UNKNOWN       -> 3  (never silently treated as passing)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from preflight.ingestion import (  # noqa: E402
    ArchiveTooLargeError,
    MalformedArchiveError,
    TooManyFilesError,
    UnsafeArchiveError,
    extracted_project,
)
from preflight.orchestration import run_snapshot_comparison  # noqa: E402

_EXIT_CODES = {
    "SAFE": 0,
    "CAUTION": 1,
    "DO_NOT_DEPLOY": 2,
    "UNKNOWN": 3,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="preflight check",
        description="Deployment-survival gate: compare OLD and NEW repository archives.",
    )
    parser.add_argument(
        "old_archive", type=Path, help="Path to the OLD (currently deployed) ZIP."
    )
    parser.add_argument("new_archive", type=Path, help="Path to the NEW (proposed) ZIP.")
    parser.add_argument(
        "--json", action="store_true", help="Print the full machine-readable result."
    )
    args = parser.parse_args(argv)

    for path in (args.old_archive, args.new_archive):
        if not path.exists():
            print(f"error: {path} does not exist", file=sys.stderr)
            return 3

    old_bytes = args.old_archive.read_bytes()
    new_bytes = args.new_archive.read_bytes()

    try:
        with extracted_project(old_bytes) as old_root, extracted_project(new_bytes) as new_root:
            result = run_snapshot_comparison(
                old_root,
                new_root,
                case_id=f"CLI-{args.old_archive.stem}-vs-{args.new_archive.stem}",
                old_label=args.old_archive.name,
                new_label=args.new_archive.name,
            )
    except (
        MalformedArchiveError,
        UnsafeArchiveError,
        TooManyFilesError,
        ArchiveTooLargeError,
    ) as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    payload = result.to_response_payload()
    decision = payload["decision_report"]["decision"]
    risk = payload["decision_report"]["risk_score"]

    if args.json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        print(f"PREFLIGHT: {decision} (risk {risk}/100)")
        for note in payload["analysis"]["notes"]:
            print(f"  - {note}")
        for entity in payload["decision_report"]["affected_entities"]:
            print(f"  affected: {entity}")

    return _EXIT_CODES.get(decision, 3)


if __name__ == "__main__":
    raise SystemExit(main())
