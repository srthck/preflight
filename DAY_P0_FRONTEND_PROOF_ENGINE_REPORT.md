# PRE-FLIGHT FRONTEND TRANSFORMATION — PROOF ENGINE REPORT

## A. What the frontend previously showed

A single client component (`app/page.tsx`, one 37-line JSX blob) that called
`analyzeDemo()` against the hardcoded scenario
`demo-commerce-phone-number-removal` and rendered exactly four things from
the response: `decision_report` (decision, risk score, risk feature bars,
findings list), `explanation.response`, a flat causal-chain strip from
`graph.paths[0]`, and a two-box "FORWARD compatible / ROLLBACK unsafe"
static label pair that was **not** bound to `rollback.forward_compatibility`
/ `rollback.rollback_compatibility` at all — it was hardcoded JSX text
(`<b>COMPATIBLE</b>` / `<b className={styles.dangerText}>UNSAFE</b>`) that
happened to match the canonical scenario by coincidence, not by binding.
There was no scenario switcher, no blast-radius graph, no evidence
inspector, no schema diff, no API-contract view, no decision trace, and no
AI-status distinction beyond a bare `{result.explanation.quality}` string.

## B. Backend capabilities discovered (audit, before any frontend edit)

`AnalysisRunResult.to_response_payload()` (from the prior P0 orchestration
work) already returned `blast_radius`, `deployment`, `api_contract`,
`rollback`, `analysis` (semantic diagnostics, unavailable components,
notes), `ai_available`, and `deterministic_hash` at the top level of every
`/api/analyze` response — none of it reached the UI. `frontend/lib/api.ts`'s
`AnalysisResult` type only declared `case_id`, `decision_report`,
`explanation`, `graph`. This was the single largest finding: most of this
transformation is "stop discarding real data the backend already computes,"
not "invent new backend behavior."

One genuine backend gap: the old/new `SchemaModel` snapshots were computed
inside `pipeline.py::_schema_snapshots()` and then discarded — never
threaded into the result object or the payload. No structured before/after
schema diff existed anywhere.

Explicitly absent from the entire repository, confirmed by reading
`frontend/package.json` and grepping the codebase: any camera, microphone,
Office Kit/device-handoff, on-device/NPU inference, or non-deterministic
confidence-scoring capability. None of these exist in any form — not
disabled, not stubbed, simply not present.

## C. Backend data newly exposed

One additive, minimal backend change: `AnalysisRunResult` gained
`old_schema`/`new_schema` fields (threaded from the already-computed
`_schema_snapshots()` call in `run_analysis()`), and
`to_response_payload()` gained a `schema: {old, new, diff}` key. `diff` is
a pure, non-authoritative presentation transform (`_schema_diff()` in
`models.py`) over the two real `SchemaModel` snapshots — it does not
compute severity, category, or safety; that remains
`DeploymentAnalyzer`'s and `decide()`'s job exclusively. Verified against
both scenarios: the destructive scenario's diff shows `phone_number` as
`REMOVED` with 3 `UNCHANGED` columns; the safe scenario shows
`phone_verified` as `ADDED` with 4 `UNCHANGED` columns.

No other backend logic was touched. `SemanticAnalyzer`, `BlastRadiusEngine`,
`DeploymentAnalyzer`, `analyze_api_contract`, `analyze_rollback`, `decide`,
`explain` are byte-for-byte unchanged from the P0 orchestration work.

## D. Frontend architecture changes

- `frontend/lib/api.ts` rewritten: full typed contract (`DecisionReport`,
  `RiskFeatures`, `CompoundRisk`, `BlastRadiusReport`, `DeploymentFinding`,
  `APIContractFinding`, `RollbackReport`, `RollbackFinding`,
  `SchemaSnapshot`/`SchemaDiffRow`, `AnalysisMeta`) matching the real
  payload field-for-field — every type here was checked against a live
  response, not guessed. `analyzeScenario(scenario, fetcher)` replaces the
  scenario-less `analyzeDemo()`; `SCENARIOS` exports the two real,
  currently-registered scenario ids with honest labels (the label text is
  the real migration statement, not marketing copy).
- `app/page.tsx` decomposed from one monolithic component into
  `app/components/`: `CommandCenter`, `RiskBreakdown`, `BlastRadiusGraph`,
  `FindingsPanel`, `SchemaRehearsal`, `RollbackTimeMachine`,
  `ApiContractPanel`, `DecisionTrace`, `AiExplanation`, `CoverageStatus`,
  `Counterfactual`, plus a shared `format.ts` of pure presentation helpers
  (tone mapping, hash truncation, evidence-row formatting — no analysis
  logic).
