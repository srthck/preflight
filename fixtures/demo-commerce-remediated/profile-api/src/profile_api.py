"""ProfileAPI — Demo Commerce analysis fixture (remediated release).

phone_number has been removed from the response contract. AndroidClient
(see the remediated profile_client.kt) no longer displays it either.
"""

from __future__ import annotations

from dataclasses import dataclass


class _RouteApp:
    def get(self, route: str) -> object:
        return lambda function: function


app = _RouteApp()


@dataclass(frozen=True)
class ProfileResponse:
    """Represents the JSON response body of GET /profile/{user_id}.

    phone_number was removed from this response as part of the same
    remediation that removed it from UserService's query.
    """

    user_id: int
    name: str
    email: str


class ProfileAPI:
    """Exposes user profile data to external consumers (e.g. AndroidClient).

    Route: GET /profile/{user_id}
    """

    def __init__(self, user_service_url: str) -> None:
        self._user_service_url = user_service_url

    @app.get("/profile/{user_id}")
    def get_profile(self, user_id: int) -> ProfileResponse:
        """Handle GET /profile/{user_id}. No longer returns phone_number."""
        raw = self._fetch_from_user_service(user_id)
        return ProfileResponse(
            user_id=raw["user_id"],
            name=raw["name"],
            email=raw["email"],
        )

    def _fetch_from_user_service(self, user_id: int) -> dict[str, object]:
        """Fetch user data from UserService via HTTP GET.

        HTTP_CALL: GET {user_service_url}/users/{user_id}
        """
        url = f"{self._user_service_url}/users/{user_id}"
        return _http_get(url)


def _http_get(url: str) -> dict[str, object]:
    """Fixture stub representing an outbound HTTP GET call."""
    _ = url
    return {
        "user_id": 1,
        "name": "Jane Doe",
        "email": "jane@example.com",
    }
