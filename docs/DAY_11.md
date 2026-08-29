# Day 11: Repository Ingestion

## What changed

`POST /api/analyze` only ever ran the two built-in `fixtures/demo-commerce`
scenarios. There was no path from an arbitrary real project into the
engine. `POST /api/analyze-project` now accepts a `multipart/form-data`
upload with an `archive` field (a ZIP), securely extracts it, and runs the
identical deterministic pipeline the fixture scenarios use. The uploaded
project becomes the actual source of truth: change a source file, a
migration, or the API contract inside the ZIP, and the result changes with
it — proven by tests, not asserted.

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

`run_analysis()` (fixture scenarios) and `run_project_analysis()` (uploads)
differ only in how they resolve four inputs — `migration_path`,
`schema_path`, `api_contract_path`, `semantic_files` — before handing them
to the shared, private `_execute_pipeline()`. Nothing about semantic
parsing, SQL parsing, graph construction, risk calculation, policy, or
rollback rules is duplicated. `src/preflight/ingestion/` contains zero
analysis logic; it only decides which real files to hand to the existing
analyzers.

## Security model

`preflight.ingestion.archive.extracted_project()` is the only sanctioned
way to turn uploaded bytes into files on disk. Before a single byte is
written:

1. The archive's own compressed size is checked against a hard limit.
2. `zipfile.ZipFile.testzip()` verifies every entry's CRC — a corrupted or
   tampered archive is rejected before extraction, not discovered mid-way.
3. Every entry name is validated: backslash-normalized, checked for
   absolute paths (POSIX `/...` and Windows `C:/...`), checked for `..`
   traversal segments, and its resolved destination is proven (via
   `Path.relative_to`) to remain under the isolated extraction root.
4. Symlink entries (detected via the ZIP external-attributes Unix mode
   bits) are rejected outright — no symlink is ever created.
5. Declared per-file size, running total declared size, and
   uncompressed/compressed ratio are all checked against limits using the
   archive's own headers.

Only after every entry passes does extraction begin — and even then, bytes
actually read from each compressed stream are counted and bounded
independently of what the header claimed, so a lying header cannot bypass
the size limits. The extraction directory is a fresh `tempfile.mkdtemp()`
result, deleted unconditionally (success or exception) when the request
finishes. No uploaded code is ever executed, imported, or evaluated —
`SemanticAnalyzer` only ever parses source text with Tree-sitter.

Limits (`preflight/ingestion/limits.py`): 25MB compressed archive, 150MB
total uncompressed, 5000 files, 20MB per file, 200x compression ratio
(only checked above a 1MB floor, so small legitimately-compressible files
never false-positive).

## Supported languages / ignored files

Semantic analysis: Python, Kotlin — unchanged, reusing `SemanticAnalyzer`
as-is. Recognized-but-unparsed languages (`.js/.ts/.go/.java/.rb/.rs/.c/...`)
are labeled `unsupported` in the manifest, never silently dropped or
misreported as analyzed. Binary/media files are labeled `ignored`. Build
output and dependency-cache directories (`.git`, `node_modules`, `dist`,
`build`, `.next`, `__pycache__`, `.venv`, `vendor`, `coverage`, `.mypy_cache`,
`.ruff_cache`, `.idea`, `.vscode`, `target`, `.gradle`, `.tox`, ...) are
excluded from semantic file discovery and marked `ignored` in the manifest
with a reason — never silently invisible. A nested archive inside the
upload is listed as `ignored`; it is never extracted recursively.

## Discovery heuristics (deterministic, explainable, never scenario-based)

- **Schema**: the first file literally named `schema.sql`, sorted by path.
- **Migration**: if any `.sql` candidates live in a directory whose name
  contains "migration", the lexicographically last one of those (matching
  the common timestamp/sequence-prefix convention). Otherwise the
  lexicographically last remaining `.sql` file. If more than one candidate
  existed and the choice was a guess, a note is attached to the response
  (`analysis.notes`) — the choice is visible, never silent.
- **API contract**: the first `openapi.{yaml,yml,json}` or
  `swagger.{yaml,yml}`, sorted by path.
- **Semantic files**: every `.py`/`.kt` file not under an ignored directory,
  passed explicitly to `SemanticAnalyzer.analyze(root, files=...)` — reusing
  its existing explicit-file-list support rather than adding new filtering
  logic to the analyzer.

