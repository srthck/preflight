# PreFlight — Current Limitations

This document explicitly states what Day 1 is **not**.

Limitations are listed here so judges, reviewers, and future contributors
understand exactly what has and has not been implemented.

---

## What Day 1 Is

Day 1 is a **deterministic dependency graph foundation**.

It provides:
- Typed domain models
- A validated graph builder
- A deterministic traversal algorithm
- Deterministic canonical serialization with SHA-256 verification
- A controlled four-component demo fixture
- A complete test suite

---

## What Day 1 Is NOT

### No static source-code analysis

The Day 1 graph is **manually defined** in `src/preflight/fixtures/loader.py`.
Entities and edges are explicit Python data, not derived from parsing source files.

Tree-sitter-based extraction begins on Day 2. Day 3 adds narrow semantic
extraction, but it does not support every framework or language construct.

### Day 3 semantic boundary

Only supported active decorators/annotations, recognized HTTP calls, SQL-bearing
calls with static literals, and supported configuration access are analyzed.
Comments and docstrings never create edges. Dynamic URLs, dynamic SQL,
reflection, and ambiguous route matches remain unresolved rather than being
guessed. SQL parsing is intentionally lightweight; full migration diffing is
planned for Day 5/6 work. The HTTP and DB matrices are now explicitly exercised
and method-sensitive/operation-sensitive, but they remain narrow static-analysis
rules rather than a general SQL or framework interpreter. The canonical SHA-256
is deterministic for the graph, but performance and scalability are not claims
about arbitrary repositories.

### Day 4 blast-radius boundary

Blast-radius scores are deterministic engineering heuristics, not probabilities
of production failure and not the final deployment risk score. Simple-path
enumeration is bounded by caller-provided hop and path limits; graph-size
benchmarks are not yet established. The CLI is a developer tool and does not
provide authentication, persistence, or deployment integration.

### No production repository ingestion

PreFlight cannot yet analyse an arbitrary software repository.
It can only analyse the controlled `demo-commerce` fixture.

### Day 9 explanation boundary

Risk scoring and the deployment verdict are deterministic Day 8 outputs.
Day 9 adds structured advisory explanation, remediation provenance, secret
redaction, strict response validation, and a deterministic fallback. The AI
layer cannot authorize deployment, change the verdict or score, execute SQL,
modify files, or prove runtime safety. The optional provider is an adapter only;
no vendor, cloud latency, or on-device inference is claimed.

### No NPU inference

No on-device neural processing.
NPU inference is not planned for Day 1 through Day 9.

### No database migration analysis

SQLGlot-based database migration analysis (detecting schema-breaking changes)
begins on **Day 6**.

### No OpenAPI / environment analysis

OpenAPI contract analysis and environment variable dependency tracking
begin on **Day 7**.

### Rollback Truth boundary

Day 7 deterministically identifies rollback incompatibilities within the
supported static evidence model. It does not guarantee safe rollback. Dynamic
SQL, reflection, generated code, incomplete application dependencies, external
runtime state, and arbitrary runtime behavior can create blind spots. Type and
constraint changes are reported as caution where static evidence cannot prove
failure. Git snapshot extraction is an adapter boundary, not part of the core.

### Day 8 decision boundary

The risk score is a deterministic engineering prioritization score, not a
probability or production guarantee. Policy decisions are only as complete as
the normalized analyzer evidence supplied. Empty or unavailable analysis is
`UNKNOWN`; unsupported runtime behavior cannot be inferred. Compound multipliers
are explicit prototype policy adjustments, not calibrated incident likelihoods.

### No frontend

There is no web or mobile frontend.
The Next.js frontend and phone-first UI begin on **Day 10**.

### No Office Kit integration

Office Kit integration (document generation) is planned for **Day 10**.

### No authentication

Day 1 has no authentication or access control.

### No database server

Day 1 uses no persistent database server.
All state is in-memory and reconstructed on each run.

### No Kubernetes or containerization

No container orchestration.
Day 1 runs entirely as a local Python process.

### No network access required

Day 1 analysis is **fully offline**. No HTTP calls are made by the analysis core.

---

## SHA-256 Note

The `canonical_sha256()` function established in Day 1 is the **foundation**
for the Determinism Verification Hash (DVH) system. It is not yet the
production DVH — that infrastructure (including the 25-fixture benchmark)
is planned for **Day 11**.

---

### Day 11 repository ingestion boundary

`POST /api/analyze-project` accepts Python/Kotlin/SQL/OpenAPI projects
only; other languages are labeled `unsupported` in the manifest, never
silently skipped. Discovery picks one schema file and one migration file
per upload using deterministic, explainable rules (`schema.sql` by name; a
migrations-directory's lexicographically-last file, or the sole/last `.sql`
candidate otherwise) — a project with multiple ambiguous migration
candidates and no dedicated migrations directory gets a best-effort
deterministic pick plus a visible note, not a guaranteed-correct one.
Nested archives are never extracted recursively; they are listed in the
manifest as ignored. Archive limits (25MB compressed, 150MB uncompressed,
5000 files, 20MB per file, 200x compression ratio) are fixed constants
sized for a single-tenant demo path, not a configurable production
ingestion service. Uploaded projects are extracted to an isolated temp
directory and deleted unconditionally after the request completes; nothing
is persisted. See `docs/DAY_11.md` for the full threat model.

### Day 10 orchestration boundary

`/api/analyze` runs the real pipeline (semantic parsing, blast radius,
deployment rehearsal, API contract diff, rollback truth, decision,
explanation) for exactly two registered scenarios, both reading
`fixtures/demo-commerce/`. Field-level API dependency derivation is not
implemented — the auto-derived `ApplicationSnapshot` fed into rollback
analysis records route-level dependencies (`"GET /profile/{id}"`) but not
which JSON field a consumer reads, so `RB-API-FIELD-REMOVED` is real and
unit-tested but not exercised end-to-end by either demo scenario. No
`new_application` snapshot is ever populated, so `forward_compatibility`
is `UNKNOWN` rather than a guess. See `docs/DAY_10.md` for the complete
list. PreFlight still cannot ingest an arbitrary repository.

---

## Summary

Day 1 is a small, deterministic, typed, tested, offline foundation.
It is not a complete analysis system. Subsequent days build on this
foundation incrementally without requiring architectural rewrites.
