# PreFlight — Architecture

## Purpose

PreFlight is a deployment-survivability analysis system.
Its goal: determine what a software change can break, how far the impact propagates,
and whether a deployment is safe to proceed.

Day 1 establishes the deterministic dependency-graph foundation. Day 2 adds
Tree-sitter parsing, and Day 3 derives narrow semantic dependencies from active
syntax on top of that foundation.

---

## Day 1 Scope

Day 1 delivers:
- Canonical domain schemas (Pydantic v2)
- A typed dependency graph (NetworkX DiGraph)
- A deterministic graph builder
- A deterministic traversal module
- A deterministic canonical serialization module
- A demo fixture representing a realistic 4-component system
- A complete test suite (unit + integration)
- A smoke script that demonstrates the end-to-end foundation

Day 1 does **not** deliver: static parsing, risk scoring, AI explanation,
database migration analysis, rollback analysis, frontend, or deployment.

---

## Module Boundaries

```
preflight/
├── domain/          Pure data contracts. No infrastructure dependencies.
│   ├── enums.py     EntityKind, EdgeKind
│   ├── entities.py  Entity (Pydantic model)
│   ├── graph_models.py  DependencyEdge, DependencyPath
│   ├── reports.py   AnalysisReport, ReportMetadata
│   └── errors.py    Domain exceptions
│
├── graph/           Graph construction, traversal, serialization.
│   │                Depends on domain/. Wraps NetworkX.
│   ├── builder.py   GraphBuilder, PreFlightGraph
│   ├── traversal.py find_downstream_paths, find_canonical_path
│   └── serialization.py  canonical_graph, canonical_json, canonical_sha256
│
└── fixtures/        Fixture definitions (Day 1: explicit; Day 2+: parsed).
    └── loader.py    build_demo_commerce_graph()

├── semantic.py      Day 3 AST-backed route, HTTP, SQL, and config analysis
└── blast_radius.py  Day 4 bounded traversal and impact reporting
```

### Dependency direction

```
domain  ←  graph  ←  fixtures / future parsers
             ↑
           scripts / tests
```

The semantic analyzer follows five phases: parse all files, register all API
providers, register consumers, resolve consumers against the complete registry,
then construct and canonicalize semantic edges. Comments, docstrings, and
unrelated strings are not semantic inputs. The Day 3 closure adds two important
semantic guarantees: HTTP route matching is method-sensitive, and the analyzer can
accept a deterministic ordered file list so equivalent source sets yield the same
canonical graph under normal, reversed, and shuffled discovery order.

The domain layer has **no dependencies on graph, fixtures, CLI, or infrastructure**.
This keeps it portable and independently testable.

Day 7 adds `rollback_truth.py`, which consumes the normalized Day 5 schema,
Day 6 API, and existing graph outputs. Its core receives structured
`ApplicationSnapshot` objects, leaving Git extraction as a future adapter.
Rollback direction is explicit: OLD application against NEW database/API;
forward compatibility is reported separately.

---

## Domain Model

### Entity

Represents any tracked artifact: a database column, a service, an API, a client.

- `entity_id` — stable, deterministic string key (never random)
- `kind` — `EntityKind` enum
- `service` — owning logical service
- `file`, `line` — source location (populated by future parsers)
- `metadata` — open extension dict; excluded from canonical output

### DependencyEdge

A directed, typed dependency between two entities.

- `source`, `target` — `entity_id` references
- `kind` — `EdgeKind` enum
- `weight` — reserved for future risk-weighted traversal

### DependencyPath

An ordered sequence of nodes and edges representing a traversal result.

- Invariant: `len(edges) == len(nodes) - 1`
- `hop_count`, `origin`, `terminal` convenience properties

### AnalysisReport

Top-level output contract. Schema-versioned for forward compatibility.

- Day 1 fields: `target`, `entities`, `edges`, `paths`, `metadata`
- Future fields (Day 9+): `risk_score`, `verdict`, `explanation` — added as optional

---

## Graph Model

Uses `networkx.DiGraph`. A `MultiDiGraph` is not used; if multiple edge kinds
between the same nodes are needed, they are represented as separate
`DependencyEdge` entries with distinct `kind` values.

`GraphBuilder` is the only sanctioned way to construct a `PreFlightGraph`.
Raw NetworkX construction is not exposed outside the `graph/` layer.

---

## Deterministic Serialization

See `docs/DETERMINISM.md` for the full specification.

