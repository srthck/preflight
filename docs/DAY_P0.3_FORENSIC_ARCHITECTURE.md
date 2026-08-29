# DAY P0.3 — Forensic Architecture Trace

Read before any P0.3 code was written: `orchestration/pipeline.py`, `orchestration/models.py`, `ingestion/discovery.py`, `ingestion/manifest.py`, `ingestion/models.py`, `ingestion/archive.py`, `decision.py`, `domain/blast_radius.py`, `scripts/preflight_api.py`. This document answers the ten required questions with file:line citations, not inference.

## Pipeline trace (current, single-repository)

```
ZIP bytes
  -> ingestion/archive.py::extracted_project()      (secure extraction, temp dir)
  -> ingestion/manifest.py::build_manifest()         (per-file SHA-256, classification, hash)
  -> ingestion/discovery.py::find_schema_and_migration / find_api_contract / find_semantic_files
  -> orchestration/pipeline.py::run_project_analysis()
       -> _execute_pipeline()
            -> SemanticAnalyzer().analyze()          (Tree-sitter, one PreFlightGraph)
            -> DeploymentAnalyzer(graph).analyze()   (SQLGlot, one DeploymentFinding)
            -> BlastRadiusEngine().analyze()          (single target, one BlastRadiusReport)
            -> analyze_api_contract() / parse_openapi_document()
            -> analyze_rollback()
            -> decide()                               (single authority on risk/verdict)
            -> explain()
  -> AnalysisRunResult.to_response_payload()
  -> scripts/preflight_api.py Handler._handle_analyze_project()
  -> frontend/lib/api.ts -> React components
```

## 1. Where repository identity is created

`ingestion/manifest.py::build_manifest()` (line 19) walks the extracted tree and produces `ProjectManifest.manifest_hash` (line 57, `with_hash()`): a SHA-256 over the sorted, canonical-JSON list of every file's own path/size/sha256/classification. This is the closest thing to "repository identity" that exists today. It is **not** a general content-addressed repository hash independent of presentation fields — it includes `language` and `classification`, which are derived, not raw content. It is computed once per extracted tree; there is no notion of "the same repository analyzed twice" beyond re-running `build_manifest` and comparing hashes.

## 2. Where files are classified

`ingestion/discovery.py::classify()` (line 137): a pure function, `(path, root) -> (classification, ignored_reason)`, returning one of `semantic | migration_candidate | api_contract | unsupported | ignored | other`. Called once by `build_manifest` (manifest.py:32) for the presentation-facing manifest, and independently re-derived by `find_semantic_files`/`find_api_contract`/`find_schema_and_migration` for the pipeline's actual input selection — both paths apply the identical `IGNORED_DIR_NAMES`/suffix tables, so they cannot diverge, but they are two call sites, not one shared classification pass reused by both.

## 3. Where semantic targets are selected

`SemanticAnalyzer().analyze(project_root, files=semantic_files)` (pipeline.py:182) — `semantic_files` comes from `discovery.find_semantic_files()`, every `.py`/`.kt` file under the root not in an ignored directory. There is no concept of "target" at this stage; the whole file set is parsed into one `PreFlightGraph`.

## 4. Where deployment changes are represented

`schema.py::DeploymentFinding`, produced by `DeploymentAnalyzer(graph=graph).analyze(migration_sql)` (pipeline.py:194). A **single** migration SQL string in, a **single** `DeploymentFinding` out — there is no concept of multiple simultaneous schema changes; `parse_migration_sql` and `DeploymentAnalyzer` are built around one migration file representing one change.

## 5. Where migration targets are selected

