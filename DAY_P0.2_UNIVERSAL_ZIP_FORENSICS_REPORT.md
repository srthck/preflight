# DAY P0.2 — Universal ZIP Forensics & Data-Integrity Audit

**Claim under audit:** PreFlight accepts arbitrary repository archives and deterministically discovers what evidence they contain, running only the analyzers that evidence supports — and every number displayed anywhere in the UI is traceable to exactly one authoritative computation, with no analyzer's silence ever misread as a "zero" result by another part of the system.

This is not "ZIP upload works." This is a forensic account of a real contradiction, its root cause, the fix, and the proof that the fix is both correct and non-regressive.

---

## 1. The reported contradiction, reproduced

A real e-commerce ZIP (`E - Commerce Platform (1).zip`) with no Python/Kotlin source, no SQL migration, and no OpenAPI contract produced, simultaneously:

| Panel | Displayed value |
|---|---|
| Project understanding | 0/5 analyzers ran |
| Source / semantic graph | 5 files, unsupported languages; 0 entities, 0 edges |
| Blast radius | NOT APPLICABLE |
| AI explanation | "Blast radius: 3 affected entities." |
| Analysis coverage | "3 unresolved references" |
| Database rehearsal | PARSE_ERROR |
| Decision | UNKNOWN (9/100) |

Three independent panels disagreed about whether anything downstream had actually been analyzed, and a repository with zero usable evidence was still spending 9 points of weighted risk score. That is a correctness bug in a tool whose entire value proposition is "trust what this says," not a cosmetic one.

## 2. Root cause (forensic trace, not guesswork)

Two independent defects, both upstream of the UI, in `src/preflight`:

**Defect A — sentinel strings leaking into `affected_entities`.**
`DecisionReport.affected_entities` is a set built by unioning every finding's `affected_entities` tuple across all categories. Two producers were putting *placeholder/description strings* into that tuple instead of leaving it empty when the referenced entity didn't exist:

- `decision.py::normalize_findings()` — a `DeploymentFinding` with `change == "PARSE_ERROR"` carries `schema_object == "UNKNOWN"` (a fixed sentinel from `DeploymentAnalyzer`, not a real schema object). The old code unconditionally wrote `(deployment_finding.schema_object,)`, so `"UNKNOWN"` was counted as a real affected entity.
- `decision.py::_rollback_normalized()` — when `rollback_truth.py::_unknown()` fabricates a finding for genuinely missing evidence, it reuses the `entity` field to *describe what's missing* (e.g. `"old_schema/new_schema"`, `"old_api/new_api"`), not to name a real graph node. The old code unconditionally wrote `(item.entity,)` regardless of `item.missing_evidence`.

Union three such placeholders (`UNKNOWN`, `old_schema/new_schema`, `old_api/new_api`) across categories and `len(affected_entities) == 3` — which is exactly the "3" that reached both the coverage panel and, indirectly, the explanation layer.

**Defect B — the explanation layer read a mislabeled cross-category aggregate.**
`DeterministicExplanationProvider.explain()` built its blast-radius sentence from `input.risk_features.affected_entity_count` — a decision-wide count spanning blast-radius, deployment, *and* rollback categories — and labeled it "blast radius." This was wrong even before Defect A: on the canonical working fixture it was already off by one (it silently included `users.phone_number` a second time via the deployment/rollback categories on top of the real blast-radius set). Defect A just made the mislabeling visible as a contradiction because it produced entity IDs on a project where the *real* blast-radius analyzer never ran at all.

**Defect C — found during verification, not in the original report.**
While confirming the fix, direct measurement of `risk_features.deployment_severity` showed `DeploymentAnalyzer.analyze("")` (called whenever no migration file exists, so the input is an empty string) returns the *same* MEDIUM-severity, 0.5-confidence `PARSE_ERROR` finding shape as a genuinely present-but-malformed SQL file. That finding was flowing into `decide()` unconditionally, so a repository with **zero** migration evidence was contributing real weighted risk — the entire 9/100 in the reported case came from evidence that never existed. This is the same class of bug as Defect A (treating "absent" as "present but bad") one layer up the pipeline, and was fixed under the same principle even though the user's report didn't call it out by number — the forensics proved it was wrong, per the standing instruction to fix only what forensics justify.

