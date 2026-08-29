"""DispatchService — Fleet Ops static-analysis fixture.

Encodes: drivers.license_number --DB_READ--> DispatchService --HTTP_CALL--> ComplianceAPI

This is a static analysis fixture, not executable production code.
"""

from __future__ import annotations


class DispatchService:
    """Assigns routes to drivers, gated on a valid driving licence."""

    def __init__(self, db_connection: object) -> None:
        self._db = db_connection

    def load_dispatchable_drivers(self, depot_code: str) -> dict[str, object]:
        """SELECT id, full_name, license_number FROM drivers WHERE depot_code = ?"""
        self._db.execute("SELECT id, full_name, license_number FROM drivers WHERE depot_code = ?")
        return {"depot_code": depot_code}

    def submit_for_compliance_check(self, depot_code: str) -> None:
        """HTTP_CALL: DispatchService --> ComplianceAPI."""
        payload = self.load_dispatchable_drivers(depot_code)
        _http_post("http://compliance-api/v1/verify-dispatch", payload)


def _http_post(url: str, payload: dict[str, object]) -> None:
    """Fixture stub representing an outbound HTTP POST."""
    _ = (url, payload)