`canonical_json()` produces a stable byte sequence by:
1. Sorting nodes by `entity_id`
2. Sorting edges by `(source, target, kind.value)`
3. Using `json.dumps(sort_keys=True, separators=(',', ':'))`
4. Excluding all non-deterministic fields (metadata, timestamps)

`canonical_sha256()` computes SHA-256 over the UTF-8 bytes of `canonical_json()`.

---

## Extension Points for Future Days

Day 8 adds `src/preflight/decision.py` above the existing analyzers. It
normalizes their findings, extracts deterministic risk features, applies the
published formula, detects compound failures, and evaluates explicit policy
rules. Parser logic remains in Days 3-7. Day 9 adds `src/preflight/explanation.py`
downstream of the verdict: a sanitizer creates structured AI input, providers
return a strictly validated advisory response, and a deterministic fallback
remains available. AI cannot change the decision, score, evidence, policy, or
deterministic hash.

| Day | Module | Hook point |
|-----|--------|------------|
| 2 | `graph/parsers/treesitter.py` (new) | Replaces/augments `fixtures/loader.py` as entity source |
| 3 | `graph/builder.py` | `GraphBuilder.add_entity()` already accepts any `Entity` |
| 6 | `graph/parsers/sqlglot.py` (new) | Adds `DB_READ`/`DB_WRITE` edges from SQL migration files |
| 7 | `graph/parsers/openapi.py` (new) | Adds `API_CONSUMES` edges from OpenAPI specs |
| 9 | `explanation.py` | Sanitized explanation input, advisory providers, grounded remediation, fallback |
| 11 | `graph/serialization.py` | `canonical_sha256()` becomes the production DVH primitive |

---

## Day 10: Orchestration boundary

`scripts/preflight_api.py` no longer contains any analysis logic. It is a
thin HTTP adapter: parse the request, call
`preflight.orchestration.run_analysis()`, serialize the result. The API
does not construct findings, does not build a graph itself, and does not
compute risk.

```
preflight/orchestration/
├── __init__.py    Public surface: run_analysis, SCENARIOS, error types
├── models.py       AnalysisInput, ScenarioConfig, AnalysisRunResult
├── pipeline.py      run_analysis() — composes every existing analyzer
└── errors.py       OrchestrationError, UnknownScenarioError, FixtureUnavailableError
```

`run_analysis()` calls, in order: `SemanticAnalyzer.analyze()` (the graph),
`DeploymentAnalyzer.analyze()` (the migration finding), `BlastRadiusEngine.analyze()`
(bounded downstream impact from the changed schema object),
`analyze_api_contract()` (contract diff), `analyze_rollback()` (OLD app vs.
NEW schema/API), `decide()` (the single risk/policy authority), and
`explain()` (advisory only). It does not reimplement any of their internal
logic — see `docs/DAY_10.md` for the full data flow, the two registered
scenarios, and how failures degrade to `UNKNOWN` instead of a fabricated
verdict.

A `ScenarioConfig` selects which real fixture files a request reads
(migration SQL, schema SQL, OpenAPI contract) — never which output it
should produce. `fixtures/demo-commerce/database/migration.sql` and
`migration_safe.sql` are the two scenario inputs currently registered.

---

## Repository ingestion: `preflight.ingestion`

`POST /api/analyze-project` lets a real, uploaded project ZIP enter the
same pipeline the fixture scenarios use. The ingestion boundary is a
separate package with no analysis logic of its own:

```
preflight/ingestion/
├── errors.py       IngestionError and its four subtypes
├── limits.py       archive/file/count/ratio limits (constants, not config)
├── archive.py      extracted_project() — the only sanctioned unzip path
├── discovery.py     locates schema/migration/API-contract/source files
├── manifest.py      build_manifest() — deterministic file inventory
├── multipart.py      minimal multipart/form-data parser (no cgi dependency)
└── models.py         ManifestEntry, ProjectManifest
```

`orchestration/pipeline.py` gained a second entry point,
`run_project_analysis(project_root, ...)`, alongside the existing
`run_analysis()`. Both now resolve their real input files differently and
then call the same private `_execute_pipeline()` — there is exactly one
analysis pipeline. `run_analysis()` looks up a `ScenarioConfig`'s fixed
paths; `run_project_analysis()` calls `preflight.ingestion.discovery` to
find the equivalent files inside an arbitrary extracted project tree.
Neither path duplicates `SemanticAnalyzer`, `DeploymentAnalyzer`,
`BlastRadiusEngine`, `analyze_api_contract`, `analyze_rollback`, `decide`,
or `explain` — see `docs/DAY_11.md` for the full data flow, the security
model, and the three-ZIP causality proof (destructive → safe →
remediated).