`ingestion/discovery.py::find_schema_and_migration()` (line 198): deterministic, documented tie-breaking (literal `schema.sql` name; then a `*migration*`-named directory's lexicographically-last file; then the lexicographically-last remaining `.sql` file, with a note recorded when the choice was ambiguous). This picks **one** file. Multiple real migrations in one upload are invisible to the current pipeline beyond that single selected file.

## 6. Where blast-radius targets originate

`pipeline.py:195`, `changed_entity = deployment_finding.schema_object or "UNKNOWN"` — the **single** schema object the one selected migration touched. `BlastRadiusRequest.target: str` (domain/blast_radius.py:25) is a scalar field; `BlastRadiusEngine.analyze(graph, request)` (pipeline.py:219) is called exactly once per pipeline run. There is no multi-target call site and no aggregation logic anywhere in the current tree — this is the single largest gap versus the P0.3 mission's "support multiple changed targets, aggregate deterministically" requirement.

## 7. Where rollback inputs originate

`pipeline.py::_derive_application_snapshot()` (line 462) builds the **OLD** application's dependency snapshot from the semantic graph's own `DB_READ`/`API_CONSUMES` edges — i.e. today "OLD" and "NEW" are not two distinct uploaded repositories; they are both derived from the **single** analyzed snapshot (`old_schema`/`new_schema` from `_schema_snapshots()`, line 438, come from applying the one migration to the one schema.sql — a *within-repository* before/after, not a *between-repository* before/after). `analyze_rollback()` (pipeline.py:253) receives `old_application=old_application` and `new_api=old_api` (pipeline.py:259 — note `new_api` is literally set to `old_api`, since only one API contract file exists in a single upload). This confirms there is currently no `SNAPSHOT_PAIR` concept in the codebase at all; P0.3's `ChangeSet` is new domain territory, not a refactor of existing rollback plumbing.

## 8. Where unavailable evidence becomes UNKNOWN

`unavailable: list[str]` accumulated through `_execute_pipeline` (pipeline.py:179, appended at lines 185, 192, 216, 237, 243, 248) and passed as `DecisionRequest.unavailable_components` (pipeline.py:281). `decision.py::normalize_findings()` (line 266) turns every entry into a `rule_id="ANALYZER-UNAVAILABLE"`, `confidence=0.0` finding in `FindingCategory.DYNAMIC_REFERENCE`. `decide()` (decision.py:285) is the **single** authority that reads these findings and resolves the final `DecisionReport.decision` to `UNKNOWN` when blocking evidence is missing — this mechanism is reused, not rebuilt, for P0.3.

## 9. Where deterministic hashes are generated

Three independent hash sites, none unified: `ProjectManifest.manifest_hash` (manifest.py:57, hashes manifest presentation fields), `graph.serialization::canonical_sha256(self.graph)` (orchestration/models.py:101, hashes the semantic graph), `DecisionReport.deterministic_hash` (decision.py, hashes the final decision — the one the frontend surfaces and the one existing determinism tests assert on). P0.3 needs a **fourth**, new hash: a repository/`ChangeSet`-scoped hash independent of any of these three, per the mission's explicit Phase 14/15 requirement to separate "repository content hash" from "analysis/decision hash."

## 10. Where demo fixtures could still leak into arbitrary uploads

Re-confirmed (same method as the DAY_P0.2 audit): `pipeline.py`'s `SCENARIOS` dict (lines 65-80) is read only by `run_analysis()` (line 83), never by `run_project_analysis()` (line 114) or `_execute_pipeline()` itself — `_execute_pipeline` takes already-resolved `Path | None` arguments and contains no scenario-name branch. `fixtures/loader.py`'s `build_demo_commerce_graph()` and its `ENTITY_*` constants are not imported by `orchestration/` at all (confirmed by import graph — `pipeline.py`'s import block, lines 37-61, has no reference to `preflight.fixtures`). No leakage path exists into the upload code path today; this stays true for P0.3 as long as the new snapshot-comparison entry point is built as a sibling to `run_project_analysis`, sharing `_execute_pipeline`/`decide()` rather than the `SCENARIOS` registry.

## The gap this turn closes

Everything above is single-repository. The mission's core correction — `ZIP -> repository analysis` must become `INPUTS -> CHANGE MODEL -> EVIDENCE MODEL -> SURVIVAL ANALYSIS` — requires a genuinely new domain object (`ChangeSet`) and a genuinely new comparator (`RepositoryDiff`) that do not exist in any form today, plus multi-target blast-radius aggregation that also does not exist today (§6). Everything else the mission asks for (evidence coverage, decision semantics, risk weights, `unavailable_components`) already exists and is reused, not rebuilt.
