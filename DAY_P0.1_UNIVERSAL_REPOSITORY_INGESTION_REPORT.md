# DAY P0.1 — UNIVERSAL REPOSITORY INGESTION REPORT

Forensics-first fix: discovery was already repository-agnostic; the real
gap was in **status semantics** — missing/unsupported evidence could look
identical to "analyzed, found nothing." That gap is now closed, verified
against a real third-party repository, not just the QuickMart fixture.

---

## 1. Exact original failure

Uploading a real "E-Commerce Platform" ZIP reported: 21 files discovered,
6 ignored, 0 supported source files, migration/API/schema unavailable,
rollback UNKNOWN.

## 2. Root cause

**Forensics, not assumption.** The user's actual ZIP was located
(`E - Commerce Platform (1).zip`, ~/Downloads) and run directly through
`preflight.ingestion.extracted_project` + `build_manifest`:

```
E - Commerce Platform/
├── index.html, cart.html, orders.html, product.html, support.html
├── css/*.css (5 files)
├── js/app.js, cart.js, index.js, orders.js, product.js
└── images/*.png, hero_banner.png (6 files)
```

This is a **pure static HTML/CSS/JavaScript site — zero Python, zero
Kotlin, zero SQL, zero OpenAPI.** `SemanticAnalyzer` supports Python and
Kotlin only (unchanged from Day 1). "0 supported source files" was
**correct**, not a discovery bug. Manifest classification already worked
exactly as designed: the 5 `.js` files were correctly labeled
`unsupported`, the 6 images `ignored`, the 10 `.html`/`.css` files `other`.
Root/nested-folder handling was never the problem — `root.rglob("*")`
already walks the whole extracted tree regardless of wrapper-folder
nesting, with no hardcoded path assumptions anywhere in
`preflight/ingestion/discovery.py`.

**The actual bugs, found by tracing the full response payload:**

1. **Status collapse.** `blast_radius` fell back to an empty
   `BlastRadiusReport` (0 affected) whenever the changed entity wasn't in
   the graph — the same code path whether semantic analysis genuinely ran
   and found zero dependents (a real "ANALYZED, 0 affected" result, as in
   the Day 10 remediated-fixture case) or never ran at all. These are
   different facts and must never render identically — this was the P0.1
   acceptance requirement (mission §7/§25) and the one real defect.
2. **Temp-path leakage.** `analysis.notes` interpolated the raw
   filesystem extraction path (`C:\Users\...\AppData\Local\Temp\preflight-
   upload-...`) into user-facing text.
3. **Unhandled malformed-OpenAPI crash**, found while building the
   adversarial test matrix: `analyze_api_contract`/`parse_openapi_document`
   raise on invalid YAML/JSON rather than degrading gracefully the way
   `DeploymentAnalyzer` already does for malformed SQL. A single bad
   contract file would abort the whole analysis instead of reporting
   `PARSE_ERROR` for that one component.

## 3. Architecture before / after

**Before:** `_execute_pipeline` computed `unavailable_components` (a flat
list of component names) and free-text `notes`, with no structured
per-component outcome. Blast radius's "empty" and "unavailable" states
were indistinguishable in the response.

**After:** `_execute_pipeline` additionally computes a `capabilities` map
— one `{status, detail}` entry per analyzer (`source`, `database`,
`blast_radius`, `api_contract`, `rollback`) — from data it already has
(`graph.node_count`, `manifest.unsupported_count`,
`deployment_finding.change`, `has_real_target`, `api_contract_finding`,
`rollback.status`). This is a **pure presentation transform**, exactly the
same pattern already established for `_schema_diff` in Day 10 — it
classifies real outcomes, computes no new evidence, and duplicates no
analyzer logic. `has_real_target` is the key new signal: a migration file
must have been found *and* parsed into an identifiable schema object
before blast radius is even attempted — previously a missing migration
still fell through to the "empty blast radius" branch.

