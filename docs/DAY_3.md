# PreFlight Day 3: Semantic Dependencies

Day 3 derives explainable dependency edges from active Python and Kotlin syntax.
The semantic pass uses Tree-sitter nodes and never treats comments, docstrings, or
unrelated string contents as executable evidence.

## Edge taxonomy

- `DB_READ`: an active `execute`, `executemany`, `query`, or `raw` call with a static SQL literal containing `SELECT`.
- `DB_WRITE`: the same supported SQL calls for `INSERT`, `UPDATE`, or `DELETE`.
- `HTTP_CALL`: a supported Python HTTP/helper call with a static URL literal.
- `API_CONSUMES`: an API provider route matched to an active Kotlin consumer annotation.
- `CONFIG_DEPENDENCY`: supported `os.getenv` access or Kotlin `BuildConfig.NAME` access.

## Resolution phases

1. Discover and parse all source files.
2. Register all provider routes.
3. Discover/register consumer route declarations.
4. Resolve consumers against the complete route registry.
5. Construct and canonicalize entities, edges, and evidence.

Route matching normalizes schemes, leading/trailing slashes, and `{parameter}`
placeholders. HTTP methods and hosts must match. Multiple providers remain
ambiguous and are not selected arbitrarily.

## Evidence and security

Every emitted edge carries structured `EdgeEvidence` with project-relative file,
line, column, syntax kind, matched pattern, extracted value, and resolution rule.
Only short normalized values are retained; source files and secret values are not
stored. Dynamic URLs and SQL are unresolved and do not produce a guessed target.

## Closed Day 3 acceptance items

The Day 3 closure adds four explicit semantic guarantees:

- HTTP matching is method-sensitive: `GET /users` matches only `GET /users` and
  does not match `POST/PUT/PATCH/DELETE` on the same route.
- SQL normalization maps `SELECT` to `DB_READ` and `INSERT`/`UPDATE`/`DELETE` to
  `DB_WRITE`, while preserving table and column names when statically available.
- Ambiguous providers remain explicit and deterministic: when multiple providers
  match the same route, the analyzer records the candidate set instead of silently
  selecting one.
- Source discovery accepts an ordered file list, allowing the same semantic input
  to be analyzed in different file orders without changing the graph or canonical JSON.

## Determinism

Files, entities, edges, registry entries, and evidence are sorted by stable keys.
Edge identity is `(source, target, kind)`, so repeated call sites merge into one
edge with canonically ordered evidence. Canonical graph serialization and SHA-256
remain the determinism boundary.

## Supported syntax boundary

Python routes use active `@app.get/post/put/patch/delete` decorators. Python HTTP
uses `requests.<method>`, `httpx.<method>`, and `_http_<method>` calls with literal
URLs. Kotlin routes use active `@GET/POST/PUT/PATCH/DELETE` annotations. Database
access requires a recognized SQL-bearing call and a static SQL literal. These are
narrow static-analysis rules, not a full framework or SQL implementation.
