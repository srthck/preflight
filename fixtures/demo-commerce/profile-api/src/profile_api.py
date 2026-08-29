"""ProfileAPI — Demo Commerce analysis fixture.

This module is a static-analysis fixture representing the ProfileAPI service.
It is NOT executable production code; it models architectural relationships
for PreFlight analysis.

Dependency this fixture encodes
--------------------------------
    UserService  --HTTP_CALL-->   ProfileAPI
    ProfileAPI   --API_CONSUMES--> AndroidClient

ProfileAPI exposes GET /profile/{user_id}.
The response includes phone_number, which originates from users.phone_number
via UserService. This makes AndroidClient transitively dependent on
users.phone_number — the 3-hop chain PreFlight traces on Day 1.

Route definition (line 27): GET /profile/{user_id}
This explicit route declaration enables Day 2+ static analysis to
auto-detect the API_CONSUMES edge from any client that calls this path.
"""

from __future__ import annotations

from dataclasses import dataclass


class _RouteApp:
    def get(self, route: str) -> object:
        return lambda function: function


app = _RouteApp()

# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProfileResponse:
    """Represents the JSON response body of GET /profile/{user_id}.

    phone_number flows here from users.phone_number via UserService.
    A change to users.phone_number propagates to every field in this
    response that carries its value.
    """

    user_id: int
    name: str
    email: str
    phone_number: str | None  # Originates from users.phone_number


# ---------------------------------------------------------------------------
# ProfileAPI
# ---------------------------------------------------------------------------


class ProfileAPI:
    """Exposes user profile data to external consumers (e.g. AndroidClient).

    Route: GET /profile/{user_id}

    Data flow:
        users.phone_number
          --> UserService.get_user_profile_data()
          --> ProfileAPI.get_profile()           # this class
          --> AndroidClient.fetchProfile()        # API_CONSUMES edge
    """

    def __init__(self, user_service_url: str) -> None:
        # user_service_url is the upstream UserService endpoint.
        # HTTP_CALL dependency: ProfileAPI calls UserService internally
        # (in this fixture the call is inbound — UserService pushes data —
        # but ProfileAPI also pulls on-demand for real-time requests).
        self._user_service_url = user_service_url

    @app.get("/profile/{user_id}")
    def get_profile(self, user_id: int) -> ProfileResponse:
        """Handle GET /profile/{user_id}.

        Fetches user data from UserService and returns a ProfileResponse
        including phone_number.

        HTTP_CALL: calls UserService to retrieve user profile data.
        The returned ProfileResponse is consumed by AndroidClient (API_CONSUMES).
        """
        raw = self._fetch_from_user_service(user_id)

        # phone_number is explicitly forwarded in the response.
        # AndroidClient depends on this field being present and correctly typed.
        return ProfileResponse(
            user_id=raw["user_id"],
            name=raw["name"],
            email=raw["email"],
            phone_number=raw.get("phone_number"),  # from users.phone_number
        )

    def _fetch_from_user_service(self, user_id: int) -> dict[str, object]:
        """Fetch user data from UserService via HTTP GET.

        HTTP_CALL: GET {user_service_url}/users/{user_id}
        """
        # Fixture stub — Day 2 static analysis detects the HTTP call pattern.
        url = f"{self._user_service_url}/users/{user_id}"
        return _http_get(url)


# ---------------------------------------------------------------------------
# Module-level helper (fixture stub)
# ---------------------------------------------------------------------------


def _http_get(url: str) -> dict[str, object]:
    """Fixture stub representing an outbound HTTP GET call.

    In production this would use httpx / aiohttp / requests.
    Day 2 Tree-sitter analysis will detect this call pattern.
    """
    # Not executed in analysis — static fixture only.
    _ = url
    return {
        "user_id": 1,
        "name": "Jane Doe",
        "email": "jane@example.com",
        "phone_number": "+1-555-0100",
    }
