# PreFlight — Data Model

## Schema Version

All `AnalysisReport` objects carry a `schema_version` field.
Current version: `"1.0"`

Version semantics:
- **MINOR** increment: backward-compatible addition (e.g. new optional field)
- **MAJOR** increment: breaking structural change

The `SCHEMA_VERSION` constant in `preflight/domain/reports.py` is the single source of truth.

---

## EntityKind

```
EntityKind
├── DATABASE   — a database table, view, or column
├── SERVICE    — a backend microservice
├── API        — an API surface (REST / gRPC / GraphQL)
├── CLIENT     — a consumer of an API (mobile, web, CLI)
├── SYMBOL     — a code-level symbol (function, class, method)
├── ENDPOINT   — a specific URL route or RPC method
└── CONFIG     — a configuration artifact
```

---

## EdgeKind

```
EdgeKind
├── DB_READ            — service reads from a database entity
├── DB_WRITE           — service writes to a database entity
├── HTTP_CALL          — service makes an outbound HTTP call
├── API_CONSUMES       — client consumes an API
├── IMPORT             — module imports another module
└── CONFIG_DEPENDENCY  — entity depends on a config artifact
```

### Edge semantics

| Kind | Direction | Day 1 example |
|------|-----------|---------------|
| `DB_READ` | db_entity → service | `users.phone_number` → `UserService` |
| `HTTP_CALL` | caller → callee | `UserService` → `ProfileAPI` |
| `API_CONSUMES` | api → client | `ProfileAPI` → `ProfileClient` |

---

## Entity

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `entity_id` | `str` | ✓ | Stable, deterministic. No whitespace. |
| `name` | `str` | ✓ | Human-readable. |
| `kind` | `EntityKind` | ✓ | Semantic classification. |
| `service` | `str` | ✓ | Owning service or database name. |
| `file` | `str \| None` | — | Relative path to source file. |
| `line` | `int \| None` | — | Line number in `file` (≥ 1). |
| `metadata` | `dict` | — | Extension data. Excluded from canonical output. |

### entity_id formation rules

```
Database columns:   "<table>.<column>"          → "users.phone_number"
Services/symbols:   "<service-name>.<ClassName>" → "user-service.UserService"
APIs:               "<service-name>.<ClassName>" → "profile-api.ProfileAPI"
Clients:            "<service-name>.<ClassName>" → "android-client.ProfileClient"
```

IDs must be stable across repeated analysis of the same input. They must not
contain whitespace, random components, or timestamps.

---

## DependencyEdge

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `source` | `str` | ✓ | `entity_id` of dependency source. |
| `target` | `str` | ✓ | `entity_id` of dependency target. |
| `kind` | `EdgeKind` | ✓ | Semantic type of dependency. |
| `weight` | `float` | — | Default 1.0. Reserved for Day 9+ risk weighting. |
| `metadata` | `dict` | — | Extension data. Excluded from canonical output. |

Constraint: `source != target` (self-loops are rejected at construction time).

---

## DependencyPath

| Field | Type | Notes |
|-------|------|-------|
| `nodes` | `tuple[str, ...]` | Ordered `entity_id` list from origin to terminal. |
| `edges` | `tuple[EdgeKind, ...]` | One per hop. `len(edges) == len(nodes) - 1`. |
| `hop_count` | `int` (computed) | `len(edges)` |
| `origin` | `str` (computed) | `nodes[0]` |
| `terminal` | `str` (computed) | `nodes[-1]` |

---

## AnalysisReport

| Field | Type | Notes |
|-------|------|-------|
| `schema_version` | `str` | Default `"1.0"`. |
| `target` | `str` | `entity_id` of the entity under analysis. |
| `entities` | `tuple[Entity, ...]` | All entities in scope. |
| `edges` | `tuple[DependencyEdge, ...]` | All edges in scope. |
| `paths` | `tuple[DependencyPath, ...]` | Downstream paths from `target`. |
| `metadata` | `ReportMetadata` | Non-analytical report metadata. |

### ReportMetadata

| Field | Type | Notes |
|-------|------|-------|
| `source_fixture` | `str` | Fixture or repository identifier. |
| `analysis_version` | `str` | Engine version. Default `"0.1.0"`. |
| `notes` | `list[str]` | Human-readable caveats. Default `[]`. |
| `extra` | `dict` | Reserved for future structured extension. |

Wall-clock timestamps are deliberately **excluded** from `ReportMetadata`.
See `docs/DETERMINISM.md`.

---

## Canonical Day 1 Entities

| entity_id | kind | service |
|-----------|------|---------|
| `users.phone_number` | `DATABASE` | `demo-commerce-db` |
| `user-service.UserService` | `SERVICE` | `user-service` |
| `profile-api.ProfileAPI` | `API` | `profile-api` |
| `android-client.ProfileClient` | `CLIENT` | `android-client` |

## Canonical Day 1 Edges

| source | target | kind |
|--------|--------|------|
| `users.phone_number` | `user-service.UserService` | `DB_READ` |
| `user-service.UserService` | `profile-api.ProfileAPI` | `HTTP_CALL` |
| `profile-api.ProfileAPI` | `android-client.ProfileClient` | `API_CONSUMES` |

## Day 4 Blast Radius Models

`BlastRadiusRequest` selects a target and caller-controlled `max_hops` and
`max_paths` bounds. `BlastRadiusReport` contains immutable ranked
`BlastRadiusFinding` objects. Each finding includes its `ImpactPath`, edge types,
structured evidence, hop distance, deterministic heuristic severity, category,
and explanation. `ImpactSummary` reports direct, indirect, and total affected
counts. These models do not represent final deployment risk or probability.
