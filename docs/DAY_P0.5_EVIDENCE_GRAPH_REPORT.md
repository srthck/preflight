# DAY P0.5 — Materialized Evidence Graph + Structural Change Intelligence

## Executive summary

P0.4 closed with the evidence graph existing only *implicitly*, spread across seven separate response fields, and with structural source diffing unimplemented. P0.5 materializes the graph as a first-class backend object, implements parser-backed structural diffing, and makes the causal chain the primary visual surface.

Three things were built, and one real defect was found and fixed along the way:

1. **`EvidenceGraph`** (`src/preflight/evidence_graph.py`) — a materialized, deterministic projection of the chain `CHANGE → SCHEMA_ENTITY → SERVICE → API_ENDPOINT → FINDING → RISK_FEATURE → POLICY_RULE → VERDICT`. It is an integration model: it performs no parsing, no traversal, no risk arithmetic, no policy evaluation.
2. **Structural source diffing** (`src/preflight/structural_diff.py`) — declaration-level comparison via the existing Tree-sitter extractor, with a hard rule that a file which failed to parse on either side produces **no symbol claims at all**.
3. **Evidence canvas** (`frontend/app/components/EvidenceCanvas.tsx`) — an SVG causal graph with column-wise causal reveal, a "Why this decision?" mode that dims everything outside the verdict chain, a click-through evidence inspector with real source provenance, and a text-equivalent causal chain for non-visual access.

**Defect found during live verification:** the canonical single-repository path (`/api/analyze` — the primary judge demo) produced a graph with `roots=0` and `reachable_verdict=false`, because `schema_changes` was only populated on the snapshot-pair path. The verdict *was* genuinely reachable from evidence there, so the graph was understating its own proof. Fixed by enumerating schema changes in `_execute_pipeline` as well. Both canonical scenarios now report `roots=1, reachable=True`.

## Architecture: before and after

| | Before (P0.4) | After (P0.5) |
|---|---|---|
| Causal chain | Implicit across `schema_changes`, `blast_radius.findings[].path`, `decision.findings`, `risk_features`, `policy_rules_triggered`, `convergence` | Materialized `evidence_graph` with typed nodes and edges |
| Frontend's job | Reverse-engineer the chain from six fields | Render backend-supplied nodes/edges |
| Source changes | Domain classification only (`SOURCE`/`DATABASE`/…) | Declaration-level `FUNCTION_/METHOD_/CLASS_ ADDED/REMOVED` with file, line, language, and establishing parser |
| Graph identity | n/a | `graph_hash`, separate from `change_set_hash` and `deterministic_hash` |

`decide()` was not touched. Weights, thresholds, and policy remain exactly as they were; the graph reads the numbers `decide()` produced and never recomputes them.

## EvidenceGraph schema

**Node kinds** (10): `CHANGE`, `SCHEMA_ENTITY`, `SOURCE_SYMBOL`, `SERVICE`, `API_ENDPOINT`, `CLIENT`, `FINDING`, `RISK_FEATURE`, `POLICY_RULE`, `VERDICT`.

**Edge kinds** (6), each with a specific meaning: `AFFECTS` (change → entity), `DEPENDS_ON` (entity → entity, carrying the real `EdgeEvidence`), `PRODUCES` (entity → finding), `CONTRIBUTES_TO` (finding → risk feature), `TRIGGERS` (risk feature → policy rule), `DETERMINES` (policy rule → verdict).

Every node carries `provenance` (source file, line, symbol) and a `layer` derived from real hop distance — 0 for the change, 1..n for dependency hops, then 90/91/92/93 for finding/risk/policy/verdict.

### Deterministic identity

Node IDs are content-derived, never positional: `change:DROP_COLUMN:drivers.license_number`, `entity:compliance-api.ComplianceAPI`, `finding:<finding_id>`, `risk:blast_severity`, `policy:RISK_THRESHOLD_70`, `verdict`. No array indices, UUIDs, timestamps, or extraction paths appear in any identifier. All collections sort before emission, and `graph_hash` is a canonical-JSON SHA-256 over the sorted result.

