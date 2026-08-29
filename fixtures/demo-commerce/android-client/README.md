# AndroidClient (ProfileClient) — Demo Commerce Fixture

**Type:** Android mobile client (Kotlin)
**Dependency role:** Consumes ProfileAPI; terminal node in the 3-hop dependency chain.

## Encoded dependencies

| Edge | Source | Target | Kind |
|---|---|---|---|
| Inbound | `ProfileAPI` | `ProfileClient` | `API_CONSUMES` |

## Key code reference

`src/profile_client.kt` → `ProfileClient.displayProfile()` — calls
`GET /profile/{userId}` and renders `phoneNumber` in the UI.

The `phoneNumber` field reference makes `ProfileClient` the terminal consumer of
`users.phone_number`. Any breaking change to that column is a blast-radius hit here.

## Day 2 note

The Retrofit-style interface and explicit `phoneNumber` field access are designed
for future Kotlin Tree-sitter pattern recognition.
