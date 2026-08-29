# UserService — Demo Commerce Fixture

**Type:** Backend service (Python)
**Dependency role:** Reads `users.phone_number` from the database; forwards data to ProfileAPI.

## Encoded dependencies

| Edge | Source | Target | Kind |
|---|---|---|---|
| Inbound | `users.phone_number` | `UserService` | `DB_READ` |
| Outbound | `UserService` | `ProfileAPI` | `HTTP_CALL` |

## Key code reference

`src/user_service.py` → `UserService.get_user_profile_data()` — contains the SQL SELECT
that reads `phone_number` from `users`.

## Day 2 note

The explicit column reference in the SELECT query is designed for Tree-sitter
recognition. The Day 2 parser will extract the `DB_READ` edge automatically.
