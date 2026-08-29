# PreFlight

## Know what breaks before you deploy.

Software deployments fail in predictable ways. A column rename silently
breaks a mobile client. A service dependency is removed and three downstream
APIs start returning 500s. A database migration that looks safe deletes a
field that a legacy service still reads.

PreFlight is a deployment-survivability analysis system. It analyses a
software change and determines: what it can break, how far the impact
propagates, whether the deployment is dangerous, and whether rollback
remains possible.

It combines deterministic static analysis, typed dependency graphs,
database migration analysis, API compatibility analysis, rollback
feasibility scoring, and structured AI explanation — surfaced in a
phone-first UI built for fast pre-deployment decisions.

---

## Day 1 Foundation

Day 1 establishes the **deterministic dependency-graph foundation** on which
all subsequent analysis modules are built.

The canonical Day 1 demonstration traces what happens when the `phone_number`
column in a `users` database table changes:

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

A change to `users.phone_number` has a **blast radius of 3 hops**.
PreFlight traces this deterministically, with typed edges, from a clean
offline foundation.

---

## Quick Start

### Requirements

- Python 3.10+
- pip

### Install

```bash
cd preflight-demo
pip install -e ".[dev]"
```

### Run tests

```bash
pytest
```

Expected output: all tests pass.

### Run smoke test

```bash
python scripts/smoke.py
```

Expected output:

```
================================================
PRE-FLIGHT  DAY 1 SMOKE TEST
================================================

Building demo-commerce fixture graph...
  Graph nodes : 4
  Graph edges : 3

Traversing canonical dependency path...
  Canonical dependency chain:
    users.phone_number
  --DB_READ--> user-service.UserService
  --HTTP_CALL--> profile-api.ProfileAPI
  --API_CONSUMES--> android-client.ProfileClient

  Hop count   : 3
  Canonical path check : PASS

Verifying deterministic serialization...
  canonical_json match : PASS
  SHA-256              : <64-char hex>

================================================
Fixture       : demo-commerce
Graph nodes   : 4
Graph edges   : 3
Hop count     : 3
Determinism   : PASS
Canonical path: PASS

STATUS: DAY 1 FOUNDATION PASS
================================================
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

## Day 10: Real Orchestration

`POST /api/analyze` runs the real pipeline — `SemanticAnalyzer`,
`BlastRadiusEngine`, `DeploymentAnalyzer`, `analyze_api_contract`,
`analyze_rollback`, `decide`, `explain` — composed by
`preflight.orchestration.run_analysis()`. The HTTP API does not contain
hardcoded findings; findings are produced by the analysis pipeline from
real fixture files (`fixtures/demo-commerce/database/migration.sql`,
`schema.sql`, `profile-api/openapi.yaml`). Two scenarios are registered:
a destructive `DROP COLUMN` migration (`DO_NOT_DEPLOY`) and a safe
`ADD COLUMN` migration (`SAFE`) — both computed, not scripted. See
[docs/DAY_10.md](docs/DAY_10.md) and
[DAY_P0_ORCHESTRATION_REPORT.md](DAY_P0_ORCHESTRATION_REPORT.md) for the
full proof, including the change-input/change-output test.

```bash
python scripts/preflight_api.py 8000        # start the API
python scripts/api_smoke.py                 # health + determinism smoke test
python -m pytest tests/integration/test_orchestration_pipeline.py -q
```

---

## Architecture

```
src/preflight/
├── domain/       Pure data contracts (Pydantic). No infrastructure deps.
├── graph/        Graph construction, traversal, serialization (NetworkX).
└── fixtures/     Demo fixture loader. Day 2+ replaces with parsed extraction.
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full breakdown.

Other documentation:
- [docs/DATA_MODEL.md](docs/DATA_MODEL.md) — Entity, Edge, Path, Report schemas
- [docs/DETERMINISM.md](docs/DETERMINISM.md) — Determinism contract and verification
- [docs/DAY_1.md](docs/DAY_1.md) — Day 1 implementation details and commands
- [docs/LIMITATIONS.md](docs/LIMITATIONS.md) — Explicit scope boundaries

---

## Engineering Principles

- **Deterministic** — identical input always produces identical output, including SHA-256
- **Typed** — Pydantic v2 models at all system boundaries; enums for all categorical values
- **Testable** — unit and integration tests; no hard-coded assertions against fabricated data
- **Offline-first** — the analysis core requires no network access
- **Security-conscious** — no secrets, no HTTP calls, no dynamic code execution
- **Auditable** — every displayed value comes from the actual graph; nothing is fabricated

---

## Roadmap

| Day | Feature | Status |
|-----|---------|--------|
| 1 | Deterministic dependency graph foundation | **Complete** |
| 2 | Tree-sitter static parser (Python, Kotlin) | Planned |
| 3 | NetworkX graph extraction from parsed ASTs | Planned |
| 4 | Multi-hop blast-radius analysis | Planned |
| 5 | Graph hardening and edge-case handling | Planned |
| 6 | SQLGlot database migration analysis | Planned |
| 7 | OpenAPI / environment analysis | Planned |
| 8 | Rollback feasibility analysis | Planned |
| 9 | Deterministic risk engine + AI explainer | **Complete** |
| 10 | Real orchestration pipeline behind `/api/analyze` | **Complete** |
| 11 | 25-fixture benchmark + DVH | Planned |

Days 1–10 are implemented, independently tested, and composed behind a
single orchestrator. Day 11 is planned, not shipped.

---

## License

MIT
