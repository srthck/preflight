# DAY P0.4 — Universal Change Impact + Evidence Integrity

## Executive summary

P0.3 closed with one explicitly disclosed gap — convergence detection was unit-proven but not fixture-proven end-to-end — and one implicit assumption: that the semantic analyzer was repository-agnostic. Forensic inspection this turn found that assumption was **false**, and that the multi-target machinery P0.3 built could not actually be exercised by a real migration.

Three genuine defects were found and fixed, each proven by a failing-before/passing-after test on a repository unrelated to the canonical demo:

1. **Demo vocabulary leaked into every arbitrary repository's graph.** `semantic.py::_infer_api_class_name()` returned the literal strings `"ProfileAPI"` / `"UserService"` for *any* repository's HTTP call, and every database entity in every repository was labelled `service="demo-commerce-db"`. An unrelated inventory repository produced an entity called `pricing-engine.ProfileAPI` — a fabricated identity, and precisely the class of leak §24 asks to hunt.
2. **A multi-statement migration collapsed to a single change.** `parse_migration_sql()` used SQLGlot's single-statement `parse_one`, so `ALTER TABLE ... DROP COLUMN a; ALTER TABLE ... DROP COLUMN b;` produced **one** `UNSUPPORTED` change rather than two `DROP_COLUMN` changes. Every change after the first was invisible to impact analysis, which made P0.3's multi-target blast radius unreachable from real SQL input.
3. **Convergence was structurally unreachable.** Because of (2), and because the orchestrator only ever resolved `deployment_finding.schema_object` (one target), no real repository could produce two independent targets — which is exactly why P0.3 could not prove convergence end-to-end.

All three are now fixed and proven on `fixtures/fleet-ops`, a new fixture built in an unrelated domain (fleet/driver compliance) with different table names, column names, service names, and business purpose.

**Status: the P0.3-disclosed gap is closed.** Convergence is now proven end-to-end from real source files, live over HTTP, with adversarial tests proving it disappears when the underlying dependency is removed.

## Architecture changes

No new graph engine, no duplicated analyzer, no policy change. `decide()`'s weights and thresholds are untouched. The changes are:

| Change | File | Nature |
|---|---|---|
| Entity names derived from real URL host, not a fixed default | `semantic.py::_infer_api_class_name` | Correctness fix |
| Neutral `_DATABASE_SERVICE_LABEL` constant | `semantic.py` | Correctness fix |
| Every SQL statement parsed, not just the first | `schema.py::parse_migration_sql` + new `_changes_from_statement` | Correctness fix |
| All schema changes resolved to blast targets | `orchestration/pipeline.py::run_snapshot_comparison` | Evidence-selection |
| `schema_changes` / `blast_radius_targets` surfaced | `orchestration/models.py` | Response contract |
| Multi-change + convergence surfaces | `ChangeSetPanel.tsx`, `api.ts` | Minimal UI |

### The naming fix, precisely

The replacement rule is a deterministic transformation of evidence actually present in the source — the URL's own host component — with a small general acronym table (`api`, `db`, `id`, `url`, `http`, `sql`, ...):

- `http://compliance-api/v1/verify` → host `compliance-api` → `ComplianceAPI`
- `http://pricing-engine/v1/recalculate` → host `pricing-engine` → `PricingEngine`
- `http://profile-api/internal/profile/sync` → host `profile-api` → `ProfileAPI`

The canonical demo's entity IDs are therefore **byte-identical** after the fix (`profile-api.ProfileAPI`, `user-service.UserService`, `android-client.ProfileClient`) — not because they are special-cased, but because the canonical host genuinely *is* `profile-api`. Verified: both canonical scenarios still produce their exact prior decision hashes (`ebafcde445cb93a1…` DO_NOT_DEPLOY/100, `e76e6fe48aef10fb…` SAFE/9).

Database entities are labelled `service="database"`. A SQL string proves a table and column exist; it never proves what the database itself is called, so a neutral label is the honest answer rather than borrowing a fixture's name.

## Convergence proof (§6, §16)

`fixtures/fleet-ops` — real source files, parsed by the real Tree-sitter/SQLGlot analyzers, nothing hand-encoded in the orchestrator:

```
drivers.license_number --DB_READ--> dispatch-service.DispatchService --HTTP_CALL--> compliance-api.ComplianceAPI
drivers.medical_cert   --DB_READ--> audit-service.AuditService       --HTTP_CALL--> compliance-api.ComplianceAPI
```

A migration dropping both columns produces two structurally independent changes that converge on one downstream entity. Live output from the running server (`POST /api/analyze-change`):

