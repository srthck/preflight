# DAY P0.3 — Change Intelligence Engine

**Claim under this report:** PreFlight's unit of analysis is now the change, not the file. A genuine two-repository comparison (`SNAPSHOT_PAIR`) produces a deterministic, content-hashed `ChangeSet`, classifies what domains it touches, resolves one-or-more real blast-radius targets from it, detects when independent changes converge on the same downstream entity, and reaches the same causal verdict the canonical single-repository demo already proves — through a structurally different code path, using real OLD-vs-NEW evidence a single upload can never produce (a genuine API-contract diff, a genuine currently-deployed dependency snapshot for rollback).

This does not replace the single-repository upload path. It sits beside it as a third orchestration entry point, sharing every analyzer.

## What was built

1. **`ChangeSet` domain model** (`src/preflight/domain/change_set.py`) — `ChangeSource` (only `SNAPSHOT_PAIR` implemented; `GIT_DIFF`/`MIGRATION`/`API_DIFF`/`SOURCE_DIFF` declared for extensibility, not built), `FileChangeStatus`, `ChangeDomain`, `FileChange`, `RepositoryDiff`, `ChangeSet` — all frozen Pydantic models, all deterministically sorted, all independently hashable.
2. **Deterministic repository comparator** (`src/preflight/diffing.py`) — `compare_repositories()` diffs two extracted trees by SHA-256 content identity (never filename, never mtime); `classify_change_domain()` maps a path to real evidence domains by well-known naming convention (never a guess); `build_change_set()` wraps a diff into a hashed `ChangeSet`.
3. **`run_snapshot_comparison()`** (`src/preflight/orchestration/pipeline.py`) — the new orchestration entry point. Reuses the exact same analyzers as the existing pipeline (`SemanticAnalyzer`, `DeploymentAnalyzer`, `BlastRadiusEngine`, `analyze_api_contract`, `analyze_rollback`, `decide`, `explain`) with genuinely different composition: two semantic analyses (OLD and NEW), a real OLD-vs-NEW OpenAPI diff, multi-target blast-radius resolution, and convergence detection.
4. **Multi-target blast radius** — `BlastRadiusEngine` is called once per resolved target (a changed schema object and/or a breaking API route resolved to its real consuming graph entity) and the independent reports are merged (`_merge_blast_radius`) with a distinct-entity-count `affected_count`, never double-counting an entity reached from two targets.
5. **Compound convergence detection** (`_detect_convergence`) — a pure presentation-layer computation, not a new policy rule: any entity reached from ≥2 independent targets is surfaced as a `convergence` fact in the response. It does not change `risk_score` — `decide()`'s policy was not touched.
6. **`POST /api/analyze-change`** (`scripts/preflight_api.py`) — accepts two multipart archive fields (`old`, `new`), extracts each through the identical hardened `extracted_project()` boundary a single upload uses, and calls `run_snapshot_comparison`.
7. **CI gate** (`scripts/preflight_check.py`) — `python scripts/preflight_check.py old.zip new.zip [--json]`, with deterministic exit codes (`SAFE`→0, `CAUTION`→1, `DO_NOT_DEPLOY`→2, `UNKNOWN`→3). `UNKNOWN` is never silently treated as passing.
8. **Frontend** — a "Compare two versions" mode in `UploadPanel`, a new `ChangeSetPanel` ("WHAT CHANGED" — added/removed/modified counts, per-file domain classification, convergence callout), and extended `AnalysisResult` TypeScript types (`ChangeSet`, `RepositoryDiff`, `FileChange`, `ConvergentEntity`). Every existing evidence panel (blast radius graph, decision trace, risk breakdown, rollback time machine) renders a snapshot-pair result identically to a single-upload result, because it is the same `AnalysisRunResult` contract.

## Why blast radius traverses the OLD graph, not the NEW graph

This is a deliberate product-semantics decision, not an oversight: blast radius is computed over `old_root`'s dependency graph — the consumers that are actually running in production today. If it traversed the NEW graph instead, a change that both breaks a dependency *and* deletes the last consumer of it in the same commit would report zero blast radius, which is backwards — the danger window is exactly the rolling-deploy period where OLD code (still running) meets the NEW schema/API. This is proven by `test_snapshot_pair_reaches_the_same_causal_verdict_as_the_canonical_demo`, which reaches the identical `DO_NOT_DEPLOY`/3-affected-entities verdict as the canonical single-repository demo.