Proven by `test_same_content_produces_the_same_graph_hash` (different nested extraction directories → identical hash), `test_graph_node_and_edge_ordering_is_deterministic`, and `test_node_ids_are_content_derived_not_positional`.

## Convergence: one node, both paths preserved

The `fleet-ops` fixture's real output, from the live server:

```
roots: change:DROP_COLUMN:drivers.license_number, change:DROP_COLUMN:drivers.medical_cert

entity:drivers.license_number --DEPENDS_ON/DB_READ--> entity:dispatch-service.DispatchService  via=drivers.license_number
entity:dispatch-service.DispatchService --DEPENDS_ON/HTTP_CALL--> entity:compliance-api.ComplianceAPI  via=drivers.license_number
entity:drivers.medical_cert --DEPENDS_ON/DB_READ--> entity:audit-service.AuditService  via=drivers.medical_cert
entity:audit-service.AuditService --DEPENDS_ON/HTTP_CALL--> entity:compliance-api.ComplianceAPI  via=drivers.medical_cert

convergence: [('compliance-api.ComplianceAPI', 2)]
```

`ComplianceAPI` is **one** node with **two** incoming edges, distinguished by `via_target`. The `via_target` field is what prevents deduplication from destroying the second causal path — `test_convergence_is_materialized_as_one_node_with_multiple_paths` asserts exactly one node and exactly two incoming edges with distinct `via_target` values.

## Structural diff strategy

Symbols are extracted by the existing `SourceExtractor` (Tree-sitter) on both sides and compared by `(file, symbol_kind, qualified_name)`. Module/package pseudo-symbols are excluded as they describe the file rather than a declaration a developer wrote.

The governing rule, and the reason this is not a text diff: **if either side failed to parse, the file is reported `PARSE_ERROR` and no symbol claims are made about it.** `test_unparseable_file_makes_no_symbol_claims` proves a syntactically broken file produces zero structural changes and an explicit status — never "every method was removed." `test_comment_only_edit_produces_no_structural_change` proves the inverse: text changing without structure changing yields nothing.

## Adversarial and integrity test results

New this turn: **34 tests** (20 evidence graph, 7 structural diff, 7 pre-existing adversarial retained), total **491 passing**.

| Invariant | Test | Result |
|---|---|---|
| A. Every entity has a change ancestor | `test_every_entity_node_is_reachable_from_a_change_root` | PASS |
| C. Every dependency edge has provenance | `test_dependency_edges_carry_provenance` | PASS |
| D. Removing a dependency removes the path | `test_removing_a_dependency_removes_the_path` | PASS |
| F. Removing one convergence path removes convergence | `test_removing_one_convergence_path_removes_convergence` | PASS |
| G/H. Unrelated README does not change the graph or decision | `test_unrelated_readme_does_not_change_the_graph` | PASS |
| I/J. Node and edge ordering deterministic | `test_graph_node_and_edge_ordering_is_deterministic` | PASS |
| L. UNKNOWN never becomes a repository entity | `test_unknown_never_becomes_a_graph_entity` | PASS |
| M/N. Unavailable never becomes zero impact | `test_unavailable_analyzer_never_becomes_a_causal_node` | PASS |
| O. No demo vocabulary in unrelated repositories | `test_graph_contains_no_demo_vocabulary_for_unrelated_repository` | PASS |
| SAFE reads as analyzed-with-zero-impact | `test_safe_change_produces_an_analyzed_graph_with_zero_impact` | PASS |

A note on invariant L: the initial version of that test failed on `policy:REQUIRED_EVIDENCE_UNKNOWN`. That was the **test** being imprecise, not a defect — a policy rule named for missing evidence, and a verdict of `UNKNOWN`, are both genuine facts. The test was tightened to assert what the invariant actually means: the `"UNKNOWN"` sentinel must never become a schema entity, service, API, client, or change node.

## Live HTTP verification (six scenarios, both servers running)

