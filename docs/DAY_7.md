# Day 7: Rollback Truth Engine

Rollback truth is different from `git revert`. A revert can restore application files while the database and API remain in their post-deployment state. PreFlight tests the actual question: can the old application operate against the new database and API?

## Model

`ApplicationSnapshot` records version, commit, schema dependencies, API dependencies, provenance, and unresolved dynamic dependencies. Existing `SchemaModel` and `OpenAPIContract` are the normalized Day 5 and Day 6 snapshots. `RollbackRequest` combines them with the existing graph, migration findings, and explicit `RollbackWindow` metadata.

The report records both directions:

```text
forward:  NEW APPLICATION -> NEW DATABASE/API
rollback: OLD APPLICATION -> NEW DATABASE/API
```

When the old application depends on `users.phone_number` and the new schema removes it, the result is `UNSAFE`, even when the new application no longer uses that column. The old application is the direct incompatible dependency; graph descendants are impact context, not proof that every descendant independently fails.

## Rules and evidence

`RB-SCHEMA-REMOVED-OLD-DEPENDENCY` proves a removed schema dependency. API endpoint and field removals are checked against old application API dependencies. Type changes and new `NOT NULL` constraints are `CAUTION`, because static evidence does not prove arbitrary runtime failure. Missing snapshots and dynamic or reflective dependencies are `UNKNOWN`, never silently `SAFE`.

Destructive removal while the old application still depends on the object also produces `EXPAND_CONTRACT_VIOLATION`. This identifies a sequencing problem; it does not generate a migration patch.

Every finding carries explicit application, database, and API direction fields, structured evidence, source provenance when supplied, and direct/indirect classification. Secret-like keys and credential-bearing values are redacted at the report boundary.

## Determinism and CLI

Findings, dependencies, provenance, evidence, and JSON keys are sorted before canonical serialization. `rollback_truth_sha256()` hashes that canonical result without timestamps, machine paths, random IDs, or the existing hash field.

The source-checkout CLI accepts JSON snapshot files:

```text
python scripts/rollback_check.py --old-app old_app.json --new-app new_app.json --old-schema old_schema.json --new-schema new_schema.json --json
```

Git integration is an adapter boundary. Static analysis cannot prove arbitrary runtime behavior; dynamic SQL, reflection, generated code, external state, and incomplete dependency extraction remain blind spots.
