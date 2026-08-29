# DAY P1 — Signature Experience

## Scope

The one genuinely missing signature interaction from P0.9 was the **counterfactual morph**. That is now built and browser-verified, and P0.9's two "partially verified" accessibility items are now fully verified. No backend policy, weight, threshold, or hashing was touched.

- **Browser:** Chrome (system channel) via Playwright 1.62.1
- **Viewports:** 1440×900, 768×1024, 390×844, plus a `reducedMotion: "reduce"` context
- **Final pass:** 35 screenshots, **0 console errors**

## 1. Counterfactual morph — VERIFIED

### What it does

The counterfactual previously ran the alternative scenario for real but rendered it as two inert cards; it could never become the report you were reading. Now:

1. It runs the real pipeline against the other fixture (unchanged behaviour).
2. Both completed analyses render as selectable cards showing decision, risk, findings, and affected-entity counts.
3. Selecting either one **adopts that exact returned payload as the active report** — verdict, evidence graph, risk breakdown, coverage, and rollback all re-render from it.

### Honesty constraints, and how they are enforced

- **No refetch, no recomputation.** `adoptResult()` sets the already-returned payload as state. The final frame is byte-for-byte the engine's output.
- **The risk number travels between two real endpoints.** `useCountUp` now animates from the *previous real score* to the *new real score* (100 → 9), rather than restarting from 0. Both endpoints are engine output; only the frames between are presentational, and the animation always terminates on the exact returned value.
- **The graph morphs by node identity.** Nodes present in both graphs keep their identity and position (layout is deterministic, so shared nodes do not move). Nodes unique to the newly-adopted analysis are marked `entering` and fade in. Nothing is interpolated.
- **Stated in the UI:** *"Both results above were produced by the deterministic engine. Selecting one replaces the report you are reading with that exact returned analysis… No intermediate value shown during the transition is engine output."*

### Browser evidence

```
BEFORE: {"verdict":"Do not deploy","score":"100","nodes":17}
CARDS : ["Destructive: DROP COLUMN · DO NOT DEPLOY · 100 · 5 findings · 4 affected · Currently shown",
         "Safe: ADD COLUMN · SAFE · 9 · 1 findings · 1 affected · Show this analysis"]
AFTER : {"verdict":"Safe to deploy","score":"9","nodes":7}
errors: none
```

The mid-morph frame (`cf-mid-morph.png`) captures the transition in progress: the graph already at the SAFE analysis's 7 nodes/3 edges, the SAFE-only `NO_BLOCKING_FINDING_LOW_RISK` policy node entering, and the sections below mid-reveal.

## 2. Keyboard traversal — VERIFIED (was PARTIALLY VERIFIED in P0.9)

Driven with the keyboard only, in a real browser:

```json
{"focusedInitial":"change:DROP_COLUMN:users.phone_number",
 "afterArrowRight":"entity:users.phone_number","movedRight":true,
 "inspectorOpenedByEnter":true,
 "inspectorClosedByEscape":true,
 "afterArrowLeft":"change:DROP_COLUMN:users.phone_number","movedBack":true}
focus ring stroke: rgba(142, 194, 142, 1)
```

Arrow keys move between graph nodes in deterministic order, Enter opens the evidence inspector, Escape closes it, and the focus ring is visibly rendered. A keyboard user can traverse the entire causal chain.

## 3. Reduced motion — VERIFIED

Measured in a real `reducedMotion: "reduce"` context:

```json
{"graphNodes":17,"faded":0,"revealTargets":12,"unrevealed":0}
```

All 17 graph nodes fully opaque, all 12 reveal targets fully revealed, with no motion running. The new `graphNodeEntering` animation is disabled under the same media query. No information depends on motion.

## 4. SAFE and UNKNOWN verdicts — VERIFIED

§7 required SAFE not to read as "nothing happened". The adopted SAFE analysis shows **"5/5 analyzers ran"**, `SOURCE / SEMANTIC GRAPH — 7 entities, 6 edges — ANALYZED`, and `DATABASE MIGRATION — ADD_COLUMN on users.phone_verified — ANALYZED`. It reads as *analyzed and found safe*.

The rollback section (verified in `cf-both-runs.png`) already satisfies §11 precisely:
- **ROLLBACK: UNSAFE** with an explicit **FAILURE POINT** — *"OLD APPLICATION expects `users.phone_number`, which the proposed schema no longer contains."*
- **FORWARD: UNKNOWN** with the reason — *"no next-version application snapshot was supplied… reported honestly as unknown rather than assumed safe."*
- **API CONTRACT: SAFE** — *"PreFlight does not manufacture an API finding to look more dangerous."*

## 5. Environment defect found (not a product defect)

Running `npx next build` while `next dev` was live overwrote the `.next` directory the dev server was serving from. Static chunks began returning 404, React never hydrated, and the page rendered as inert HTML — which initially looked like a product regression. Diagnosed via `requestfailed` events, fixed by clearing `.next` and restarting dev. **Anyone re-running this QA should not run `next build` against a live dev server.**

## Automated gates — no regressions

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

**Decision hashes byte-identical** (`ebafcde445cb93a1…` / `e76e6fe48aef10fb…`).

P0.8/P0.9 regression checks hold: verdict auto-scroll, no duplicate verdict, graph fits viewport, no horizontal overflow, WHY chain, soft hover dimming, convergence keys, UNKNOWN/unsupported semantics, upload-lifecycle honesty, no fake progress, reduced motion, no local path leakage, no demo leakage.

## Verification status

**VERIFIED:** counterfactual morph (adopt, risk transition between real endpoints, node entry); keyboard traversal (arrows/Enter/Escape/focus ring); reduced motion (measured); SAFE verdict semantics; rollback failure point and UNKNOWN reasoning; zero console errors across 35 screenshots; all automated gates; decision-hash stability.

**PARTIALLY VERIFIED:** animation *feel* — I have a genuine mid-transition frame, but I never watched the motion play at speed; scroll-reveal transition (observer wired and reduced-motion measured, no mid-scroll frame captured); label truncation (native `<title>` tooltips only, no designed tooltip component).

**NOT VERIFIED:** performance of the counterfactual transition specifically (P0.9's general measurements — 483 ms click→verdict, 8.3 ms median frame gap — were not re-run after this change); long-session memory profiling; the §11 design-token consolidation and §12 "generic SaaS language" audit were not carried out as a systematic sweep this turn.

## Remaining limitations

- The design-system consolidation (§11) and card-reduction audit (§12) were scoped out in favour of the one missing signature interaction; the token set is coherent but still has one-off values.
- The `TRIGGERS` relationship remains an honest aggregation through the labelled POLICY EVALUATION junction, not a precise mapping — resolving it properly requires `decide()` to report feature→rule attribution, a backend change deliberately not made.
- The counterfactual is available for fixture scenarios only (it needs a second registered scenario); uploaded projects have no alternative to compare against.
- `playwright` remains a devDependency for QA, not in the app bundle.

## Closing

I am not going to call this world-class, top 0.1%, or Apple-level — those are judgements for a person looking at the product, and my evidence is 35 still frames, DOM measurements, and driven interactions, not a human reaction. What I can state precisely: the counterfactual morph now transitions between two genuinely-real analyses without inventing a single intermediate value the engine did not produce, keyboard and reduced-motion access are measured rather than assumed, and every automated gate passes with the decision hashes unchanged.
