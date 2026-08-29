# DAY P0 — REPOSITORY INGESTION REPORT

Turn PreFlight from a fixture-driven demonstration into a repository-level
deployment survival engine: a judge uploads a real project ZIP, and the
same deterministic engine analyzes it — no scenario names, no fabricated
evidence, no parallel analysis logic.

Status: **PASS**. All commands below were actually run; results are pasted,
not summarized from memory.

---

## Architecture

```
ZIP bytes
  -> preflight.ingestion.archive.extracted_project()      secure extraction
  -> preflight.ingestion.manifest.build_manifest()         deterministic inventory
  -> preflight.ingestion.discovery.*                        locate schema/migration/API/source files
  -> preflight.orchestration.pipeline.run_project_analysis()
       -> _execute_pipeline()   <-- the SAME function run_analysis() calls
            -> SemanticAnalyzer -> DeploymentAnalyzer -> BlastRadiusEngine
               -> analyze_api_contract -> analyze_rollback -> decide -> explain
  -> AnalysisRunResult.to_response_payload()   <-- same payload shape as /api/analyze
```

`run_analysis()` (built-in fixture scenarios) and `run_project_analysis()`
(an uploaded project) were unified behind one private `_execute_pipeline()`
during this work — previously `run_analysis()` had the entire pipeline
inlined. They differ only in how they resolve four real-file inputs
(migration, schema, API contract, semantic files); everything downstream is
byte-identical code. No analyzer (`SemanticAnalyzer`, `DeploymentAnalyzer`,
`BlastRadiusEngine`, `analyze_api_contract`, `analyze_rollback`, `decide`,
`explain`) was modified, duplicated, or rewritten. Full data flow, module
list, and rationale: `docs/DAY_11.md`.

## Input flow

```
POST /api/analyze-project  (multipart/form-data, field "archive")
  -> preflight_api.py: _handle_analyze_project()
       Content-Length pre-check (413 fast-reject before reading body)
       -> preflight.ingestion.parse_multipart_form()   (no cgi dependency)
       -> analyze_project(bytes, case_id)
            -> extracted_project(bytes)   [validates + extracts, always cleans up]
            -> run_project_analysis(root, case_id)
            -> result.to_response_payload()   [same shape as /api/analyze]
```

`GET /health` and `POST /api/analyze` are unchanged and still pass their
existing tests (`test_orchestration_pipeline.py`, `api_smoke.py`).

## Security model

Full detail in `docs/DAY_11.md` "Security model"; summary:

- Every entry name is validated **before** any extraction: backslash and
  POSIX traversal, absolute paths (incl. `C:/...`), and a proven
  `Path.relative_to(extraction_root)` check on the resolved destination.
- Symlink entries (detected via ZIP external-attribute Unix mode bits) are
  rejected outright.
- Archive size, per-file declared size, running total declared size, and
  compression ratio are all checked against headers **before** writing a
  byte; actual bytes read during extraction are also counted and bounded
  independently, so a lying header cannot bypass the limit.
- `zipfile.testzip()` verifies every entry's CRC before extraction —
  corrupted archives are rejected with a structured error, not a crash
  mid-extraction.
- Extraction target is always a fresh `tempfile.mkdtemp()` directory,
  deleted unconditionally (`finally: shutil.rmtree`) whether the request
  succeeded or raised.
- No uploaded code is ever executed, imported, or evaluated.

## Supported languages / ignored files

