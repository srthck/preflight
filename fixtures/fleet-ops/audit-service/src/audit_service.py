"""AuditService — Fleet Ops static-analysis fixture.

Encodes: drivers.medical_cert --DB_READ--> AuditService --HTTP_CALL--> ComplianceAPI

Structurally independent of DispatchService: it reads a different column and
serves a different business purpose, but calls the SAME downstream API. That
shared downstream is the convergence point this fixture exists to prove.
"""

from __future__ import annotations


class AuditService:
    """Audits driver medical certification for regulatory reporting."""

    def __init__(self, db_connection: object) -> None:
        self._db = db_connection

    def load_certification_records(self, depot_code: str) -> dict[str, object]:
        """SELECT id, medical_cert FROM drivers WHERE depot_code = ?"""
        self._db.execute("SELECT id, medical_cert FROM drivers WHERE depot_code = ?")
        return {"depot_code": depot_code}

    def submit_for_compliance_check(self, depot_code: str) -> None:
        """HTTP_CALL: AuditService --> ComplianceAPI."""
        payload = self.load_certification_records(depot_code)
        _http_post("http://compliance-api/v1/verify-audit", payload)


def _http_post(url: str, payload: dict[str, object]) -> None:
    """Fixture stub representing an outbound HTTP POST."""
    _ = (url, payload)