| # | Scenario | Decision | Roots | Reachable | Notes |
|---|---|---|---|---|---|
| 1 | canonical destructive | DO_NOT_DEPLOY | 1 | true | 17 nodes, full chain |
| 2 | canonical safe | SAFE | 1 | true | change shown, blast radius `ANALYZED` |
| 3 | fleet-ops convergence | DO_NOT_DEPLOY | 2 | true | 1 convergent entity, 2 causes |
| 4 | arbitrary inventory repo | DO_NOT_DEPLOY | 1 | true | entities `InventoryTracker`, `PricingEngine`, `warehouse_qty`; **zero demo leakage** |
| 5 | unsupported (Go) | UNKNOWN | 0 | false | `source: UNSUPPORTED`, no invented entities |
| 6 | no-evidence (docs only) | UNKNOWN | 0 | false | `source: UNAVAILABLE`, no invented entities |

Scenarios 5 and 6 are the anti-fabrication proof: neither is downgraded to SAFE, neither invents a node, and both correctly report the verdict as not reachable from causal evidence.

## Frontend state coverage

| State | Handling |
|---|---|
| LOADING | Existing staged sequence; no fake percentages |
| ANALYZED | Full graph with causal reveal |
| SAFE | Change node still rendered; zero dependency edges (analyzed, no dependents) |
| UNKNOWN / UNAVAILABLE | Toolbar states "The verdict was not reached through causal evidence"; "Why this decision?" is disabled |
| UNSUPPORTED | Capability matrix reports `UNSUPPORTED`; graph shows no fabricated entities |
| EMPTY | Explicit "No causal graph was produced" panel rather than a blank canvas |

**Animation honesty:** the column reveal animates *already-returned* evidence and is documented as such in the component. No animation duration is ever presented as analysis latency; real backend timing remains separate. `prefers-reduced-motion` renders the entire graph immediately, and the text-equivalent causal chain (`<details>`) is always present regardless of motion settings.

**Frontend never infers:** it renders `evidence_graph` nodes/edges, `capabilities` statuses, and `decision_report` numbers as supplied. `verdictChain()` is a traversal over backend-supplied edges, not an inference about causality. No policy arithmetic exists in React.

## Security

Unchanged and not regressed. Both archives pass through the same hardened `extracted_project()` boundary; all 16 archive-security tests still pass. Nothing uploaded is executed, installed, or built — `structural_diff.py` and `evidence_graph.py` contain no `subprocess`/`eval`/`exec`. Source evidence is rendered as text content (`<pre>{value}</pre>`), never as markup, so uploaded source cannot inject HTML. Extraction paths are never serialized into the response.

## Verification gate

```
python -m pytest -q                                  -> 491 passed
python -m ruff check src/ tests/ scripts/            -> All checks passed
python -m mypy --strict src/preflight                -> Success: no issues found in 44 source files
cd frontend && npx tsc --noEmit                      -> clean
cd frontend && npx eslint app lib --max-warnings=0   -> clean
cd frontend && npx next build                        -> Compiled successfully
node scripts/api-integration.mjs                     -> PASS
node scripts/evidence-graph-contract.mjs             -> PASS
```

## Hostile review (§31)