## 3. What was fixed (and, explicitly, what was not touched)

`decide()`'s weights, thresholds, and policy logic in `decision.py` were **not modified**. Every change is either (a) a guard on data already present on the domain objects, gated by fields those objects already expose, or (b) using the existing `unavailable_components` signal-propagation mechanism that `decide()` already understood before this turn.

- `decision.py::normalize_findings()` — `affected_entities=()` when `schema_object == "UNKNOWN"`, else `(schema_object,)`.
- `decision.py::_rollback_normalized()` — `affected_entities=()` when `item.missing_evidence`, else `(item.entity,)`.
- `orchestration/pipeline.py` — when `migration_path is None`, the deployment finding is **excluded** from `DecisionRequest.deployment_findings` (so it can't spend risk for absent evidence), while `"deployment_rehearsal"` is still appended to `unavailable_components` so `decide()` reaches UNKNOWN through the mechanism it already had. A genuinely present-but-malformed migration still goes through `deployment_findings` and still contributes real severity — verified explicitly (§14).
- `orchestration/pipeline.py` — blast radius is now driven by an explicit `blast_radius_analyzed = has_real_target and graph.node_count > 0` boolean computed once and threaded through both the decision path and the capability-matrix presentation, replacing implicit re-derivation in two places.
- `orchestration/pipeline.py` — API contract parsing wrapped in `try/except` over `(yaml.YAMLError, json.JSONDecodeError, ValueError, KeyError, TypeError)`, setting an explicit `api_contract_parse_error` flag instead of letting a malformed contract silently look identical to a missing one.
- `explanation.py` — `ExplanationInput` gained `blast_radius_available: bool` and `blast_radius_affected_count: int`, computed in `AIContextSanitizer.sanitize()` from the **full** `report.findings` list (category-filtered to `BLAST_RADIUS` only), not the 5-item-capped `top_findings` used elsewhere for AI context economy. `_blast_radius_summary()` renders from these two fields only, never from the cross-category `risk_features.affected_entity_count`.
- Four frontend components (`SchemaRehearsal`, `CoverageStatus`, `DecisionTrace`, `RiskBreakdown`) were changed to read `result.capabilities.*.status` as the single source of truth for "did this analyzer run," instead of independently inferring it from raw finding shapes — this is what makes the contradiction structurally impossible to reintroduce, not just fixed for this one case.

## 4. Data-flow trace — one authoritative value per metric

| Displayed metric | Source of truth | Fallback when unavailable | Frontend consumer |
|---|---|---|---|
| Affected entities | `DecisionReport.affected_entities` (union of per-finding `affected_entities`, sentinel-guarded at both producers) | `()` | `RiskBreakdown`, coverage panel |
| Blast radius count | `blast_radius.summary.affected_count` (only computed when `blast_radius_analyzed`) | `0` via `_empty_blast_radius()` | `BlastRadiusGraph`, `DecisionTrace` |
| Blast radius capability | `capabilities.blast_radius.status` (`ANALYZED` / `UNAVAILABLE` / `NOT_APPLICABLE`) | n/a — always set | `CapabilityMatrix`, `RiskBreakdown` (gates `scored`), `DecisionTrace` |
| Risk score | `DecisionReport.risk_score` from `decide()` | n/a | `CommandCenter`, `RiskBreakdown` |
| Decision | `DecisionReport.decision` from `decide()` | n/a | `CommandCenter` |
| Unresolved/unavailable components | `DecisionReport.unavailable_components` len | n/a | `CoverageStatus` (relabeled from "unresolved references") |
| Analyzer availability (per-analyzer) | `AnalysisRunResult.capabilities` dict, built once by `_capability_matrix()` | n/a | every panel |
| Deployment/database status | `capabilities.database.status` (`ANALYZED`/`UNAVAILABLE`/`PARSE_ERROR`) | n/a | `SchemaRehearsal`, `DecisionTrace` |
| API contract status | `capabilities.api_contract.status` (adds `PARSE_ERROR`) | n/a | `ApiContractPanel`, `DecisionTrace` |
| Rollback status | `capabilities.rollback.status` (`SAFE`/`CAUTION`/`UNSAFE`/`UNKNOWN`) | n/a | `RollbackTimeMachine`, `DecisionTrace` |
| Semantic entity/edge count | `result.graph.entities.length` / `.edges.length` | `0` when semantic analysis didn't run | `DecisionTrace`, `CapabilityMatrix` |
| Repository file count | `ProjectManifest` (built once by `build_manifest()` during discovery) | n/a | `ProjectManifestPanel` |
| AI blast-radius sentence | `ExplanationInput.blast_radius_available` / `.blast_radius_affected_count`, computed from full `findings` list, category-scoped | grounded "could not be established" sentence | `AiExplanation` |

Every row has exactly one producer. No panel recomputes a metric another panel already owns.

## 5. Demo-data leakage audit (Phase 2)

```
grep -rn "demo-commerce|killer_report|build_demo_commerce_graph|users.phone_number|ProfileAPI|UserService|ProfileClient|DROP_COLUMN|ADD_COLUMN" src/ scripts/ frontend/app frontend/lib
```

Result: `killer_report` — **zero matches anywhere in the repository** (removed in Turn 1). Every other match falls into one of:
- The fixture-scenario code path only: `pipeline.py`'s `SCENARIOS` dict (used exclusively by `run_analysis()`, the `/api/analyze` endpoint for the canned demo scenarios — never by `run_project_analysis()`), `fixtures/loader.py`, `scripts/*.py` (dev/debug scripts, not imported by the API).
- Domain-model docstrings/examples (`entities.py`, `enums.py`, `traversal.py`) — illustrative comments, not executable logic.
- Generic SQL-dialect enum members (`ADD_COLUMN`/`DROP_COLUMN` in `schema.py`, `decision.py`, `rollback_truth.py`) — these are schema-change *kinds* that apply to any SQL, not demo-specific strings.
- `frontend/lib/api.ts` — the two hardcoded scenario IDs used only by the "Try the canonical scenario" button, structurally separate from `analyzeProjectUpload()`.

A second check confirmed **no scenario-name conditionals** (`if scenario == "..."`) exist anywhere in `orchestration/` or `scripts/preflight_api.py` — the orchestration code has no branch that behaves differently because it recognizes "demo-commerce." `run_project_analysis()` and `run_analysis()` both terminate in the same `_execute_pipeline()`; the only difference is which files discovery finds versus which paths a `ScenarioConfig` hardcodes for the canned demo.

## 6. Live end-to-end verification (real ZIP, both servers running)

Backend (`scripts/preflight_api.py`, port 8000) and frontend (`next dev`, port 3000) were both restarted clean, then the actual `E - Commerce Platform (1).zip` was posted to `/api/analyze-project` via real HTTP multipart:

```
decision: UNKNOWN 0
affected_entities: []
blast_radius_summary: Blast radius could not be established because required evidence was unavailable.
capabilities: {'api_contract': 'UNAVAILABLE', 'blast_radius': 'UNAVAILABLE', 'database': 'UNAVAILABLE', 'rollback': 'UNKNOWN', 'source': 'UNSUPPORTED'}
```

Every field agrees: nothing ran, nothing is claimed to have run, the risk score reflects zero spent evidence (not a phantom 9/100), and the explanation text is grounded in — not independent of — the capability matrix.

## 7. Regression proof — canonical scenario unaffected

`test_canonical_destructive_scenario_blast_radius_is_still_consistent` loads the real `destructive-release.zip` fixture (genuine 3-entity blast radius) and asserts the fix did not perturb real evidence: `affected_count == 3`, `capabilities.blast_radius.status == "ANALYZED"`, and the explanation summary contains `"3"` and never says "could not be established." The full canonical demo-commerce scenario's `deterministic_hash` was diffed against pre-fix output and is byte-identical — the fix touches only code paths that fire on *absent* evidence, never on present evidence.

## 8. New regression tests (`tests/integration/test_data_integrity.py`)

Six tests, all passing, each locking in one specific claim from this audit:

1. `test_no_evidence_project_never_shows_phantom_affected_entities` — reproduces the exact reported contradiction with a synthetic zero-evidence ZIP; asserts `blast_radius.summary.affected_count == 0`, capability status `!= ANALYZED`, `affected_entities == []`, no sentinel string present, and the explanation text is grounded.
2. `test_deployment_placeholder_schema_object_is_never_an_affected_entity` — unit-level proof that a `PARSE_ERROR` deployment finding (`schema_object == "UNKNOWN"`) never contributes to `affected_entities`, independent of any ZIP/discovery machinery.
3. `test_rollback_missing_evidence_entity_is_never_an_affected_entity` — same, for the rollback `_unknown()` sentinel path.
4. `test_missing_migration_file_is_unavailable_not_just_parse_error` — proves Defect C's fix: `deployment_severity == 0.0` and `"deployment_rehearsal" in unavailable_components` when no SQL file exists at all, even though the raw analyzer output is still `PARSE_ERROR`.
5. `test_present_but_malformed_migration_still_contributes_real_risk` — the inverse proof: a genuinely present, broken migration still produces `deployment_severity > 0.0` and is *not* marked unavailable — the fix narrows correctly, it doesn't over-suppress.
6. `test_canonical_destructive_scenario_blast_radius_is_still_consistent` — the non-regression anchor from §7.

## 9. Full validation gate

- `pytest` — 431 tests passing (425 prior + 6 new), 0 failures.
- `ruff check` — clean.
- `mypy --strict` — clean (`yaml` import tagged `# type: ignore[import-untyped]` matching the existing convention in `api_contract.py`).
- Frontend `tsc --noEmit` — clean.
- Frontend `eslint` — clean.
- Frontend `next build` — succeeds.
- Backend smoke (`scripts/smoke.py`), API smoke (`scripts/api_smoke.py`) — pass.
- Archive security tests, repository discovery tests, universal ingestion tests, determinism tests — all pass (one assertion in `test_universal_ingestion.py` updated: a frontend-only static site now correctly reports `capabilities.blast_radius.status == "UNAVAILABLE"` rather than `NOT_APPLICABLE`, because "semantic analysis never ran" is the more foundational reason than "no target identified" when both are true simultaneously — precedence, not behavior, changed).
- Real-ZIP determinism: 10 randomized ZIP-entry orderings and multiple archive filenames all produced the identical `deterministic_hash`.

## 10. Hostile review

- **Does any panel show a number for an analyzer that didn't run?** No — `RiskBreakdown` renders "NOT SCORED" instead of a numeric contribution when `capabilities.*.status != ANALYZED`.
- **Can the explanation layer disagree with the decision report?** No — it now reads only capability-derived, full-findings-list-scoped fields; it has no independent counting logic left for blast radius.
- **Does an absent migration spend risk?** No — proven by test 4.
- **Does a present-but-broken migration lose real risk?** No — proven by test 5.
- **Is any demo-specific string reachable from the upload path?** No — confirmed by grep in §5.
- **Is the canonical fixture unaffected?** Yes — byte-identical decision hash, test 6.
- **Is the real e-commerce ZIP now internally consistent end-to-end, live?** Yes — §6.
- **Was `decide()`'s policy touched?** No — only evidence-selection at the orchestrator layer and presentation-layer normalization guarded by pre-existing fields.
- **Is the fix ZIP-shape-specific (i.e., does it special-case "e-commerce")?** No — both guards key off structural sentinels (`schema_object == "UNKNOWN"`, `missing_evidence` non-empty) that exist for any repository, not this one.
- **Full validation gate green?** Yes — §9.

## 11. Known limitations (not addressed this turn, out of scope per "do not add features")

The full 16-scenario cross-repository matrix (Go/Rust/Java/mixed-monorepo/etc.) and the UNKNOWN-copy audit beyond blast radius (Phase 18's rollback-specific wording) were not built out further this turn — this audit was scoped to the reported contradiction and what forensics proved adjacent to it, per the explicit instruction not to polish or add features beyond what the evidence justified.