```
decision: DO_NOT_DEPLOY 100
schema_changes: [('DROP_COLUMN', 'drivers.license_number'), ('DROP_COLUMN', 'drivers.medical_cert')]
blast_targets: ['drivers.license_number', 'drivers.medical_cert']
convergence: [('compliance-api.ComplianceAPI', ['drivers.license_number', 'drivers.medical_cert'])]
capabilities: {api_contract: ANALYZED, blast_radius: ANALYZED, database: ANALYZED, rollback: UNSAFE, source: ANALYZED}
demo leakage: []
```

The shared API appears **once** in `affected_entities` but retains **both** causal paths in `blast_radius.findings` — deduplicated in the aggregate, never deduplicated in the evidence (`test_shared_api_counted_once_but_retains_both_causal_paths`).

### The convergence is causal, not incidental

Three adversarial tests prove it is derived from the real graph rather than asserted:

- Drop only one column → `convergence == []`, but the shared API is still affected (one cause, not two).
- Delete `audit-service` entirely → `convergence == []`, and `medical_cert` stops being a target because it no longer has any reader.
- Use an additive `ADD COLUMN` migration → no targets, no convergence, `affected_count == 0`.

## Adversarial mutation results (§25)

| Mutation | Asserted consequence | Result |
|---|---|---|
| Rewrite `SELECT` to read a different column | target disappears, decision hash changes | PASS |
| Remove one consumer service | affected set strictly shrinks | PASS |
| Remove the HTTP call | shared API drops out of impact set, convergence empties | PASS |
| `DROP COLUMN` → `ADD COLUMN` | `DROP_COLUMN` finding disappears, risk drops | PASS |
| Add a second migration statement | ChangeSet hash and decision hash both change | PASS |
| **Edit README only** | ChangeSet hash changes, **decision hash does not** | PASS |
| Different extraction directory | identical decision hash | PASS |

The README test is the important one for §18: it proves *repository content identity* and *analysis identity* are genuinely separate hashes, not the same value under two names.

## Determinism

- `change_set_hash` / `diff_hash`: stable across file-creation order, independent extractions, and extraction directory (proven in `test_diffing.py`, `test_adversarial_mutations.py`, `test_snapshot_comparison.py`).
- `decision.deterministic_hash`: identical across independent runs of the same byte content; changes when and only when analyzed evidence changes.
- Repository content identity is independent of extraction path, temp directory, and file-creation order.
- ZIP-entry-order and filesystem-order independence are inherited unchanged from the P0.1/P0.2-proven `extracted_project()` boundary, reused verbatim rather than reimplemented.

## Security

Unchanged and not regressed: both archives in a comparison pass through the identical hardened `extracted_project()` boundary (path traversal, symlink, zip-bomb ratio, per-file and total size limits), and all 16 `test_archive_security.py` tests still pass. Direct grep confirms no `subprocess`, `os.system`, `eval`, `exec`, or `shell=True` anywhere in `diffing.py` or `run_snapshot_comparison`. Nothing uploaded is executed, installed, or built.

## Validation

Commands executed, all from `preflight-demo/`:

```
python -m pytest -q                          -> 464 passed
python -m ruff check src/ tests/ scripts/    -> All checks passed
python -m mypy --strict src/preflight        -> Success: no issues found in 42 source files
cd frontend && npx tsc --noEmit              -> clean
cd frontend && npx eslint app lib --max-warnings=0  -> clean
cd frontend && npx next build                -> compiled successfully
```

Test count: 464 (444 at P0.3 close, +20 this turn: 9 convergence, 7 adversarial mutation, 4 demo-leakage). Note that mypy caught a real variable-shadowing bug I introduced in the multi-target resolution loop (an `APIChange` assigned to a variable typed `SchemaChange`) — fixed before completion, not suppressed.

## Known limitations (disclosed, not hidden)

- **Structural source diffing (§11) was not implemented.** Changed source files are classified by domain and their dependency consequences are analyzed through the semantic graph, but PreFlight does not yet report "function X was removed" as a first-class change object. The forensics did not show this blocking any causal chain, and the mission's own instruction was to implement the smallest architectural change that closes the actual gap — the actual gap was multi-change parsing and demo leakage.
- **The evidence graph (§2) remains an implicit structure, not a materialized object.** The full chain (change → entity → edge → finding → risk feature → decision) is traceable through existing fields — `schema_changes`, `blast_radius_targets`, `blast_radius.findings[].path`, `decision_report.findings[].evidence`, `evidence_chain` — but there is no single `EvidenceGraph` node/edge document. Building one would be an integration model over data that already exists; it was not required to close the P0.3 gap and would have been new surface area rather than a correctness fix.
- **Config and deployment domains are still classified, not analyzed** (unchanged from P0.3). A changed `Dockerfile` is labelled `DEPLOYMENT` in the ChangeSet; no analyzer resolves its consumers.
- **The 15-repository matrix (§15) was not built.** Four structurally distinct repositories are now exercised (demo-commerce, fleet-ops, synthetic inventory, and the P0.2 no-evidence archives) plus the existing universal-ingestion fixtures. The remaining eleven were not built this turn.
- **Rollback still derives its OLD application snapshot from the OLD semantic graph**, which is genuine OLD/NEW evidence for the snapshot-pair path, but `run_project_analysis` (single upload) necessarily still compares a repository against itself — an inherent property of having only one snapshot, surfaced honestly as `UNKNOWN` rather than `SAFE`.
- **Performance (§20) was not benchmarked this turn.** No timing claims are made.

