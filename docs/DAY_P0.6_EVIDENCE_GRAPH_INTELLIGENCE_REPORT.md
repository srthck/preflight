# DAY P0.6 / P0.7 — Evidence Graph Intelligence + Frontend Proof Experience

Covers both missions issued together: P0.6 (make the evidence graph an interactive causal proof system) and P0.7 (world-class judge-facing frontend). Backend analytical truth was **not** changed — no weights, thresholds, findings, or decision logic were touched.

## VISUAL QA: PARTIAL — read this first

Browser automation was attempted and **is not available to me in this session**. Playwright 1.62.1 and Chrome are installed on the machine, and I installed the `playwright` npm package, but the screenshot probe was declined before it ran. **No screenshot was ever captured and no rendered pixel was ever inspected.**

Therefore, the following are **unverified** and are not claimed:

- how any screen actually looks
- node/label clipping or overlap in the SVG graph at real viewport sizes
- spacing, alignment, and 1px consistency (P0.7 §32's "premium detail pass")
- animation smoothness, timing feel, and absence of artifacts
- hover, selection, and drawer interactions in a real browser
- mobile and tablet layout behaviour
- reduced-motion rendering
- whether the interface passes P0.7 §37's "does this look like a student project?" test

I can state that it **compiles, type-checks, lints, builds, and serves HTTP 200**, and that every field each component reads is present and correctly shaped in live backend payloads (asserted below). I cannot state that it looks good, because I did not look at it. The `playwright` devDependency is left installed so this can be completed in one step later.

## Architecture changes

No backend analytical change. One backend-adjacent fix and a set of new frontend components:

| Component | Purpose |
|---|---|
| `VerdictHeader` | Verdict-first hierarchy; risk score count-up; **changeset ID and decision ID shown separately and labelled distinctly** |
| `EvidenceCanvas` (rewritten) | Change-root filtering, risk↔graph highlighting, hover neighbourhood illumination, convergence markers, "Why this decision?" |
| `EvidenceGapGraph` (new) | UNKNOWN/UNSUPPORTED rendered as an **evidence-gap chain**, not an empty canvas |
| `SourceEvidence` (new) | Line-numbered evidence viewer with file breadcrumb, analyzer provenance badge, and multi-item navigation |
| `ManifestDrawer` (new) | Compact file counts + on-demand filterable drawer |
| `RiskBreakdown` (extended) | Rows emit hover events that highlight contributing evidence in the graph |

## Risk-to-evidence mapping (P0.6 §18)

Hovering a risk contribution highlights the evidence that produced it. The traversal is over **backend edges only**:

```
risk:blast_severity
  ← CONTRIBUTES_TO ← finding:blast:*        (findings that feed this feature)
                       ← PRODUCES ← entity:*  (entities that produced those findings)
```

The frontend does not decide which findings belong to which feature — it follows `CONTRIBUTES_TO` edges the backend emitted, keyed by the backend's own `risk_features` field names. Verified by contract assertions that every `RISK_FEATURE` node's `metadata.feature` matches a real key in `decision_report.risk_features`.

No risk arithmetic exists in React. `RiskBreakdown` formats `report.risk_features` and `report.base_risk`; the count-up animation interpolates toward the number the backend already returned.

## Convergence behaviour (P0.6 §13)

The shared node carries a small marker dot; a banner reports `N shared downstream entities reached by independent changes`; clicking expands a panel naming each cause and the shared entity. Every value comes from `evidence_graph.convergence` — the frontend never infers convergence. `test_convergence_is_materialized_as_one_node_with_multiple_paths` (backend) proves the shared entity is one node with two `via_target`-distinguished edges.

## Multiple changes and multi-target (P0.6 §14, §15)

When `evidence_graph` contains more than one `CHANGE` node, a filter row appears: `All changes` plus one pill per change root. Selecting one filters the graph to edges whose `via_target` equals that change's `schema_object` — again a backend-data filter, not a re-derivation. The filter row is rendered **only** when more than one change root genuinely exists, so a single-change analysis is not decorated with a fake control.

## UNKNOWN and UNSUPPORTED (P0.6 §20, §21)

A result with zero causal roots renders `EvidenceGapGraph` instead of an empty diagram: the chain PreFlight *would* have traced (semantic graph → database → dependency impact → API contract → rollback → verdict), each stage labelled with its **real** `capabilities[...]` status and detail, ending with an explicit statement that the verdict was reached because evidence was missing — "not because the change was shown to be safe."

Live-verified: a Go-only repository reports `source: UNSUPPORTED`, a docs-only repository reports `source: UNAVAILABLE`, both `UNKNOWN` with zero fabricated entities.

## The SAFE-with-risk-26 semantic case (P0.6 §19)

The mission flagged that `DROP_COLUMN` + 0 dependents + no rollback violation can legitimately yield `SAFE` under existing policy, and instructed **not** to alter policy to make the UI feel intuitive. Policy was not touched. The verdict header instead states the supporting counts plainly (`N findings · N affected entities · N policy rules triggered`), and the graph shows the change node present with zero dependency edges — the reading is "analyzed, no dependents found", not "nothing happened". The canonical safe scenario still returns `SAFE 9/100` with an unchanged decision hash.

## Security

- Contract test asserts no manifest path matches a local-path pattern (`C:\`, `/tmp/`, `AppData`) and that no local extraction path appears anywhere in a serialized response. Both pass.
- All uploaded source is rendered as **text content** (`<pre>{value}</pre>`, `<code>{value}</code>`) — never `dangerouslySetInnerHTML`, so uploaded files cannot inject markup.
- Archive boundary untouched; 16 archive-security tests still pass.

## Test results

```
python -m pytest -q                                  -> 491 passed
python -m ruff check src/ tests/ scripts/            -> All checks passed
python -m mypy --strict src/preflight                -> Success: no issues found in 44 source files
npx tsc --noEmit                                     -> clean
npx eslint app lib --max-warnings=0                  -> clean
npx next build                                       -> Compiled successfully
node scripts/api-integration.mjs                     -> PASS
node scripts/evidence-graph-contract.mjs             -> PASS (extended with P0.6 component contracts)
```

The contract test was extended to assert every field the new components read: `VerdictHeader`'s score/hashes, the `RISK_FEATURE`↔`risk_features` name correspondence, `SourceEvidence`'s provenance keys (`source_file`, `line`), `ManifestDrawer`'s classifications and content hashes, and `EvidenceGapGraph`'s per-stage capability statuses. If the backend stopped supplying any of them the test fails — which is what keeps the UI from silently inventing a fallback.

## Hostile review (P0.6 §36)

Answered by evidence, with honest "cannot verify" where that applies.

1–3. Judge understands verdict / sees what changed / sees dependents? **Data-verified, visually unverified.** All required data is present and rendered by code that compiles; I did not see the result.
4. Inspect source evidence? **Yes** — `SourceEvidence` renders `source_file`, `line`, `symbol`, `matched_pattern`, `extracted_value`, `resolution_rule`, asserted present in live payloads.
5–7. See why risk changed / which policy fired / trace back to evidence? **Yes** — `CONTRIBUTES_TO`/`TRIGGERS`/`DETERMINES` edges, plus the hover highlight.
8. Two changes converge visibly? **Yes** — marker, banner, and detail panel, all from `evidence_graph.convergence`.
9. Multiple targets independently traceable? **Yes** — change-root filter keyed on `via_target`.
10–13. SAFE / UNKNOWN / UNSUPPORTED explained; unavailable distinguished from zero impact? **Yes** — `EvidenceGapGraph` plus the unchanged capability matrix.
14. Graph proves its own verdict? **Yes** — `reachable_verdict` plus the walkable chain.
15. Can frontend diverge from backend truth? **Structurally constrained** — every displayed value traces to a payload field; contract test fails if a field disappears.
16. Can animation imply work that never happened? **No** — reveal and count-up animate already-returned data, documented in-component; no fabricated progress percentages.
17. Repository identity confused with decision identity? **No** — rendered as separate `CHANGESET ID` / `DECISION ID` with distinct tooltips.
18. Demo entities leak into arbitrary uploads? **No** — fixed in P0.4, still asserted.
19. Uploaded file influence execution? **No** — static analysis only; text-only rendering.
20. README change alters a decision? **No** — `test_unrelated_readme_does_not_change_the_graph`.
21. Judge can challenge any claim and inspect proof? **Data-verified, visually unverified.**

## Known limitations (not hidden)

- **Visual QA is PARTIAL** — see the top of this document. This is the single largest gap in this turn.
- **Several P0.7 items were not implemented**: scroll-triggered section reveals (§9/§10), a dedicated "Judge mode" (§33), the counterfactual morph transition (§16), the multi-stage upload lifecycle display (§18), and the rollback timeline redesign (§21). The existing components for those areas are unchanged and still functional.
- **The premium detail pass (P0.7 §32) was not performed** — it requires rendering the UI to find 1px and alignment issues, which I could not do.
- **No React component test runner** is configured; interaction behaviour (click, hover, drawer open, filter switching) is covered only by TypeScript's structural guarantees and the payload contract test, not by executed UI tests.
- **`highlightFeature` graph highlighting is implemented but unproven in a browser** — the traversal logic is correct against backend data, but I did not see it dim/illuminate.
- **Structural source changes still are not graph roots** (carried over from P0.5) — they are surfaced in their own panel but do not feed blast radius, because resolving an arbitrary removed symbol to a graph entity is not something the resolver can currently do honestly.
- **Performance was not benchmarked** (P0.6 §32 / P0.7 §29). The graphs are small (7–21 nodes) and rendered as plain SVG with memoized layout and stable keys, but no measurements were taken.

## Final status

P0.6's graph-intelligence requirements are implemented and contract-verified against live backend data. P0.7's design-system and hierarchy work is partially implemented — verdict-first hierarchy, risk score animation, the evidence viewer, the manifest drawer, and the microinteraction/token pass are in; scroll choreography, judge mode, and the detail pass are not.

I am explicitly **not** declaring this "world-class", because P0.7 §37's own acceptance test is a visual judgement and I was unable to render the interface. The correct next step is one browser pass to capture the ten screens P0.7 §36 lists and complete the detail pass against what they show.