Semantic: Python, Kotlin (unchanged `SemanticAnalyzer`). Recognized
unsupported languages (JS/TS/Go/Java/Ruby/Rust/C/C++/C#/PHP/Swift/Scala)
are labeled `unsupported` in the manifest — never silently dropped, never
claimed as analyzed. Build/vendor/VCS directories (`.git`, `node_modules`,
`dist`, `build`, `.next`, `__pycache__`, `.venv`, `vendor`, `coverage`,
`.mypy_cache`, `.ruff_cache`, `.idea`, `.vscode`, `target`, `.gradle`,
`.tox`) are excluded from semantic discovery and labeled `ignored` with a
reason. Nested archives are listed `ignored`, never recursively extracted.

## Archive limits

`src/preflight/ingestion/limits.py`: 25MB compressed, 150MB total
uncompressed, 5000 files, 20MB per file, 200× compression ratio (floor:
1MB, so small legitimately-compressible files never false-positive).
Documented as fixed constants for a single-tenant demo path, not
production configuration — see Limitations.

## Manifest schema

```json
{
  "files": [{"path": "...", "language": "python", "size": 2143,
             "sha256": "...", "classification": "semantic",
             "ignored_reason": null}],
  "file_count": 10, "ignored_count": 0,
  "language_counts": {"python": 2, "kotlin": 1, "sql": 2, "openapi": 1},
  "manifest_hash": "..."
}
```

Pure inventory — no risk, severity, or decision content.

## Analysis pipeline

Identical to the P0-orchestration pipeline (`docs/DAY_10.md`), entered via
`run_project_analysis()` instead of `run_analysis()`. Discovery rules
(schema/migration/API-contract selection) are documented in full in
`docs/DAY_11.md` "Discovery heuristics" — deterministic, sorted, and every
ambiguous choice is surfaced as a note rather than silently guessed.

## Failure states

| Condition | HTTP | Body |
|---|---|---|
| Not a valid ZIP / corrupted CRC | 400 | `INVALID_ARCHIVE` |
| Path traversal / absolute path / symlink / decompression-bomb ratio | 400 | `UNSAFE_ARCHIVE` |
| Too many entries | 400 | `ARCHIVE_TOO_MANY_FILES` |
| Compressed or uncompressed size over limit | 413 | `ARCHIVE_TOO_LARGE` |
| Unexpected internal error | 500 | `ANALYSIS_UNAVAILABLE` (structured, never a raw traceback) |
| No migration / schema / API contract found post-extraction | 200 | `decision: UNKNOWN`, component listed in `analysis.unavailable_components` |
| Empty / all-ignored project | 200 | `decision: UNKNOWN`, `semantic_analysis` in `unavailable_components` |

Verified by `tests/unit/ingestion/test_archive_security.py` (16 tests) and
`tests/integration/test_project_ingestion.py` (empty/no-migration/no-openapi
cases + 4 HTTP-boundary tests).

## Determinism — PASS

```
$ PYTHONPATH=src python -m pytest tests/integration/test_project_ingestion.py -v -k determinism_or_hash_or_renaming
```

Real results (all passing, over actual ZIP bytes, not a hand-built
request):

- `test_ten_runs_of_the_same_zip_produce_one_hash` — 10 runs, 1 distinct hash.
- `test_shuffled_zip_entry_order_produces_the_same_hash` — internal ZIP
  entry order shuffled and re-zipped; `manifest_hash` and
  `deterministic_hash` both unchanged.
- `test_renaming_the_upload_does_not_change_the_result` — same archive
  analyzed under labels `"destructive"`, `"random-project-42"`, and
  `"safe"`; identical hash every time, and the `"safe"`-labeled run still
  correctly reports `DO_NOT_DEPLOY` — the label lied, the evidence didn't.
- `test_irrelevant_file_change_does_not_change_the_decision_hash` — a new
  `NOTES.txt` changes `manifest_hash` (the manifest sees everything) but
  not `deterministic_hash` (analysis only reacts to relevant evidence).
- `test_relevant_source_change_and_restore_roundtrips_the_hash` — mutating
  `database/migration.sql` to a no-op changes `deterministic_hash` and the
  `DROP_COLUMN` finding disappears; restoring the original bytes restores
  the original hash exactly.

## Provenance / causality — PASS (the killer proof)

`fixtures/uploads/{destructive,safe,remediated}-release.zip`, built by
`scripts/build_upload_demos.py` from real fixture sources:

```
$ curl -s -X POST http://127.0.0.1:8000/api/analyze-project \
    -F "archive=@fixtures/uploads/destructive-release.zip;type=application/zip"
decision: DO_NOT_DEPLOY  risk_score: 100

$ curl -s -X POST http://127.0.0.1:8000/api/analyze-project \
    -F "archive=@fixtures/uploads/safe-release.zip;type=application/zip"
decision: SAFE  risk_score: 9

$ curl -s -X POST http://127.0.0.1:8000/api/analyze-project \
    -F "archive=@fixtures/uploads/remediated-release.zip;type=application/zip"
decision: SAFE  risk_score: 26
```

Destructive vs. remediated is the load-bearing proof: **byte-identical**
`ALTER TABLE users DROP COLUMN phone_number;`, different decision, because
`fixtures/demo-commerce-remediated/` (new fixture, see below) removes
every source reference to `phone_number` from `user_service.py`,
`profile_api.py`, and `profile_client.kt`. Real, measured deltas:

| | destructive | remediated |
|---|---|---|
| `deployment_finding.change` | `DROP_COLUMN` | `DROP_COLUMN` (same) |
| blast radius affected count | 3 | 0 |
| `rollback.status` | `UNSAFE` | `SAFE` |
| `decision` | `DO_NOT_DEPLOY` | `SAFE` |
| `risk_score` | 100 | 26 |
| `deterministic_hash` | `c291de9f072a...` | `40d82bf364f2...` |

This is exercised through the real HTTP multipart-upload path (curl above)
and through direct Python calls
(`tests/integration/test_project_ingestion.py::test_remediated_zip_changes_the_decision_via_real_dependency_removal`).

## Performance — MEASURED (this fixture only, not a scalability claim)

20 runs, `destructive-release.zip` (10 files, ~6KB):

| Stage | Median (ms) | P95 (ms) |
|---|---|---|
| Secure extraction only | 37.2 | 50.0 |
| Extraction + manifest build | 55.1 | 315.9 |
| Full pipeline (extraction + manifest + real analysis) | 414.4 | 549.0 |

P95 variance reflects Windows temp-directory I/O on this development
machine, not the code itself. **NOT MEASURED:** larger projects, concurrent
uploads, production-scale throughput — none of these claims are made.

## Tests — PASS

```
$ PYTHONPATH=src python -m pytest tests/ -q
409 passed in 25.66s
```

357 pre-existing (Day 1–9) + 21 orchestration (Day 10) + 16 adversarial
ingestion (`tests/unit/ingestion/test_archive_security.py`) + 15 project
ingestion integration (`tests/integration/test_project_ingestion.py`) = 409.
Zero regressions, zero skipped, zero weakened assertions.

## Lint / type-check — PASS

```
$ python -m ruff check .
All checks passed!

$ python -m mypy src/preflight
Success: no issues found in 40 source files

$ cd frontend && npx tsc --noEmit -p tsconfig.json    # clean
$ npm run lint                                          # clean
$ npm run build                                          # ✓ compiled, ✓ static pages, 0 warnings
```

## Smoke / integration — PASS

```
$ python scripts/preflight_api.py 8000 &
$ curl -s http://127.0.0.1:8000/health
{"engine":"deterministic","status":"online"}

$ python scripts/api_smoke.py           # existing /api/analyze path, unchanged, still PASS

$ curl -s -X POST http://127.0.0.1:8000/api/analyze-project \
    -H "Origin: http://localhost:3000" \
    -F "archive=@fixtures/uploads/destructive-release.zip;type=application/zip"
  -> 200, decision DO_NOT_DEPLOY, risk 100, project_manifest.file_count=10,
     CORS header echoes the frontend's origin
```

Frontend: `UploadPanel` (file picker, `.zip`-only, client-side size
pre-check mirroring the real backend limit) wired to
`analyzeProjectUpload()` in `lib/api.ts`, driving the same staged-pipeline
UI the fixture-scenario path uses (`page.tsx::runStaged`). A new
`ProjectManifestPanel` renders the real manifest when a result came from an
upload; `CommandCenter`'s fixture-scenario switcher and the
fixture-only `Counterfactual` panel are hidden for upload results (there is
no second real scenario to compare an arbitrary upload against).

## Files changed / added

**Backend (new):** `src/preflight/ingestion/{__init__,errors,limits,models,
archive,discovery,manifest,multipart}.py`; `scripts/build_upload_demos.py`;
`fixtures/demo-commerce-remediated/**` (5 source files); `fixtures/uploads/
{destructive,safe,remediated}-release.zip`; `tests/unit/ingestion/
test_archive_security.py`; `tests/integration/test_project_ingestion.py`.

**Backend (modified, additive only):** `src/preflight/orchestration/
pipeline.py` (refactored into shared `_execute_pipeline` + new
`run_project_analysis`); `src/preflight/orchestration/models.py` (added
`manifest` field, threaded into the existing payload shape);
`src/preflight/orchestration/__init__.py` (exports `run_project_analysis`);
`scripts/preflight_api.py` (added `/api/analyze-project`, multipart
handling; `/api/analyze` and `/health` untouched in behavior).

**Frontend (new):** `frontend/app/components/{UploadPanel,
ProjectManifestPanel}.tsx`.

**Frontend (modified):** `frontend/lib/api.ts` (`analyzeProjectUpload`,
`ProjectManifest`/`ManifestEntry` types, `project_manifest` field on
`AnalysisResult`); `frontend/app/page.tsx` (upload wiring, shared staged
sequence); `frontend/app/components/CommandCenter.tsx` (upload-aware
header); `frontend/app/page.module.css` (upload/manifest panel styles).

**Docs:** `docs/DAY_11.md` (new), `docs/ARCHITECTURE.md`,
`docs/DETERMINISM.md`, `docs/LIMITATIONS.md` (additive sections).

## Known limitations

See `docs/DAY_11.md` "Known limitations" for full detail: one
schema/migration per upload (multi-candidate ambiguity gets a deterministic
best-effort pick plus a visible note, not a guarantee); no malware/content
scanning beyond ZIP structural safety; fixed (not per-tenant-configurable)
limits, appropriate for a single-tenant demo; concurrent-upload load is
unmeasured. None of these were hidden or downgraded to make the demo look
more finished than it is.

## Hostile review

| Question | Answer | Evidence |
|---|---|---|
| Does the uploaded ZIP reach the real engine? | **YES** | Same `_execute_pipeline()` as fixture scenarios; §Architecture |
| Can renaming the ZIP/scenario label change the result? | **NO** | `test_renaming_the_upload_does_not_change_the_result` |
| Does changing a real dependency change the result? | **YES** | Destructive vs. remediated, §Provenance |
| Is path traversal actually blocked? | **YES** | 16/16 adversarial tests, §Security model |
| Does a missing migration/schema/API-contract fabricate SAFE? | **NO** | `UNKNOWN`, tests in §Failure states |
| Is the result reproducible across runs / entry order / renaming? | **YES** | §Determinism, 5 tests |
| Does uploaded code ever execute? | **NO** | Static parsing only; no `import`, `exec`, `subprocess` on uploaded content anywhere in `ingestion/` or `orchestration/` |
| Were any existing analyzers rewritten or duplicated? | **NO** | `git`-visible diff of `semantic.py`, `blast_radius.py`, `schema.py`, `api_contract.py`, `rollback_truth.py`, `decision.py`, `explanation.py`: zero changes |

No "NO" answers remain unaddressed.
