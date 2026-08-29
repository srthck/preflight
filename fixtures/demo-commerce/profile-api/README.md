# ProfileAPI — Demo Commerce Fixture

**Type:** REST API (Python)
**Dependency role:** Receives user data from UserService; exposes profile to AndroidClient.

## Encoded dependencies

| Edge | Source | Target | Kind |
|---|---|---|---|
| Inbound | `UserService` | `ProfileAPI` | `HTTP_CALL` |
| Outbound | `ProfileAPI` | `AndroidClient` | `API_CONSUMES` |

## Key code reference

`src/profile_api.py` → `ProfileAPI.get_profile()` — handles `GET /profile/{user_id}`
and returns `ProfileResponse` including `phone_number`.

## Day 2 note

The route annotation `GET /profile/{user_id}` and the `ProfileResponse.phone_number`
field are designed for static analysis recognition. Day 2+ will auto-derive edges.