No analyzer (`SemanticAnalyzer`, `DeploymentAnalyzer`, `BlastRadiusEngine`,
`rollback_truth.py`) was modified. `analyze_api_contract`/
`parse_openapi_document` in `api_contract.py` were **not** touched;
`_execute_pipeline` now wraps the call site in a `try/except` for
`yaml.YAMLError`/`json.JSONDecodeError`/`ValueError`/`KeyError`/`TypeError`
— the same boundary-level defensiveness already used everywhere else in
the orchestrator (e.g. checking `api_contract_path.exists()` before
calling).

## 4. Repository-root algorithm

**No change was needed, and none was made.** `discovery.find_semantic_files`,
`find_schema_and_migration`, and `find_api_contract` already call
`root.rglob("*")` unconditionally — proven this session against: the ZIP
root itself, one level of nesting, deep nesting (6 levels), and a
multi-directory monorepo (`services/orders/`, `services/inventory/`,
`libs/shared/`), all in `tests/integration/test_universal_ingestion.py`.
What *was* added is **informational** root/boundary reporting:
`find_framework_signals(root)` (new in `discovery.py`) walks the tree for
recognized project-marker files (`pyproject.toml`, `package.json`,
`go.mod`, `Cargo.toml`, `pom.xml`, `build.gradle`, `*.csproj`, ...) and
reports their repository-relative paths in the manifest's
`framework_signals` field — purely for judge-facing transparency ("here is
where project boundaries likely are"). It never restricts, gates, or
directs what gets scanned.

Full `ROOT_AMBIGUOUS`/`MULTI_REPOSITORY_ARCHIVE` detection with independent
per-subproject analysis was **not** built this session — see Known
Limitations. Framework-signal reporting proves the underlying signal
(multiple manifests exist) is already visible; acting on it (splitting
into independent analyses) is future work, not silently faked here.

## 5. File classification model

Unchanged from Day 11 (`preflight/ingestion/discovery.py::classify`):
`semantic` / `migration_candidate` / `api_contract` / `unsupported` /
`ignored` / `other`. Verified this session to correctly classify a real
third-party repository it had never seen: 5 `unsupported` (`.js`), 6
`ignored` (images), 10 `other` (`.html`/`.css`).

## 6. Language capability model

`SEMANTIC_SUFFIXES = {.py, .kt}` (Tree-sitter-backed, real). 
`UNSUPPORTED_SOURCE_SUFFIXES` (`.js/.jsx/.ts/.tsx/.go/.java/.rb/.rs/.c/.cpp/
.cs/.php/.swift/.scala`) are recognized-but-unparsed — reported honestly,
never silently dropped, never claimed analyzed. `ProjectManifest` now
carries `unsupported_count` as a first-class field (was previously only
derivable by filtering `files`), and the `capabilities.source` entry uses
it directly to distinguish `UNSUPPORTED` (real code, wrong language) from
`UNAVAILABLE` (no code at all — e.g. a docs-only archive).

## 7. SQL / 8. OpenAPI / 9. Schema discovery

Unchanged discovery heuristics (Day 11, `docs/DAY_11.md`): deterministic,
sorted, content-based (SQLGlot actually parses candidates; OpenAPI parsing
actually validates YAML/JSON structure). What changed: the orchestration
boundary now distinguishes, per component, `UNAVAILABLE` (nothing found)
from `PARSE_ERROR` (found, but invalid) from `ANALYZED` — previously SQL
already had this distinction internally (via `DeploymentAnalyzer`'s own
graceful `PARSE_ERROR` finding); OpenAPI did not, and now does, at the
orchestration boundary only.

## 10. Monorepo / 11. multi-project handling

Proven, not merely designed: `test_monorepo_layout_discovers_across_all_services`
uploads a two-service tree (`services/orders/` — Python + `pyproject.toml`,
`services/inventory/` — JS + `package.json`) plus a shared lib
(`libs/shared/utils.py`) under names that share nothing with any PreFlight
fixture; both `pyproject.toml` and `package.json` are correctly surfaced as
`framework_signals`, the Python files reach the semantic graph, and the JS
file is correctly labeled `unsupported` rather than silently disappearing.
The analysis remains **one graph across the whole extracted tree** — not
one per detected project — matching what the existing `SemanticAnalyzer`
already supports architecturally (mission §13's cross-component causal
chain, proven via `test_cross_service_dependency_chain_is_preserved_in_a_generic_layout`).

## 12. Analyzer capability matrix

New response field `capabilities` (see `AnalysisResult.capabilities` in
`frontend/lib/api.ts`, `_capability_matrix()` in `pipeline.py`):

```json
{
  "source": {"status": "UNSUPPORTED", "detail": "5 file(s) in a language PreFlight does not parse; 0 Python/Kotlin files were found."},
  "database": {"status": "UNAVAILABLE", "detail": "No SQL migration file was found."},
  "blast_radius": {"status": "NOT_APPLICABLE", "detail": "No real schema change was identified to compute downstream impact for."},
  "api_contract": {"status": "UNAVAILABLE", "detail": "No OpenAPI/Swagger contract file was found."},
  "rollback": {"status": "UNKNOWN", "detail": "Rollback compatibility resolved to UNKNOWN."}
}
```

Rendered on the frontend by the new `CapabilityMatrix.tsx` ("PROJECT
UNDERSTANDING" panel), placed immediately after the verdict, before the
project manifest — matching the mission's information architecture.

## 13. Failure semantics

| Status | Means | Never confused with |
|---|---|---|
| `ANALYZED` | The analyzer ran and produced a real result (including a real zero) | `UNAVAILABLE` |
| `UNAVAILABLE` | Required input was never found | `ANALYZED` (0) |
| `NOT_APPLICABLE` | No real target/change exists to analyze | `ANALYZED` (0) |
| `UNSUPPORTED` | Real code exists, in a language not yet parsed | `UNAVAILABLE` (no code) |
| `PARSE_ERROR` | Input existed but failed to parse | `UNAVAILABLE` |

`decide()` itself is untouched — these statuses are presentation-layer
classification of facts `decide()` and the analyzers already produced;
`unavailable_components`/`decision` continue to be the actual policy
inputs, unchanged.

## 14. Security model

Unchanged from Day 11 — all 16 adversarial archive tests still pass
(traversal, absolute paths, symlinks, oversized/too-many-files archives,
corrupted CRC, decompression-bomb ratio). No uploaded code is executed;
`SemanticAnalyzer` performs static Tree-sitter parsing only.

## 15. Provenance

Fixed this session: `_execute_pipeline` now takes a `display_root: str`
label (a safe, human-readable string — `"the uploaded project"` for
uploads, the fixture's repo-relative path for built-in scenarios) used in
every user-facing note instead of the real filesystem `project_root`. Two
`_read_optional`/`_schema_snapshots`-adjacent error messages that
previously interpolated a full path now use `path.name` only. Verified by
`test_no_local_temp_path_leaks_into_response`, which asserts `"AppData"`,
`"preflight-upload-"`, and the actual temp directory string are all absent
from the full serialized response.

## 16. Canonicalization / 17. Determinism

Unchanged mechanism from Day 11 (`build_manifest`'s sorted, content-hashed
walk; `_execute_pipeline`'s single deterministic call path) — all 5
existing determinism tests in `test_project_ingestion.py` still pass
unmodified after this session's refactor (10 identical runs; shuffled ZIP
entry order; three different scenario labels on one archive; irrelevant
file addition; relevant mutation + restore). No new determinism risk was
introduced by the capability-matrix computation, since it is a pure
function of already-deterministic inputs.

## 18. Performance

Not re-measured this session — no architecture change affects the
extraction/manifest/analysis cost model established in `docs/DAY_11.md`
(the capability matrix is O(1) additional work per response, computed from
values already in memory).

## 19. Complete test matrix

`tests/integration/test_universal_ingestion.py` (new, 16 tests): repo at
ZIP root (A), nested one folder (B), deeply nested (C), monorepo (D),
backend-only (F), **frontend-only static site — the exact real-bug shape,
reconstructed synthetically, not the user's actual file** (G, the P0.1
regression case), source+SQL (H), SQL-without-source (K), malformed SQL
(O), malformed OpenAPI (P, caught the real bug in §2.3), documentation-only
(R), no-temp-leak provenance check, cross-service causal chain (§13), and
three ZIP-filename variants proving the label never affects the result.
Combined with the 16 archive-security tests (Day 11) and 15
project-ingestion tests (determinism, causality, HTTP boundary): **47
ingestion-specific tests**, all passing.

## 20. Real regression results

### QuickMart / demo-commerce fixtures (unchanged behavior, proven via live HTTP upload)

| ZIP | Decision | Risk | source | database | blast_radius | api_contract | rollback |
|---|---|---|---|---|---|---|---|
| `destructive-release.zip` | DO_NOT_DEPLOY | 100 | ANALYZED | ANALYZED | ANALYZED | ANALYZED | UNSAFE |
| `safe-release.zip` | SAFE | 9 | ANALYZED | ANALYZED | ANALYZED | ANALYZED | SAFE |
| `remediated-release.zip` | SAFE | 26 | ANALYZED | ANALYZED | ANALYZED | ANALYZED | SAFE |

Decision hash for `destructive-release.zip` is byte-identical to every
prior session's report (`9a0d8eb4acf467e7...`) — this refactor changed
zero bits of the actual analysis for the working case.

## 21. Structurally different repository result (real, not synthetic)

```
$ curl -X POST http://127.0.0.1:8000/api/analyze-project \
    -F "archive=@E - Commerce Platform (1).zip;type=application/zip"

decision: UNKNOWN   risk_score: 9
capabilities:
  source        -> UNSUPPORTED    (5 unsupported-language files; 0 Python/Kotlin)
  database      -> UNAVAILABLE    (no SQL migration file found)
  blast_radius  -> NOT_APPLICABLE (no real schema change to compute impact for)
  api_contract  -> UNAVAILABLE    (no OpenAPI/Swagger file found)
  rollback      -> UNKNOWN
manifest.unsupported_count: 5
```

Also live-tested against a synthetic two-service monorepo
(`services/orders/` Python + `pyproject.toml`, `services/inventory/`
JS + `package.json`) through the actual running HTTP endpoint:
`source: ANALYZED`, `framework_signals: ["services/inventory/package.json",
"services/orders/pyproject.toml"]`.

## 22. Tests / Lint / Type-check — PASS

```
$ PYTHONPATH=src python -m pytest tests/ -q
425 passed in 8.67s        # 409 prior + 16 new universal-ingestion tests

$ python -m ruff check .
All checks passed!

$ python -m mypy src/preflight
Success: no issues found in 40 source files

$ cd frontend && npx tsc --noEmit -p tsconfig.json    # clean
$ npm run lint                                          # clean
$ npm run build                                          # ✓ compiled, ✓ static, 0 warnings

$ python scripts/smoke.py                # STATUS: DAY 3 SEMANTIC PIPELINE PASS
$ python scripts/api_smoke.py            # STATUS: DAY 10 API INTEGRATION PASS
$ node scripts/api-integration.mjs       # destructive/safe hashes both PASS, unchanged
```

## 23. Known limitations

- **`ROOT_AMBIGUOUS` / `MULTI_REPOSITORY_ARCHIVE` states are not implemented.**
  `framework_signals` proves the underlying detection signal exists
  (multiple manifests found), but the pipeline still analyzes the whole
  extracted tree as one graph rather than offering independent per-project
  analysis or flagging ambiguity when signals conflict. This is a real,
  acknowledged gap — not hidden behind a fabricated "detected" state.
- **No new language support.** JavaScript/TypeScript/Go/Java/etc. remain
  `UNSUPPORTED`, honestly reported, never parsed. Adding a language means
  adding a real Tree-sitter grammar and `SemanticAnalyzer` support — out of
  scope here per the mission's own instruction not to fake capabilities.
- **`.html`/`.css` are classified `other`, not `unsupported`.** They are
  presentation, not code PreFlight's dependency model would ever reason
  about (no DB/API/service semantics lives in markup) — this is a
  deliberate distinction, not an oversight, but is worth flagging as a
  taxonomy choice a reviewer might weigh differently.
- **One migration/schema per upload**, unchanged from Day 11 — a project
  with genuinely ambiguous multiple migration candidates and no dedicated
  `migrations/` directory still gets a deterministic best-effort pick with
  a visible note, not a guaranteed-correct one.
- **Performance was not re-measured** this session; no architectural change
  invalidates the Day 11 numbers.
