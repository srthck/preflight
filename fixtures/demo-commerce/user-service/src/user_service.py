"""UserService — Demo Commerce analysis fixture.

This module is a static-analysis fixture representing the UserService
microservice. It is NOT executable production code; it models the
architectural relationships that PreFlight analyses.

Dependency this fixture encodes
--------------------------------
    users.phone_number  --DB_READ-->  UserService

UserService reads the ``phone_number`` column from the ``users`` table.
It then forwards enriched user data — including phone_number — upstream
to ProfileAPI via an internal HTTP call.

The explicit column reference on the SELECT query (see below) is
intentional: Day 2 Tree-sitter parsing will recognise this pattern and
automatically derive the DB_READ edge without manual fixture definition.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Simulated database row type
# ---------------------------------------------------------------------------


class UserRow:
    """Represents a row returned from the users table."""

    def __init__(
        self,
        user_id: int,
        name: str,
        email: str,
        phone_number: str | None,
    ) -> None:
        self.user_id = user_id
        self.name = name
        self.email = email
        # phone_number is the dependency-bearing field.
        # A change to users.phone_number propagates through this service.
        self.phone_number = phone_number


# ---------------------------------------------------------------------------
# UserService
# ---------------------------------------------------------------------------


class UserService:
    """Retrieves user data from the database and exposes it to the profile layer.

    DB dependency: reads `phone_number` from the `users` table.
    Upstream call: forwards enriched data to ProfileAPI via HTTP.
    """

    def __init__(self, db_connection: object) -> None:
        # db_connection is a placeholder; real connection logic belongs
        # in the production service, not in this analysis fixture.
        self._db = db_connection

    def get_user_profile_data(self, user_id: int) -> dict[str, object]:
        """Fetch user profile data including phone_number.

        SQL executed (conceptual):
            SELECT id, name, email, phone_number
            FROM users
            WHERE id = ?

        The explicit selection of `phone_number` from `users` establishes
        the DB_READ dependency: users.phone_number --> UserService.
        """
        # Fixture placeholder — in production this executes the SQL above.
        self._db.execute("SELECT id, name, email, phone_number FROM users WHERE id = ?")
        row = self._fetch_user_row(user_id)

        # phone_number is explicitly included in the returned payload so that
        # the dependency is visible to both static analysis and human readers.
        return {
            "user_id": row.user_id,
            "name": row.name,
            "email": row.email,
            "phone_number": row.phone_number,  # users.phone_number  <-- DB_READ
        }

    def _fetch_user_row(self, user_id: int) -> UserRow:
        """Execute: SELECT id, name, email, phone_number FROM users WHERE id = ?"""
        # Fixture stub — returns a deterministic placeholder record.
        return UserRow(
            user_id=user_id,
            name="Jane Doe",
            email="jane@example.com",
            phone_number="+1-555-0100",
        )

    def forward_to_profile_api(self, user_id: int) -> None:
        """Send user profile data (including phone_number) to ProfileAPI.

        HTTP_CALL dependency: UserService --> ProfileAPI
        Endpoint: POST /internal/profile/sync
        """
        # Fixture placeholder for the HTTP_CALL edge.
        # Day 2 static analysis will recognise HTTP client call patterns.
        payload = self.get_user_profile_data(user_id)
        _http_post("http://profile-api/internal/profile/sync", payload)


# ---------------------------------------------------------------------------
# Module-level helper (fixture stub)
# ---------------------------------------------------------------------------


def _http_post(url: str, payload: dict[str, object]) -> None:
    """Fixture stub representing an outbound HTTP POST call.

    In production this would be an aiohttp / requests / httpx call.
    The function exists so Day 2 Tree-sitter can detect the HTTP_CALL pattern.
    """
    # Not executed in analysis — this is a static fixture.
    pass  # noqa: PIE790 (intentional fixture stub)