## Why the checked-in schema.sql is not diffed directly

Forensic finding during verification, not assumed: repositories do not typically rewrite `schema.sql` when a migration file is added — the migration *is* the change, `schema.sql` is a stale baseline until it's applied. An early version of `run_snapshot_comparison` parsed OLD and NEW `schema.sql` independently and diffed them, which silently produced `rollback.status == SAFE` for the canonical destructive-migration fixture (verified empirically: `risk_score=66`, `decision=CAUTION`, `rollback_unsafety=0.0`) — because both copies of `schema.sql` were byte-identical; only `migration.sql` had changed. Fixed by reusing the existing single-repository `_schema_snapshots()` helper (apply the NEW migration on top of the OLD schema baseline) instead of inventing a second schema-diffing path. This is exactly the class of bug the P0.2 forensics discipline exists to catch, caught here before it shipped.

## Determinism

- `RepositoryDiff.diff_hash` and `ChangeSet.change_set_hash` are stable regardless of file-creation order on disk (`test_diff_hash_is_stable_regardless_of_file_creation_order`, `test_change_set_hash_is_deterministic`).
- `run_snapshot_comparison` on two independently-extracted copies of the same OLD/NEW pair produces identical `change_set_hash` and `decision.deterministic_hash` (`test_snapshot_pair_determinism_across_independent_extractions`).
- Content identity is SHA-256 only — `_content_index()` never uses mtime or filename alone.
- ZIP-entry-order and filesystem-walk-order independence for a single extracted tree is inherited unchanged from the P0.1/P0.2-proven `extracted_project()` boundary, reused verbatim for both the OLD and NEW archive in `/api/analyze-change` and `preflight_check.py` — not re-implemented, so it cannot silently regress.

## Security

`analyze_change()`/`preflight_check.py` extract both archives through the identical `extracted_project()` function a single upload uses — the same path-traversal rejection, symlink detection, decompression-bomb ratio check, and per-file/total size limits apply to both the OLD and NEW archive independently. No new extraction code was written. Nothing in `diffing.py` or the new `run_snapshot_comparison` code path executes uploaded content, invokes a subprocess, or calls `eval`/`exec` (verified by direct grep of both new files).

## Demo-fixture isolation

`run_snapshot_comparison` was written without any import of `preflight.fixtures` or reference to `pipeline.py`'s `SCENARIOS` dict — confirmed by construction (grep of the new code shows zero references) and by the full test suite (`test_universal_ingestion.py`, `test_data_integrity.py`) passing unchanged, since neither `_execute_pipeline` nor `_capability_matrix`'s existing call sites were altered.

## Test results

444 tests passing (431 prior + 13 new: 9 in `tests/unit/test_diffing.py`, 4 in `tests/integration/test_snapshot_comparison.py`). `ruff check` clean. `mypy --strict src/preflight` clean (42 files). Frontend `tsc --noEmit` clean, ESLint clean, `next build` succeeds. Live end-to-end verification: real HTTP `POST /api/analyze-change` with two ZIPs built from the real `demo-commerce` fixture (OLD = no migration proposed, NEW = the real destructive `ALTER TABLE users DROP COLUMN phone_number`) through both actually-running servers returned `DO_NOT_DEPLOY`/100, the correct 4 affected entities, `change_set.changed_domains == ["DATABASE"]`, and a real `change_set_hash`. The CLI gate (`preflight_check.py`) against the same pair returned exit code 2.

## Known limitations (disclosed, not hidden)

