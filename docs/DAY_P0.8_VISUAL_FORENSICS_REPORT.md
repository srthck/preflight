# DAY P0.8 — Visual Forensics + Polish

## VISUAL QA: PERFORMED (this is the change from P0.7)

P0.7 closed with `VISUAL QA: PARTIAL` — no screenshot had ever been captured. This turn, the application was rendered in **real Chrome via Playwright**, screenshots were captured across four iteration passes, and **the screenshots were inspected**. Every defect below was found by looking at rendered pixels or by measuring the live DOM, not by reading code.

- **Tool:** Playwright 1.62.1 driving system Chrome (`channel: "chrome"`)
- **Harness:** `frontend/scripts/visual-qa.mjs` (committed, re-runnable)
- **Viewports:** 1440×900 desktop, 768×1024 tablet, 390×844 mobile
- **Passes:** 4 (`pass1` baseline → `pass2` → `pass3` → `final`), 23 screenshots each
- **Console errors:** 1 across all passes — a single 404 for a static asset (favicon-class); no JS errors, no `pageerror` events

## Defects found by looking, and fixed

### 1. The verdict was invisible after analysis — CRITICAL
**Found in:** `pass1-03-destructive-verdict.png`. After clicking "Try the canonical scenario" and waiting for completion, the screenshot showed *the unchanged hero*. The verdict sat far below the fold. A judge would click "analyze" and appear to get nothing.
**Fix:** `page.tsx` now scrolls a dedicated anchor into view on completion (`behavior: "auto"` under reduced motion).
**Verified:** `pass2-03` onward opens directly on "Do not deploy / 100".

### 2. Two competing verdicts on one screen
**Found in:** `pass1-10-unknown-full.png` — the legacy `CommandCenter` verdict block and the new `VerdictHeader` both rendered.
**Fix:** removed the duplicate block from `CommandCenter`; it now carries only controls and the provenance strip. The deterministic root cause moved into `VerdictHeader`, so the "why" is adjacent to the verdict.

### 3. The evidence graph overflowed and pushed the verdict off-screen — CRITICAL
**Found in:** `pass1-04-evidence-graph.png`. The single 8-column row measured **~2330px**; at 1440px it forced horizontal scroll (the panel heading rendered clipped as "idence graph"), and the RISK / POLICY / VERDICT columns were entirely off-screen. The signature feature was unusable.
**Fix:** rewrote `evidenceLayout.ts` as **two stacked bands** — `SYSTEM IMPACT` (change → changed entity → direct → downstream) above `DECISION PROOF` (findings → risk → policy → verdict) — with cross-band edges drawn vertically as the impact→consequence hand-off. Width dropped to ~1090px.
**Verified:** `pass2-04` and `pass3-04` show the entire chain including the `DO_NOT_DEPLOY` node within one viewport. This also delivers the two-layer graph model the evidence design called for.

### 4. Band labels collided with column labels
**Found in:** `pass2-04` — "SYSTEM IMPACT" overlapped "CHANGE"; "DECISION PROOF" overlapped "FINDINGS" (6px apart).
**Fix:** `BAND_LABEL_H` 26 → 44, column labels to `bandY − 12`. **Verified** clean in `pass3-04`.

### 5. "Why this decision?" button was white-on-white — CRITICAL
**Found by measuring computed style**, not by eye: `color: rgb(245,245,247)` on `background: rgb(245,245,247)`. Cause: `.pillButton:hover` sets `color: var(--primary)`, which overrode `.pillButtonActive`'s dark text whenever the cursor rested on the active button — i.e. always, immediately after clicking it.
**Fix:** `.pillButtonActive:hover:not(:disabled){color:var(--base)}`.
**Verified:** re-measured `color: rgb(5,5,5)` on `rgb(245,245,247)`.

### 6. "Why this decision?" dimmed nothing — the signature interaction did not work
**Found by measuring the DOM:** `{ total: 17, dimmed: 0 }`. The dimming logic was correct, but on a real graph **every node is part of the verdict's ancestry**, so nothing recedes. The interaction was semantically right and experientially useless.
**Fix:** added an ordered **"WHY PREFLIGHT REACHED THIS VERDICT"** panel that lists the causal chain as numbered steps, built from the same `verdictChain` traversal over backend edges, sorted by the backend's own layer value.
**Verified:** `final-07-why-this-decision.png` renders a genuine forensic narrative — `01 CHANGE DROP_COLUMN "Column users.phone_number is removed." → 02 DATABASE phone_number → 03 SERVICE UserService → 04 API ProfileAPI → 05 API ProfileClient → 06 FINDING DROP_COLUMN → 07 FINDING BLAST-DOWNSTREAM-IMPACT "Indirect impact through DB_READ -> HTTP_CALL -> API_CONSUMES"`.