## Hostile review (§27)

Answered only where evidence exists; "not proven" is stated where it does not.

1. **One migration → multiple Change objects?** Yes — `test_migration_produces_two_independent_change_objects`.
2. **Multiple targets analyzed independently?** Yes — `blast_radius_targets` has two entries, `BlastRadiusEngine` called once per target.
3. **Two causes converge on one entity?** Yes — live output above.
4. **Convergence proven by an actual fixture?** Yes — `fixtures/fleet-ops`, real files, real parsers. **This closes the P0.3 gap.**
5. **Every affected entity traceable to a changed artifact?** Yes — via `schema_changes[].schema_object` → `blast_radius.findings[].path.nodes`.
6. **Every graph edge traceable to a source location?** Yes — unchanged `EdgeEvidence` (file, line, column, symbol, syntax_kind, matched_pattern, resolution_rule).
7–9. **Finding → evidence → risk feature → verdict traceable?** Yes — unchanged `evidence_chain` / `risk_features` / `policy_rules_triggered`.
10. **UI reconstructs the chain without inference?** The backend now supplies `schema_changes`, `blast_radius_targets`, and `convergence` explicitly, and the UI renders them; no frontend component infers analyzer status (P0.2 invariant, still enforced).
11–13. **Missing evidence stays UNKNOWN; zero ≠ unavailable; unsupported stays UNSUPPORTED?** Yes — unchanged capability matrix, all P0.2 regression tests still pass.
14. **One source statement changes the graph?** Yes — `test_changing_a_selected_column_changes_the_graph_and_the_decision`.
15. **One migration statement changes the ChangeSet?** Yes — `test_adding_a_statement_to_a_migration_changes_the_changeset`.
16. **API contract change changes API findings?** Yes — unchanged P0.3 behaviour, `api_contract` reports ANALYZED on fleet-ops.
17. **Removing a dependency reduces blast radius?** Yes — `test_removing_a_consumer_reduces_the_blast_radius`.
18. **Removing a convergence path removes convergence?** Yes — two separate tests.
19. **Multiple paths preserved, not overwritten?** Yes — `test_shared_api_counted_once_but_retains_both_causal_paths`.
20. **Duplicates deterministically merged?** Yes — distinct-entity `affected_count`, sorted convergence output.
21–22. **Hashes independent of ordering/paths/filenames?** Yes — determinism tests above.
23. **Arbitrary repositories enter the same pipeline?** Yes — fleet-ops and the synthetic inventory repo both run the identical `run_snapshot_comparison` / `run_project_analysis`.
24. **Demo-specific branching in production code?** **No longer** — this turn removed the only two real instances. Locked by `test_no_demo_leakage.py`.
25. **Malformed input crashes the analysis?** No — unchanged PARSE_ERROR/UNAVAILABLE handling, P0.2 tests still pass.
26. **Uploaded code can execute?** No — verified by grep, no subprocess/eval/exec in any new code.
27. **Rollback uses distinct OLD/NEW evidence?** Yes for snapshot pairs; honestly limited for single uploads (see limitations).
28. **System can say what it could not analyze?** Yes — capability matrix plus `resolved_as_blast_target: false` for changes with no graph target.
29. **A judge can inspect one causal chain?** Yes — the fleet-ops chain above renders in the UI.
30. **Every visible claim backed by an artifact?** Yes for everything asserted in this report; claims not backed by evidence are listed under limitations rather than asserted.

## Final status

The specific gap P0.3 disclosed is **closed**, and two deeper defects that would have undermined any convergence claim were found and fixed on the way. Sections 11 (structural source diffing), 15 (full repository matrix), and 20 (benchmarks) of the P0.4 brief are **not complete** and are listed above rather than glossed. P0.4 is therefore reported as *gap-closed and defect-fixed*, not as *fully complete against every section of the brief*.
