# Day 10: Real Orchestration

## What changed

`/api/analyze` used to call `killer_report()`: a function in
`scripts/preflight_api.py` that constructed two `NormalizedFinding` objects
by hand, called `build_demo_commerce_graph()` for the graph, and fed both
into `decide()` and `explain()`. Every other analyzer — `SemanticAnalyzer`,
`BlastRadiusEngine`, `DeploymentAnalyzer`, `analyze_api_contract`,
`analyze_rollback` — existed, was independently tested, and was never
called from the HTTP path. The request handler had already skipped the
analysis and gone straight to the answer.

`killer_report()` and `build_demo_commerce_graph()` are gone from the
production request path. `scripts/preflight_api.py` now does exactly one
thing: parse the HTTP request, call
`preflight.orchestration.run_analysis()`, and serialize whatever it
returns. It contains no `NormalizedFinding(...)` construction, no risk
arithmetic, and no scenario-to-verdict mapping.

## The orchestrator

`src/preflight/orchestration/` composes the existing analyzers without
duplicating any of their logic:

```
AnalysisInput (case_id, scenario)
  -> ScenarioConfig                     which real fixture files to read
  -> SemanticAnalyzer.analyze(root)     -> SemanticAnalysisResult, graph
  -> DeploymentAnalyzer(graph).analyze(migration_sql)
                                         -> DeploymentFinding (schema_object,
                                            change, deployment_status)
  -> BlastRadiusEngine.analyze(graph, BlastRadiusRequest(target=schema_object))
                                         -> BlastRadiusReport
  -> analyze_api_contract(contract, contract)
                                         -> APIContractFinding
  -> parse_schema_sql / apply_schema_migration
                                         -> old/new SchemaModel snapshots
  -> _derive_application_snapshot(semantic)
                                         -> ApplicationSnapshot (evidence-derived)
  -> analyze_rollback(RollbackRequest(...))
                                         -> RollbackReport
  -> decide(DecisionRequest(...))       -> DecisionReport (risk, verdict, hash)
  -> explain(decision_report)           -> ExplanationResult (never raises)
  -> AnalysisRunResult.to_response_payload()
```

A **scenario name selects fixture inputs, never an output.** The registry
in `pipeline.py` (`SCENARIOS`) maps a scenario string to file paths —
`migration.sql`, `schema.sql`, `openapi.yaml` — under
`fixtures/demo-commerce/`. Nothing branches on the scenario string after
that; every value in the response is computed from what those files
contain.

### `_derive_application_snapshot`

The OLD application's `ApplicationSnapshot` (used by rollback analysis) is
not a hand-written fixture. It is built from the real `SemanticAnalyzer`
output: any database entity with an incoming `DB_READ` edge becomes a
schema dependency; any API route reached through an `API_CONSUMES` edge
becomes an API dependency. Each dependency carries the edge's own
`source_file`/`line` evidence as provenance. This is why the rollback
finding's provenance points at `user_service.py`, not at a JSON fixture —
because that is where the dependency evidence actually came from.

### `parse_schema_sql` / `apply_schema_migration`

Added to `schema.py` (not to the orchestrator) alongside the existing
`parse_migration_sql`, since it is the same kind of SQLGlot-backed
structural parsing `DeploymentAnalyzer` already does. `parse_schema_sql`
turns a `CREATE TABLE` fixture into a `SchemaModel`; `apply_schema_migration`
applies a parsed migration's changes to produce the *new* schema snapshot.
The orchestrator calls both; it does not parse SQL itself.

## Two real scenarios, one pipeline

| Scenario | Migration fixture | Deployment | Rollback | Decision |
|---|---|---|---|---|
| `demo-commerce-phone-number-removal` | `ALTER TABLE users DROP COLUMN phone_number;` | `DROP_COLUMN` / `UNSAFE` | `UNSAFE` (`RB-SCHEMA-REMOVED-OLD-DEPENDENCY`) | `DO_NOT_DEPLOY`, risk 100 |
| `demo-commerce-phone-verified-addition` | `ALTER TABLE users ADD COLUMN phone_verified BOOLEAN DEFAULT FALSE;` | `ADD_COLUMN` / `SAFE` | `SAFE` (no findings) | `SAFE`, risk 9 |