1. Two independent changes → two graph roots? **Yes** — `test_multiple_changes_create_multiple_change_nodes`.
2. Two roots converge on one entity? **Yes** — live fleet-ops output.
3. Both paths preserved? **Yes** — `via_target` on each edge; `test_convergence_is_materialized_as_one_node_with_multiple_paths`.
4. Entity without a change ancestor? **No** — `test_every_entity_node_is_reachable_from_a_change_root`.
5. Evidence edge without provenance? **No** — `test_dependency_edges_carry_provenance`.
6. UNKNOWN becomes a graph node? **No** (as an entity) — `test_unknown_never_becomes_a_graph_entity`.
7. Unavailable becomes zero impact? **No** — `test_unavailable_analyzer_never_becomes_a_causal_node`.
8. Unsupported becomes analyzed? **No** — live scenario 5.
9. README changes alter the decision? **No** — `test_unrelated_readme_does_not_change_the_graph`.
10/11. Extraction directory or ZIP order alter graph identity? **No** — `test_same_content_produces_the_same_graph_hash`; ZIP-order independence inherited from the unchanged, still-tested archive boundary.
12. Demo vocabulary in an unrelated repository? **No** — live scenario 4 and `test_graph_contains_no_demo_vocabulary_for_unrelated_repository`.
13. Source-function removal representable? **Yes** — `test_removed_method_is_detected_with_source_location`.
14. Three-statement migration → three change objects? **Yes** — the multi-statement parser fixed in P0.4; two-statement case asserted, and the loop is per-statement with no cap.
15. Multiple targets independently reach BlastRadiusEngine? **Yes** — one call per target, merged afterwards.
16/17/18. Risk → findings → policy → verdict traceable? **Yes** — `CONTRIBUTES_TO`/`TRIGGERS`/`DETERMINES` edges; `test_verdict_is_reachable_through_the_graph`.
19. Frontend invents evidence? **No** — it renders supplied nodes/edges only.
20. Frontend recalculates policy? **No** — `RiskBreakdown` formats backend numbers; no policy math in React.
21. Animation implies fake analysis? **No** — reveal animates returned evidence, documented in-component, never labelled as latency.
22. Reduced motion preserves complete evidence? **Yes** — immediate render plus the always-present text chain.
23. Judge can follow the chain without the report? **Partially verifiable** — the graph, "Why this decision?" mode, and inspector are built for it, but this is a human-comprehension claim I cannot test automatically and did not user-test. Not asserted as proven.
24/25/26. Graph sensible for SAFE / UNKNOWN / unsupported? **Yes** — live scenarios 2, 5, 6 and the SAFE-state test.

## Known limitations (disclosed, not hidden)

- **VISUAL QA: PARTIAL.** No screenshots were captured and no browser-rendering verification was performed. Both servers were confirmed serving HTTP 200 and the graph contract was asserted against live payloads, but the rendered appearance, layout at real viewport sizes, and the animation's feel were **not** visually inspected. Any claim about how the graph *looks* is unverified.
- **No React component test runner is configured** in this repository. Rather than add one under time pressure or claim coverage that does not exist, §30's requirements are covered by a live-backend contract test (`evidence-graph-contract.mjs`) asserting semantic content, plus the pure-logic guarantees enforced by `tsc`. Interaction behaviours (node click, inspector open, "Why this decision?" toggle, mobile layout) are **not** covered by automated tests.
- **Structural changes are not yet wired into the evidence graph as nodes.** They are extracted, provenance-carrying, surfaced in the API response, and rendered in their own panel — but `FUNCTION_REMOVED` does not currently become a `CHANGE` root feeding blast radius. Doing so honestly requires resolving a removed symbol to a graph entity, which the current resolver does not do for arbitrary symbols; inventing that mapping would violate the anti-fabrication rule.
- **Signature changes are not detected** — only added/removed declarations. A renamed parameter or changed return type is invisible. `RENAMED` file detection is likewise not implemented; renames appear as `REMOVED` + `ADDED`, which the P0.4 brief explicitly preferred over a fabricated rename.
- **Config, deployment, and dependency domains remain classified but unanalyzed** (unchanged from P0.4). No analyzer resolves their consumers, so they contribute no graph nodes.
- **Performance (§24) was not benchmarked.** No timing measurements were taken and no performance numbers are claimed.
- **The `TRIGGERS` edge is coarse**: every non-zero weighted risk feature is linked to every triggered policy rule, because `decide()` does not expose which specific feature fired which specific rule. This is an honest over-approximation of a real relationship rather than a fabricated precise one, but it is not a precise mapping.

## Final status

The two gaps P0.4 disclosed — an implicit evidence graph and missing structural diffing — are **closed**, and a real defect in the canonical demo's graph reachability was found and fixed during live verification. The full backend and frontend gates pass, and all six required live scenarios tell the same story on both sides. Sections 24 (performance) and parts of 30 (component-level interaction tests) are **not complete**, and visual QA is **partial** — these are listed above rather than glossed.