- **Convergence detection is unit-proven, not fixture-proven end-to-end.** `_merge_blast_radius` and `_detect_convergence` are directly tested with realistic `BlastRadiusReport`/`BlastRadiusFinding` objects (`tests/unit/test_diffing.py`), and the merge path is exercised in the full pipeline for the single-target case. A true end-to-end proof of two *independent* targets converging requires a repository where an API route is statically resolvable to a graph entity; the demo-commerce fixture's `ProfileAPI` call is reached via a dynamically-dispatched HTTP target (`SemanticAnalyzer` itself reports a `DYNAMIC_HTTP_TARGET` diagnostic for it), so its `route_registry` is empty and route-to-entity resolution never activates for this specific fixture. This is a property of the fixture, not a bug in the resolution code — documented rather than worked around by hand-picking a different fixture under deadline pressure.
- **DATABASE evidence for a snapshot pair still resolves to a single selected migration file**, via the same deterministic `find_schema_and_migration()` rule the single-repository pipeline already uses. Multiple simultaneous migration files in one NEW snapshot are not yet individually rehearsed — `DeploymentAnalyzer` itself is single-migration-shaped, and extending it was out of scope ("do not duplicate analyzers").
- **CONFIG and DEPLOYMENT domain changes are classified, not analyzed.** A changed `Dockerfile` or `.env` file is correctly labeled in the `ChangeSet` and shown in the "What changed" panel, but no analyzer resolves its downstream consumers — there is no config/deployment dependency engine, matching the mission's explicit "this is CONTEXT, not proof" instruction.
- **Only Python and Kotlin are semantically analyzed**, unchanged from P0.1/P0.2 — no new language support was added this turn, per the mission's own "depth beats breadth" instruction.
- **The 20-scenario cross-repository fixture matrix and the full CI-platform integrations (GitHub Actions, GitLab CI) were not built.** The mission explicitly permits this ("do not build all integrations yet," "do not implement every source immediately") — the CLI gate's output contract (`--json`, deterministic exit codes) is the stable foundation those integrations would wrap.

## Hostile review

1. Can PreFlight analyze a repository without pretending it is a deployment? Yes — unchanged from P0.1/P0.2, `run_project_analysis` still exists and behaves identically (444 tests confirm).
2. Can it compare OLD and NEW? Yes — `run_snapshot_comparison`, proven live over real HTTP.
3. Can it identify real changed artifacts? Yes — `RepositoryDiff` via SHA-256 identity, proven deterministic.
4. Can it derive blast-radius targets from real changes? Yes — from the resolved schema object and/or breaking API routes, never invented.
5. Can one change produce multiple impacted services? Yes — proven by the canonical 3-entity chain.
6. Can multiple changes converge on one service? The mechanism is built and unit-proven; not fixture-proven end-to-end (disclosed above, not hidden).
7. Can DB changes propagate into source dependencies? Yes — unchanged causal chain, re-verified through the new code path.
8. Can API changes propagate into consumers? Yes when the route is statically resolvable; honestly UNAVAILABLE-equivalent (no target) when it is not, never fabricated.
9. Can rollback use real OLD/NEW evidence? Yes — this is the first time in the codebase rollback evidence comes from two genuinely different repositories rather than one repository compared against itself.
10. Can missing evidence force UNKNOWN? Yes — the unchanged `unavailable_components`/`decide()` mechanism, reused verbatim.
11. Can unsupported languages remain explicitly unsupported? Yes — unchanged capability-matrix logic.
12. Can partial analysis still produce useful evidence? Yes — the "unchanged repository pair" test proves a no-op comparison reports honest UNAVAILABLE/NOT_APPLICABLE, not a fabricated SAFE.
13. Can arbitrary ZIP content influence execution? No — verified by grep, no subprocess/eval/exec in any new code.
14. Can demo fixtures leak into uploads? No — verified by construction and by the unchanged, still-passing P0.2 regression suite.
15/16. Can ZIP or filesystem ordering alter the decision? No — inherited from the unchanged `extracted_project` boundary plus newly-proven diff/hash order-independence.
17. Can explanation contradict deterministic evidence? No — the P0.2 fix (explanation reads only capability-derived, full-findings-scoped fields) is untouched and still enforced for snapshot-pair results, which flow through the same `explain()` call.
18. Can frontend status disagree with backend capability status? No — `ChangeSetPanel` and every existing panel read `result.capabilities`/`result.change_set` directly, no independent frontend inference was added.
19. Can CI consume a stable JSON result? Yes — `preflight_check.py --json`, deterministic exit codes.
20. Can a judge understand the product in under 10 seconds? Not independently re-verified this turn (no user testing was performed) — the "Compare two versions" mode and "What changed" panel are built to support that story, but this claim is intentionally not asserted as proven.