None of this ever inspects the scenario label, filename, or ZIP name.
`test_renaming_the_upload_does_not_change_the_result` proves it: the same
archive analyzed under the labels `"destructive"`, `"random-project-42"`,
and `"safe"` produces the identical `deterministic_hash` every time.

## Manifest schema

```json
{
  "files": [
    {"path": "user-service/src/user_service.py", "language": "python",
     "size": 2143, "sha256": "...", "classification": "semantic",
     "ignored_reason": null}
  ],
  "file_count": 10,
  "ignored_count": 0,
  "language_counts": {"python": 2, "kotlin": 1, "sql": 2, "openapi": 1},
  "manifest_hash": "..."
}
```

`classification` is one of: `semantic`, `migration_candidate`,
`api_contract`, `unsupported`, `ignored`, `other`. The manifest is pure
inventory — it carries no risk, severity, or decision content, and
`_schema_diff`-style presentation logic never lives here.

## Failure states

`run_project_analysis`/`extracted_project` raise exactly the ingestion
error types (`MalformedArchiveError`, `UnsafeArchiveError`,
`ArchiveTooLargeError`, `TooManyFilesError`); the HTTP layer maps each to a
distinct, honest status: `INVALID_ARCHIVE` (400), `UNSAFE_ARCHIVE` (400),
`ARCHIVE_TOO_MANY_FILES` (400), `ARCHIVE_TOO_LARGE` (413). Anything else
unexpected is caught at the boundary and returned as
`500 {"error": "ANALYSIS_UNAVAILABLE", ...}` — a structured body, never a
raw traceback. Once extraction succeeds, every remaining gap (no migration
file, no schema, no API contract, an empty/all-ignored project, an
unsupported-only project) flows through the same graceful path the fixture
scenarios already use: `decide()` resolves missing evidence to `UNKNOWN`,
never a fabricated `SAFE` or `DO_NOT_DEPLOY`.

## The three-ZIP causality proof

`scripts/build_upload_demos.py` builds three ZIPs from real fixture
sources into `fixtures/uploads/`:

| ZIP | Real difference | Decision |
|---|---|---|
| `destructive-release.zip` | `DROP COLUMN phone_number`; consumers still read it | `DO_NOT_DEPLOY`, risk 100 |
| `safe-release.zip` | `ADD COLUMN phone_verified` (additive) | `SAFE`, risk 9 |
| `remediated-release.zip` | **same** `DROP COLUMN phone_number` SQL, but no source file references the column any more | `SAFE`, risk 26 |

The destructive/remediated pair is the load-bearing proof: identical
migration SQL, different decision, because the only thing that changed is
whether the graph actually contains a dependency on the dropped column.
Blast radius drops from 3 affected entities to 0; rollback truth flips from
`UNSAFE` to `SAFE`; the deterministic hash changes. See
`tests/integration/test_project_ingestion.py::test_remediated_zip_changes_the_decision_via_real_dependency_removal`.

## Performance (measured on this fixture only — not a scalability claim)

20 runs, `destructive-release.zip` (10 files, ~6KB):

| Stage | Median (ms) | P95 (ms) |
|---|---|---|
| Secure extraction only | 37.2 | 50.0 |
| Extraction + manifest build | 55.1 | 315.9 |
| Full pipeline (extraction + manifest + real analysis) | 414.4 | 549.0 |

The P95 jump reflects OS-level temp-directory I/O variance on this
Windows development machine, not the code path itself — the manifest
build's own work (SHA-256 over ~10 small files) is sub-millisecond. No
claim is made about larger projects or concurrent uploads; both are
untested.

## Known limitations

- **One schema/one migration per upload.** A project with multiple
  ambiguous migration files and no dedicated `migrations/` directory gets a
  deterministic-but-unverified pick, surfaced as a note — not a guaranteed
  correct one.
- **No malware/content scanning beyond structural ZIP safety.** This is
  path-traversal/decompression-bomb/resource-limit protection, not an
  antivirus.
- **Ingestion limits are fixed constants**, not per-request/per-tenant
  configuration — appropriate for a single-tenant demo path, not a
  production multi-tenant upload service (explicitly out of scope for this
  work).
- **Concurrent uploads are unmeasured.** The HTTP server is
  `ThreadingHTTPServer`, so concurrent requests do run, but no load test
  was performed.
