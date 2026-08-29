"""ComplianceAPI — Fleet Ops static-analysis fixture.

The shared downstream both DispatchService and AuditService call. This is
the convergence point: two independent upstream schema changes both reach
this one entity.

Route: GET /compliance/{driver_id}
"""

from __future__ import annotations

from dataclasses import dataclass


class _RouteApp:
    def get(self, route: str) -> object:
        return lambda function: function


app = _RouteApp()


@dataclass(frozen=True)
class ComplianceRecord:
    """Response body of GET /compliance/{driver_id}."""

    driver_id: int
    depot_code: str
    licence_valid: bool
    medical_valid: bool


class ComplianceAPI:
    """Aggregates dispatch and audit compliance for one driver."""

    def __init__(self, registry_url: str) -> None:
        self._registry_url = registry_url

    @app.get("/compliance/{driver_id}")
    def get_compliance(self, driver_id: int) -> ComplianceRecord:
        """Handle GET /compliance/{driver_id}."""
        return ComplianceRecord(
            driver_id=driver_id,
            depot_code="DEP-1",
            licence_valid=True,
            medical_valid=True,
        )
