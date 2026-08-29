# PreFlight — Day 1 Implementation

## Objectives

Build the complete foundation for a deployment-survivability analysis system:

1. Repository architecture
2. Multi-service demonstration fixture (demo-commerce)
3. Canonical domain schemas (Pydantic v2)
4. Dependency graph (NetworkX DiGraph)
5. Deterministic graph builder
6. Deterministic traversal
7. Deterministic canonical serialization
8. Smoke test (end-to-end)
9. Unit + integration test suite
10. Documentation

## Acceptance Criteria

| Criterion | Status |
|-----------|--------|
| Repository structure exists | ✓ |
| Python project installs | ✓ |
| Pydantic models validate | ✓ |
| NetworkX graph builds | ✓ |
| Four canonical entities | ✓ |
| Three typed edges | ✓ |
| Canonical 3-hop path | ✓ |
| Correct ordered nodes | ✓ |
| Correct edge types | ✓ |
| Serialization deterministic | ✓ |
| SHA-256 identical across runs | ✓ |
| `pytest` passes | ✓ |
| `smoke.py` passes | ✓ |
| No network required | ✓ |
| No external AI API | ✓ |
| No secrets required | ✓ |
| Documentation exists | ✓ |

---

## Commands

### Install (editable, with dev dependencies)

```bash
pip install -e ".[dev]"
```

### Run tests

```bash
pytest
```

### Run smoke test

```bash
python scripts/smoke.py
```

### Lint

```bash
python -m ruff check .
```

### Type check

```bash
python -m mypy src
```

---

## Implementation Summary

### Domain layer (`src/preflight/domain/`)

- `enums.py` — `EntityKind` (6 values), `EdgeKind` (6 values)
- `entities.py` — `Entity` Pydantic model, immutable, validator on `entity_id`
- `graph_models.py` — `DependencyEdge`, `DependencyPath` with invariant enforcement
- `reports.py` — `AnalysisReport`, `ReportMetadata`, `SCHEMA_VERSION = "1.0"`
- `errors.py` — `PreFlightError`, `GraphValidationError`, `DuplicateEntityError`,
  `UnknownEntityError`, `InvalidDependencyError`

### Graph layer (`src/preflight/graph/`)

- `builder.py` — `GraphBuilder` (fluent), `PreFlightGraph`
- `traversal.py` — `find_downstream_paths`, `find_canonical_path`
- `serialization.py` — `canonical_graph`, `canonical_json`, `canonical_sha256`

### Fixtures (`src/preflight/fixtures/`)

- `loader.py` — `build_demo_commerce_graph()`, canonical entity/edge constants

### Demo fixture (`fixtures/demo-commerce/`)

- `database/schema.sql` — users table with phone_number
- `user-service/src/user_service.py` — Python service, DB_READ dependency
- `profile-api/src/profile_api.py` — Python API, HTTP_CALL + API_CONSUMES
- `android-client/src/profile_client.kt` — Kotlin client, terminal consumer

### Tests

- `tests/unit/test_schemas.py` — Pydantic validation (21 tests)
- `tests/unit/test_graph_builder.py` — GraphBuilder (18 tests)
- `tests/unit/test_traversal.py` — Traversal (16 tests)
- `tests/unit/test_serialization.py` — Serialization + determinism (17 tests)
- `tests/integration/test_demo_fixture.py` — End-to-end (16 tests)

---

## Canonical Day 1 Graph

```
users.phone_number  (DATABASE)
  │
  │  DB_READ
  ▼
user-service.UserService  (SERVICE)
  │
  │  HTTP_CALL
  ▼
profile-api.ProfileAPI  (API)
  │
  │  API_CONSUMES
  ▼
android-client.ProfileClient  (CLIENT)

Nodes:     4
Edges:     3
Hop count: 3
```
