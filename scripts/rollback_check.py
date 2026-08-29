"""CLI adapter for deterministic rollback truth analysis."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from preflight.api_contract import parse_openapi_document
from preflight.rollback_truth import (
    ApplicationSnapshot,
    RollbackRequest,
    RollbackWindow,
    analyze_rollback,
)
from preflight.schema import SchemaModel


def _read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _build_request(args: argparse.Namespace) -> RollbackRequest:
    old_app = ApplicationSnapshot.model_validate(_read_json(args.old_app))
    new_app = ApplicationSnapshot.model_validate(_read_json(args.new_app))
    old_schema = SchemaModel.model_validate(_read_json(args.old_schema))
    new_schema = SchemaModel.model_validate(_read_json(args.new_schema))
    old_api = parse_openapi_document(_read_json(args.old_api)) if args.old_api else None
    new_api = parse_openapi_document(_read_json(args.new_api)) if args.new_api else None
    return RollbackRequest(
        old_application=old_app,
        new_application=new_app,
        old_schema=old_schema,
        new_schema=new_schema,
        old_api=old_api,
        new_api=new_api,
        deployment_context=RollbackWindow(
            enabled=args.rollback_window,
            rollback_versions=tuple(args.rollback_version),
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze OLD application against NEW deployment state."
    )
    parser.add_argument("--old-app", required=True, help="JSON ApplicationSnapshot file")
    parser.add_argument("--new-app", required=True, help="JSON ApplicationSnapshot file")
    parser.add_argument("--old-schema", required=True, help="JSON SchemaModel file")
    parser.add_argument("--new-schema", required=True, help="JSON SchemaModel file")
    parser.add_argument("--old-api", help="JSON or YAML OpenAPI file")
    parser.add_argument("--new-api", help="JSON or YAML OpenAPI file")
    parser.add_argument("--rollback-version", action="append", default=[])
    parser.add_argument("--rollback-window", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    try:
        report = analyze_rollback(_build_request(args))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    payload = report.model_dump(mode="json")
    if args.as_json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    else:
        print(f"rollback_status: {report.status.value}")
        print(f"forward_compatibility: {report.forward_compatibility.value}")
        print(f"rollback_compatibility: {report.rollback_compatibility.value}")
        print(f"determinism_hash: {report.deterministic_hash}")
        for finding in report.findings:
            print(f"{finding.severity} {finding.rule_id}: {finding.reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