- `app/globals.css` gained the shared tone-token custom properties
  (`--danger-fg`, `--warn-fg`, `--safe-fg`, `--unknown-fg` and their
  backgrounds/borders) plus a `prefers-reduced-motion` rule.
  `app/page.module.css` gained ~230 new rules for the new sections,
  mobile-first (base rules target narrow viewports implicitly via
  flex-wrap/grid; a `max-width:680px` block tightens layout further).
- `frontend/scripts/api-integration.mjs` rewritten to assert the full
  real contract on both scenarios and — critically — to fail if the two
  scenarios ever produce the same decision/risk, which would indicate the
  engine stopped reacting to input.

## E. Major judge-facing features implemented (all backed by real data)

1. **Command Center** — verdict, risk score, case id, decision hash
   (copyable), engine/AI status, and a real scenario switcher (destructive
   ↔ safe) that re-runs the actual pipeline, not a client-side toggle.
2. **Risk Calculation** — the 0.40/0.35/0.25 weighted contributions
   computed from real `risk_features`, reconciled against the backend's
   own `base_risk`; compound-risk multipliers rendered only when
   `compound_risks` is non-empty; final `base_risk × multiplier = risk_score`
   arithmetic shown literally with real numbers.
3. **Blast Radius graph** — a real hierarchical column layout (hop 0 root →
   hop 1 direct → hop 2+ indirect), built from `blast_radius.findings`'
   actual `hop_distance`/`category`/`path` fields — no fabricated hairball,
   no invented hop count. Clicking a node opens an evidence inspector
   showing the real `path.evidence` array (source file, line, symbol,
   syntax kind, matched pattern, resolution rule) traced straight from
   `SemanticAnalyzer`'s Tree-sitter output. When a target has zero
   dependents (the safe scenario's new column), it says so honestly
   instead of rendering an empty-looking graph with no explanation.
4. **Findings** grouped causally (Primary Failure / Blast Impact / Rollback
   Impact / API Impact / Other Evidence) by real `category`, with
   per-finding evidence/provenance disclosure.
5. **Database Rehearsal** — the real column-level schema diff (§C above),
   the real migration SQL text (extracted from `deployment.evidence`), and
   a causal closer line connecting the removed column to its dependent
   count.
6. **Rollback Time Machine** — T0/T1 staging, forward vs. rollback
   compatibility pills bound to `rollback.forward_compatibility` /
   `rollback.rollback_compatibility` (the two fields the old UI faked),
   an explicit failure-point callout built from `unsafe_dependencies`,
   and rollback- vs. forward-direction findings shown separately.
7. **API Contract** panel — renders `analyze_api_contract`'s real output;
   when zero changes exist (true for both current scenarios, since neither
   touches `openapi.yaml`), it says so explicitly rather than manufacturing
   a finding.
8. **Counterfactual** — a "Run {other scenario}" button that performs a
   second real `/api/analyze` call against the other registered scenario
   and shows both real decisions/scores side by side. Labeled explicitly as
   real, not simulated, because it is a second pipeline execution, not a
   score projection.
9. **Decision Trace** — the seven real pipeline stages (matching
   `run_analysis()`'s actual call order), each stage's status derived from
   `analysis.unavailable_components` rather than invented timings, followed
   by the real `decision_report.evidence_chain` rendered as an ordered
   trace and the real `policy_rules_triggered`.
10. **AI Explanation** — persistent "ENGINE DECIDES / AI EXPLAINS" framing,
    an honest three-state AI badge (`FULL_AI` / `AI_UNAVAILABLE` /
    `DETERMINISTIC_FALLBACK` — never "on-device", never "NPU", because
    neither exists), grounded claims with their `claim_type`
    (`PROVEN`/`INFERRED`/`UNKNOWN`), and the real per-call timing breakdown.
11. **Analysis Coverage** — real semantic edge counts, unresolved-reference
    and ambiguity counts, unavailable-component and diagnostic lists.
    "No confidence percentage" was a deliberate choice: the backend has no
    such metric, so none is shown.

## F. Capabilities intentionally NOT built (no real backend/runtime support)

Per the anti-fabrication rule, none of the following received any UI —
not even a disabled/"coming soon" placeholder, since even a decorative
button implies a capability under active development:

- Camera / QR-scan workflow
- Microphone / voice / STT workflow
- Office Kit or phone↔laptop handoff
- On-device or NPU-accelerated inference claims
- A fabricated confidence percentage
- A "simulated" risk score for a migration that wasn't actually run

The one item from the brief's P1 list this report does **not** claim as
built: a live phone↔laptop handoff bridge. §9's "counterfactual" was
implemented as a real second pipeline run (see E.8) rather than a
simulated expand/contract risk delta, because the backend has no
counterfactual-simulation capability — only the ability to run a second,
genuinely different, registered scenario.

## G. Tests added/changed

- `frontend/scripts/api-integration.mjs` — rewritten to assert the full
  real response contract (16 field checks) against both scenarios, and to
  fail the build if the two scenarios produce an identical decision/score
  (the actual "is this real" test the brief asks for).
- `src/preflight/orchestration/models.py`, `pipeline.py` — additive only;
  covered by the existing 21 orchestration integration tests plus the
  full 357-test pre-existing suite (all still pass — see H).
- No Python test was weakened or removed.

## H. Test results

```
$ PYTHONPATH=src python -m pytest tests/ -q
378 passed

$ cd frontend && npx tsc --noEmit -p tsconfig.json
(no output — clean)

$ npm run lint
> eslint .
(no output — clean)

$ npm run build
✓ Compiled successfully
✓ Generating static pages (4/4)

$ NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 node scripts/api-integration.mjs
Frontend API integration: PASS
  destructive -> DO_NOT_DEPLOY (100/100, 9a0d8eb4acf467e7...)
  safe        -> SAFE (9/100, e76e6fe48aef10fb...)
```

## I. Lint / type-check results

`ruff check .` — All checks passed. `mypy --strict src/preflight` —
Success, no issues found in 32 source files. `eslint .` (frontend) — clean.
`tsc --noEmit` (frontend) — clean. `next build` — compiles and statically
generates successfully (only pre-existing, non-blocking autoprefixer
flex-shorthand warnings, unrelated to this change).

## J. Visual QA — PARTIAL, stated honestly

No headless-browser tool (`chromium-cli`, Playwright) is installed in this
environment, and installing Playwright would require downloading a
Chromium binary I did not fetch. **I did not capture a screenshot of the
populated report**, so I cannot claim pixel-level visual verification —
doing so without evidence would itself violate the anti-fabrication rule
this task is built around.

What I did verify directly:
- The dev server serves the initial (empty-state) page at `200` and
  contains the expected landing copy.
- `POST /api/analyze` was exercised live, with the frontend's own CORS
  origin header, for both scenarios, and the response was checked
  field-by-field against every TypeScript type.
- `next build`'s static-generation pass renders the component tree
  server-side for the initial (no-result) state without throwing.
- Every CSS class referenced from TSX has a corresponding rule (cross-
  checked while writing each component/CSS pair); the production build's
  CSS-Modules pass would fail on an unresolved class reference, and it
  did not.

What remains unverified: actual rendered layout at each breakpoint,
touch-target sizing on a real device, and whether the blast-radius graph
overflows or clips at very narrow widths beyond what the CSS was designed
for. Both dev servers are left running (backend :8000, frontend :3000) —
opening `http://localhost:3000`, clicking "Analyze demo change," and
trying the scenario switcher is the fastest way to close this gap.

## K. Remaining technical risks

- Visual QA is unverified (§J) — the highest-priority follow-up.
- `DeploymentFinding.deployment_status === "COMPATIBLE"` (a real enum
  value distinct from `SAFE`/`UNSAFE`/`UNKNOWN`) currently renders with the
  "unknown" tone in `SchemaRehearsal` rather than a dedicated tone — a
  minor color-choice gap, not a data-correctness issue; neither current
  scenario exercises this value.
- The blast-radius graph's column layout has not been tested against a
  graph with materially more nodes than the demo-commerce fixture (7
  entities); it should degrade to horizontal scrolling (`graphScroll`) but
  that's untested at scale.
- The Counterfactual panel issues a second live network call on demand;
  if the API server is down, its error path (`AnalysisApiError` message)
  is shown inline but was not tested against a real server-down condition.

## L. Direct statement

**Backed by real deterministic evidence:** the verdict, risk score, hash,
every risk-feature bar and its weighted contribution, every finding and
its evidence/provenance, the entire blast-radius graph and its per-node
evidence inspector, the schema diff table and migration SQL, both rollback
compatibility verdicts and their per-finding reasons, the API contract
status and change list, the decision trace's stage order and evidence
chain, the AI quality badge and its grounded claims, and the coverage/
unknowns panel. Every one of these traces to a field this session read
directly out of a live `/api/analyze` response.

**Intentionally not claimed, because the capability does not exist:**
camera, microphone, on-device/NPU inference, Office Kit/device handoff,
any numeric confidence score, and a "simulated" (as opposed to actually
re-run) safe-migration risk projection. Also not claimed: pixel-verified
visual correctness (§J) — that's marked partial, not passed.
