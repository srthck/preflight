# DAY P0.9 — Final Productization, Motion System & Judge Experience

## Environment

- **Browser:** Chrome (system channel) driven by Playwright 1.62.1
- **Harness:** `frontend/scripts/visual-qa.mjs` (committed, re-runnable), 35 screenshots per pass
- **Viewports:** 1440×900, 768×1024, 390×844, plus a `reducedMotion: "reduce"` context
- **Passes:** 4 (`p9a` → `p9b` → `p9c` → `final`)
- **Console:** **0 errors** on the final pass (P0.8 ended with 1)

## P0.8 gaps — disposition

| # | Gap | Status |
|---|---|---|
| 1 | Scroll reveal CSS-only, not wired | **DONE** — `hooks/useReveal.ts` (IntersectionObserver), applied via a new `Section` component |
| 2 | Judge mode missing | **DONE** — real focused mode, verified in browser |
| 3 | Upload lifecycle missing | **DONE** — 9 real stages, no fabricated percentage |
| 4 | Counterfactual morph | **NOT DONE** — see limitations |
| 5 | Two-version browser E2E | **DONE** — captured `13-two-version-verdict` |
| 6 | Convergence browser E2E | **DONE** — captured `09-convergence`, `09c-convergence-graph` |
| 7 | Reduced-motion browser verification | **DONE** — measured, not assumed |
| 8 | Keyboard graph traversal | **DONE** — arrows/Enter/Space/Escape |
| 9 | Performance unmeasured | **DONE** — measured, numbers below |
| 10 | RISK→POLICY visual noise | **DONE** — honest bundling through a labelled junction |
| 11 | Labels truncate | **PARTIAL** — full text in inspector, `<title>` tooltip on nodes; no custom tooltip |
| 12 | Favicon 404 | **DONE** — `app/icon.svg` |

## Defects found by looking, and fixed

### 1. Judge mode still showed the hero — and the first fix silently failed
`p9a-15-judge-mode.png` showed the full marketing hero after entering judge mode. I first used `hidden={judgeMode}`; `p9c` proved it **had no effect** — `.hero` sets `display:flex`, which beats the user-agent `[hidden]{display:none}` rule. Replaced with conditional rendering. `final-15-judge-mode.png` now opens directly on **"Do not deploy / 100"** followed by the evidence graph.

This is a case where taking the second screenshot mattered: the first fix compiled, looked correct in code, and did nothing.

### 2. React key collision that only exists in a convergence — CRITICAL
Console: `Encountered two children with the same key … compliance-api.ComplianceAPI`. The backend payload was correct (one convergence entry). Root cause was `BlastRadiusGraph` keying findings by `affected_entity` — but in a convergence the same downstream entity **legitimately appears once per causal path**, which is the entire point of the model. Two siblings therefore shared a key, and React's documented behaviour is that children may be *duplicated or omitted*.

Fixed by keying on `${finding.target}:${finding.affected_entity}`. **This bug was only reachable through the convergence flow — the exact scenario P0.8 could not verify.**

### 3. Hover dimming erased the graph
`p9a-09c` showed most of the diagram invisible after a mouse-over: hover reused the full `.graphDimmed` (opacity .14) treatment. Split into `.graphSoftDimmed` (.42) for hover-emphasis, reserving full dim for why-mode and change-root filtering. Hover now recedes context rather than deleting it.

### 4. Page title asserted something the product denies
`"PreFlight AI | Deployment Risk Intelligence"` contradicted the core claim that the verdict is deterministic and AI is explanation-only. Now `"PreFlight — Deployment Survival Engine"`.

## RISK → POLICY: honesty over tidiness

`decide()` does not expose which risk feature fired which policy rule. The graph previously drew every non-zero feature to every triggered rule — 9 crossing arrows asserting a mapping the data cannot support.

Rather than invent a mapping, the TRIGGERS edges now route through a single waypoint labelled **POLICY EVALUATION**, with a tooltip stating plainly: *"All contributing risk features feed policy evaluation collectively. The engine does not report which feature triggered which rule."* Visible in `final-09c-convergence-graph.png`. This is calmer *and* more truthful — it removes a false implication rather than hiding it.

## Upload lifecycle — what it does and does not claim

Nine stages in the engine's real execution order (INGEST ARCHIVE → … → APPLY POLICY). The API returns **one** response at the end and streams no progress, so:

- no percentage is displayed anywhere;
- the indicator advances through the ordered stages and then **holds on the final stage** until the real response lands — it never runs ahead to a "complete" state the backend never reported;
- the panel states this explicitly: *"The engine returns one result when the full run completes — no partial progress is reported or estimated."*

## Reduced motion — measured, not assumed

Captured in a real `reducedMotion: "reduce"` browser context, then measured in the live DOM:

```
{ graphNodes: 17, faded: 0, revealTargets: 12, unrevealed: 0 }
```

All 17 graph nodes fully opaque and all 12 reveal targets fully revealed **without any motion running**. `useReveal` short-circuits to `revealed = true` and never observes; the risk counter renders its final value directly. No content depends on animation to become readable.

## Performance — measured

| Metric | Result |
|---|---|
| DOMContentLoaded | 75 ms |
| Load event | 606 ms |
| Click → verdict visible (incl. backend round-trip) | **483 ms** |
| Total DOM nodes | 846 |
| Graph nodes / SVG paths | 17 / 27 |
| Hover-stress frame gap (median / p95 / worst) | **8.3 ms / 8.5 ms / 8.8 ms** |

Frame gaps stay near 8 ms while hovering every node in sequence — comfortably above 60 fps (16.7 ms), with no dropped frames. No optimisation was needed and none was invented.

## Verification status

**VERIFIED (rendered and inspected, or measured in the live DOM):**
- Landing, safe, destructive, UNKNOWN, unsupported at 1440×900
- Evidence graph two-band layout; verdict node on-screen
- "Why this decision?" ordered chain; button contrast
- Node hover (softened), selection, inspector
- **Judge mode** — opens on verdict, nav stripped, exit works
- **Two-version comparison** end-to-end in browser
- **Convergence** — 2 change roots → shared `ComplianceAPI`, detail panel, graph marker
- **Upload lifecycle** mid-flight
- **Reduced motion** — measured, zero hidden content
- Mobile 390×844, tablet 768×1024; zero page-level horizontal overflow
- Performance and frame behaviour
- Zero console errors

**PARTIALLY VERIFIED:**
- Keyboard traversal — implemented (arrows/Enter/Space/Escape) and type-checked, but **not driven end-to-end in the browser**; I did not tab through the graph and confirm focus movement visually
- Scroll reveal — the observer is wired and reduced-motion behaviour is measured, but I did not capture a mid-scroll frame proving the transition itself
- Label truncation — native `<title>` tooltips only; no designed tooltip component

**NOT VERIFIED / NOT DONE:**
- **Counterfactual morph** — not implemented. The counterfactual still hard-swaps between two real pipeline runs rather than animating the transition. It remains truthful (both results are real), just not animated.
- Animation *feel* — still frames only; I never watched the motion play
- Long-session memory/re-render profiling

## Automated gate — no regressions

```
python -m pytest -q                        -> 491 passed
python -m ruff check src/ tests/ scripts/  -> All checks passed
python -m mypy --strict src/preflight      -> Success: no issues found in 44 source files
npx tsc --noEmit                           -> clean
npx eslint app lib hooks --max-warnings=0  -> clean
npx next build                             -> Compiled successfully
node scripts/api-integration.mjs           -> PASS
node scripts/evidence-graph-contract.mjs   -> PASS
```

**Decision hashes byte-identical** to every prior turn (`ebafcde445cb93a1…` / `e76e6fe48aef10fb…`). No backend policy, weight, or threshold was touched.

P0.8 regression checks all still hold: verdict visible after analysis, no duplicate verdict, graph fits viewport, band labels clear, WHY button contrast correct, WHY chain works, mobile `scrollWidth === viewport`, UNKNOWN never renders as SAFE, no demo leakage, no local path leakage.

## Judge test

- **5s — what does it do?** Hero states "Ship with proof" over "Deployment survival engine". Yes.
- **10s — the verdict?** Analysis auto-scrolls to it; judge mode opens on it. Yes.
- **20s — why?** Deterministic root cause sits directly under the headline. Yes.
- **30s — follow the evidence?** Two-band graph, then the ordered "Why this decision?" chain. Yes.
- **60s — why is this different from a code scanner?** It shows a *causal chain* from a schema change through real dependency edges to a policy rule, with source-located provenance, and refuses to guess when evidence is missing. Yes.

## Known limitations

- Counterfactual morph not implemented (§4 of the brief).
- Keyboard traversal is implemented but not browser-verified.
- The `TRIGGERS` relationship remains an honest aggregation, not a precise mapping — resolving it properly requires `decide()` to report feature→rule attribution, which is a backend change deliberately not made here.
- Long labels rely on native tooltips.
- `playwright` remains a devDependency for QA; it is not in the app bundle.

## Closing

I am not calling this "world-class" — that is a judgement for a person looking at it, and my evidence is 35 still frames plus DOM measurements, not a human reaction. What I can state precisely: every P0.8 gap except the counterfactual morph is closed, three real defects were found by rendering (one of them a data-corrupting React key collision reachable only through convergence), the interface is measurably fast, it degrades correctly without motion, and nothing it displays is unsupported by the backend.