### 7. Mobile page overflowed horizontally
**Found in:** `pass2-18b-mobile-verdict.png` — text clipped on the right at 390px. **Measured:** `documentElement.scrollWidth = 727` vs viewport `390`, with `.commandCenter` reporting a 707px box. Cause: grid items default to `min-width:auto` and refuse to shrink below content min-content width.
**Fix:** `min-width:0` on `.report`/children plus wrapping rules for long SQL and hashes.
**Verified:** re-measured `scrollWidth: 390` — exactly the viewport. `final-18b` shows clean wrapping and no clipping.

### 8. Mobile scenario switcher rendered as a glaring white bar
**Found in:** `pass1-18b`. **Fix:** on ≤760px the active state uses `--surface-raised` with a border rather than the full-white desktop treatment.

### 9. "1 files discovered" pluralization
**Found in:** `pass2-10-unknown.png`. **Fix:** conditional singular/plural.

### 10. Cross-band edge noise
**Found in:** `pass2-04` — long dashed curves crossing the mid-band at the same weight as real dependency edges. **Fix:** cross-band edges rendered at 0.2 opacity vs 0.5 for in-band, dashed to distinguish them.

## Test-harness defect also found and fixed

`visual-qa.mjs` originally forced `window.scrollTo(0,0)` after uploads, which masked the very scroll-to-verdict behaviour under test — `pass2-10-unknown.png` showed the hero and I nearly recorded it as a product bug. Removed; the harness now captures the app's natural post-analysis position.

## Verification status

**VERIFIED (rendered and inspected, or measured in the live DOM):**
- Landing, destructive, safe, UNKNOWN, unsupported states at 1440×900
- Evidence graph layout, band separation, verdict node visibility
- "Why this decision?" ordered chain and button contrast
- Node hover and selection (17 interactive nodes confirmed present and clickable)
- Mobile 390×844 and tablet 768×1024 layout; zero page-level horizontal overflow
- Console cleanliness (1 static-asset 404, no JS errors)
- Scroll-to-verdict on completion

**PARTIALLY VERIFIED:**
- Animation *feel* — reveal cadence and easing were seen only as still frames, never as motion
- Reduced-motion path — implemented and code-gated, but not captured under an emulated `prefers-reduced-motion` browser
- Convergence visuals — the marker, banner, and detail panel are covered by backend tests and the fleet-ops payload, but the **fleet-ops convergence graph was never rendered in the browser**, because that case requires the two-ZIP comparison flow which the harness does not yet drive

**NOT VERIFIED:**
- Two-version comparison UI end-to-end in the browser
- Counterfactual morph (not implemented; unchanged from P0.7)
- Upload lifecycle stage display (not implemented; unchanged from P0.7)
- Judge mode (not implemented)
- Scroll-reveal choreography — CSS classes were added but are **not wired to an IntersectionObserver**, so sections do not currently animate on scroll
- Keyboard-only traversal of the full graph
- Performance profiling (no re-render or frame measurements taken)

## Automated gate — no regressions

```
python -m pytest -q                        -> 491 passed
python -m ruff check src/ tests/ scripts/  -> All checks passed
python -m mypy --strict src/preflight      -> Success: no issues found in 44 source files
npx tsc --noEmit                           -> clean
npx eslint app lib --max-warnings=0        -> clean
npx next build                             -> Compiled successfully
node scripts/api-integration.mjs           -> PASS (DO_NOT_DEPLOY 100 / SAFE 9, hashes unchanged)
node scripts/evidence-graph-contract.mjs   -> PASS
```

Decision hashes are byte-identical to previous turns: no frontend change altered analytical truth. `UNKNOWN` never renders as `SAFE`; unsupported repositories still produce zero fabricated entities.

## Honest assessment against the mission's own judge test

- *Understand the verdict within 2 seconds?* **Yes** — the page now opens on the verdict.
- *Understand why within 5 seconds?* **Yes** — the deterministic root cause sits directly under the headline.
- *Follow evidence → risk → policy → verdict?* **Yes** — two-band graph plus the ordered "why" chain.
- *Does the graph feel technically credible?* **Yes** — real entity names, hop distances, and source-located provenance.
- *Does it look like a student project?* In my judgement of the final screenshots, **no** — the dark editorial treatment, restrained accents, and tabular verdict read as an instrument. This remains **my** judgement of static frames, not a substitute for a human's.
- *Does anything feel fake?* **No** — every animation presents already-returned data; nothing fabricates progress.

I am **not** declaring this "world-class". Three of the mission's own requirements — scroll reveals, judge mode, upload lifecycle — are unimplemented, and convergence was never seen rendered. The interface is now genuinely defensible and free of the critical defects that made it unusable at the start of this turn, which is a materially different claim.

## Known limitations

- Scroll-reveal CSS exists but has no IntersectionObserver; sections do not animate in.
- The RISK→POLICY region draws every non-zero feature to every triggered rule (9 crossing edges), because `decide()` does not expose which feature fired which rule. Visually busy, but an honest over-approximation rather than a fabricated precise mapping.
- Long policy/finding labels truncate with an ellipsis in nodes (full text is in the inspector and the "why" chain).
- The fleet-ops convergence path needs harness support for the two-ZIP flow before it can be visually verified.
- `playwright` is now a devDependency (~for QA only; not shipped in the app bundle).
