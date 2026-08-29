"""Executable smoke test for the deployed PreFlight HTTP boundary."""

from __future__ import annotations

import json
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
SCENARIO = "demo-commerce-phone-number-removal"


def request(path: str, body: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body).encode() if body else None
    req = Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST" if data else "GET",
    )
    with urlopen(req, timeout=10) as response:  # noqa: S310 - explicit configured endpoint
        return response.status, json.loads(response.read().decode())


def analyze() -> dict[str, Any]:
    status, payload = request("/api/analyze", {"scenario": SCENARIO})
    if status != 200 or not isinstance(payload, dict):
        raise RuntimeError("canonical analysis failed")
    report = payload.get("decision_report")
    if not isinstance(report, dict):
        raise RuntimeError("missing decision_report")
    for field in ("decision", "risk_score", "deterministic_hash", "findings"):
        if field not in report:
            raise RuntimeError(f"missing DecisionReport field: {field}")
    return report


def main() -> int:
    try:
        health_status, health = request("/health")
        if health_status != 200 or health.get("status") != "online":
            raise RuntimeError("health check failed")
        first, second = analyze(), analyze()
    except (HTTPError, URLError, ValueError, RuntimeError) as error:
        print(f"STATUS: DAY 10 API INTEGRATION FAIL\n{error}")
        return 1
    match = first["deterministic_hash"] == second["deterministic_hash"]
    print("PRE-FLIGHT API SMOKE")
    print("Health: PASS")
    print("Canonical Analysis: PASS")
    print(f"Decision: {first['decision']}")
    print(f"Risk: {first['risk_score']}")
    print(f"Hash: {first['deterministic_hash']}")
    print("Second Run: PASS")
    print(f"Determinism: {'PASS' if match else 'FAIL'}")
    print(f"STATUS: DAY 10 API INTEGRATION {'PASS' if match else 'FAIL'}")
    return 0 if match else 1


if __name__ == "__main__":
    raise SystemExit(main())
