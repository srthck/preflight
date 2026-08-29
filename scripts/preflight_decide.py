"""CLI adapter for deterministic PreFlight decision evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from preflight.decision import DecisionRequest, decide


def main() -> int:
    parser = argparse.ArgumentParser(description="Produce a deterministic deployment decision.")
    parser.add_argument("--analysis", required=True, help="JSON normalized-analysis file")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    try:
        payload: dict[str, Any] = json.loads(Path(args.analysis).read_text(encoding="utf-8"))
        report = decide(DecisionRequest.model_validate(payload))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    output = report.model_dump(mode="json")
    if args.as_json:
        print(json.dumps(output, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    else:
        print(f"decision: {report.decision.value}")
        print(f"risk_score: {report.risk_score}")
        print(f"deterministic_hash: {report.deterministic_hash}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
