"""UserService — Demo Commerce analysis fixture (remediated release).

Unlike the canonical fixture, this version no longer selects or forwards
phone_number. This removes the DB_READ dependency on users.phone_number
entirely, which is the point of this fixture: proving that PreFlight's
blast-radius and rollback-truth results change when the real dependency
disappears, not just when a scenario label changes.
"""

from __future__ import annotations


class UserRow:
    """Represents a row returned from the users table."""

    def __init__(self, user_id: int, name: str, email: str) -> None:
        self.user_id = user_id
        self.name = name
        self.email = email


class UserService:
    """Retrieves user data from the database and exposes it to the profile layer.

    DB dependency: reads id, name, email from the users table.
    phone_number is intentionally no longer selected.
    """

    def __init__(self, db_connection: object) -> None:
        self._db = db_connection

    def get_user_profile_data(self, user_id: int) -> dict[str, object]:
        """Fetch user profile data. No longer includes phone_number.

        SQL executed (conceptual):
            SELECT id, name, email
            FROM users
            WHERE id = ?
        """
        self._db.execute("SELECT id, name, email FROM users WHERE id = ?")
        row = self._fetch_user_row(user_id)
        return {
            "user_id": row.user_id,
            "name": row.name,
            "email": row.email,
        }

    def _fetch_user_row(self, user_id: int) -> UserRow:
        """Execute: SELECT id, name, email FROM users WHERE id = ?"""
        return UserRow(user_id=user_id, name="Jane Doe", email="jane@example.com")

    def forward_to_profile_api(self, user_id: int) -> None:
        """Send user profile data (no longer including phone_number) to ProfileAPI.

        HTTP_CALL dependency: UserService --> ProfileAPI
        Endpoint: POST /internal/profile/sync
        """
        payload = self.get_user_profile_data(user_id)
        _http_post("http://profile-api/internal/profile/sync", payload)


def _http_post(url: str, payload: dict[str, object]) -> None:
    """Fixture stub representing an outbound HTTP POST call."""
    _ = url
    pass  # noqa: PIE790 (intentional fixture stub)