Both numbers come from the real formula in `decision.py`
(40% blast + 35% deployment + 25% rollback); nothing here overrides it.
`tests/integration/test_orchestration_pipeline.py::test_removing_the_migration_changes_the_result_and_restoring_it_reverts`
mutates the canonical scenario's migration file in place, re-runs the
pipeline, and asserts the decision, risk score, and deterministic hash all
change — then restores the file and asserts the original hash returns
exactly.

## API contract question, answered honestly

Neither scenario changes the OpenAPI contract — a database migration alone
does not touch `profile-api/openapi.yaml`. `analyze_api_contract` compares
the file against itself and correctly reports `SAFE` with zero changes.
PreFlight does not synthesize a breaking API change to make the demo look
more dangerous; `analyze_api_contract`'s existing breaking-change detection
is unit-tested independently in `tests/unit/test_day6.py` and is exercised
unchanged here — it just has nothing to report for this input.

## Failure modes

`run_analysis` raises exactly two typed exceptions —
`UnknownScenarioError` and `FixtureUnavailableError` — for requests that
cannot be analyzed at all. The HTTP layer maps these to `400`/`404` with a
structured `{"error": ..., "detail": ...}` body. Every other gap in the
evidence (missing migration file, malformed SQL, missing API contract,
missing schema snapshot, an empty/invalid fixture tree) is threaded through
as an `unavailable_components` entry or handled by the analyzer's own
existing graceful path — `DeploymentAnalyzer` already returns a structured
`PARSE_ERROR` finding for malformed SQL instead of raising — so `decide()`
resolves the request to `UNKNOWN` rather than a fabricated `SAFE` or
`DO_NOT_DEPLOY`. See `tests/integration/test_orchestration_pipeline.py`,
Phase 16 tests, for one case per failure mode.

An unexpected exception from inside an analyzer is caught at the HTTP
boundary and returned as `500 {"error": "ANALYSIS_UNAVAILABLE", ...}` — a
structured body, never a raw traceback.

## AI boundary

No AI provider is wired into this repository. `explain()` is always called
with no `provider` argument, so it always uses
`DeterministicExplanationProvider` and reports
`quality = DETERMINISTIC_FALLBACK`. The response payload's `ai_available`
field is `false` for every request. `explain()`'s own internal try/except
(unchanged, from Day 9) guarantees that even a failing provider cannot fail
the analysis — that guarantee is exercised as-is, not re-implemented, by
`test_ai_unavailable_never_fails_analysis`.

## Determinism

`test_ten_runs_produce_identical_hash` runs the canonical scenario ten
times and asserts one distinct `deterministic_hash`.
`test_reversed_and_shuffled_file_discovery_order_is_identical` runs
`SemanticAnalyzer` with the fixture's files in forward, reversed, and
shuffled order and asserts the same graph hash — this was already a Day 3
guarantee; the test confirms the orchestrator does not depend on any file
ordering assumption of its own.
`test_repeated_http_style_requests_share_deterministic_hash` calls the HTTP
handler's `analyze()` function twice and compares
`decision_report.deterministic_hash`. The AI explanation is never part of
that hash — it is attached to the response payload but excluded from
`DecisionReport`, unchanged from Day 9.

## Known limitations

- **Field-level API dependencies are not derived.** `_derive_application_snapshot`
  builds route-level API dependencies (`"GET /profile/{id}"`) from
  `API_CONSUMES` edges, but the semantic layer does not track which
  specific JSON response field a consumer reads, so no `#phone_number`
  suffix is attached. `RB-API-FIELD-REMOVED` is still real and tested
  (`tests/unit/test_rollback_truth.py`), just not exercised end-to-end by
  the two demo scenarios — proving it end-to-end would require field-level
  static analysis, out of scope for this change.
- **`DeploymentAnalyzer`'s `schema` parameter remains unused inside `analyze()`.**
  This is pre-existing Day 5 behavior, not something introduced here; the
  orchestrator does not pass a schema into it because the analyzer would
  ignore it.
- **`new_application` is never populated.** Rollback truth is evaluated as
  OLD application against NEW schema/API, which is the scenario this repo
  models (a migration ships without a corresponding new-app fixture).
  `forward_compatibility` is consequently reported as `UNKNOWN` (missing
  evidence), never fabricated as `SAFE`.
- **Two scenarios, one fixture family.** Both registered scenarios read
  `fixtures/demo-commerce/`; PreFlight still cannot ingest an arbitrary
  repository (unchanged from prior-day limitations).
