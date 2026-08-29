# PRE·FLIGHT DESIGN SYSTEM TRANSFORMATION — ADDENDUM

This is a focused addendum to `DAY_P0_FRONTEND_PROOF_ENGINE_REPORT.md`, which
already covers the functional audit (backend contract, what was thrown away,
what was newly exposed). Nothing in this pass touched backend code, API
fields, or data truth — this turn was the visual/interaction system on top
of that already-real foundation. No new audit was needed because nothing
structural changed since the last one.

## What changed

**Design tokens** (`app/globals.css`) — replaced the prior dark-green
palette with the specified restrained system: base `#050505`, surface
`#0b0b0d`, primary text `#f5f5f7`, secondary `#86868b`, borders at
`rgba(255,255,255,.04)`, and muted (not neon) safe/danger/warn tones. A
single `--ease: cubic-bezier(0.2,0.9,0.2,1)` token now drives every
transition in the app.

**Typography** — hero `clamp(40px,7vw,76px)` at weight 600, line-height
1.02, tight tracking; section headings 30px/weight 500; body 15–18px;
metadata uppercase with `.14em` tracking. Hierarchy now comes from type
scale and spacing, not from box borders.

**Navigation** — collapsed to the specified three zones: `PRE·FLIGHT` /
`Analysis · Evidence · Architecture` / `ENGINE ● <status> · GitHub ↗`. The
engine-status pill is not asserted — it performs a real `GET /health` on
mount and shows `CHECKING` → `READY`/`UNREACHABLE` based on the actual
response, never a hardcoded "online."

**Hero** — reduced to the literal spec: eyebrow, headline, one sentence,
one CTA (`Analyze a change →`), one metadata line
(`TREE-SITTER · SQLGLOT · OPENAPI · DETERMINISTIC ENGINE`). No dashboard is
visible before the first analysis runs.

**Staged analysis sequence** — replaces the old spinner with the five
specified stages (`READING SOURCE`, `BUILDING DEPENDENCY GRAPH`,
`REHEARSING MIGRATION`, `CHECKING ROLLBACK`, `APPLYING POLICY`), advanced
by a 170ms interval while the real `/api/analyze` call runs in parallel.
This is an honest pacing choice, not fabricated latency: the real request
starts immediately, the total added wait is capped at 850ms
(5 × 170ms — the same budget the motion spec allots to a staged reveal),
and nothing in the UI claims the analysis itself took that long — the
per-stage timing is never displayed as a number. Under
`prefers-reduced-motion`, the interval is skipped entirely and the result
appears as soon as the real response arrives.

**Verdict copy** — `decisionLabel()` appends a period only to
`DO NOT DEPLOY.` (per the spec's exact example); other verdicts render as
bare words. The one-line root-cause sentence under the verdict now prefers,
in order: a blocking `ROLLBACK`-category finding's real `reason` text, then
any blocking finding's description, then the AI's executive summary, then
the deterministic recommendation string — the deterministic layer's own
words are preferred over the AI's paraphrase, consistent with "the engine
decides, the AI explains."

**Section copy** aligned to the brief throughout: "Blast radius / Causal
dependency graph," "Rollback truth / Deployment time machine,"
"What if? / Same engine. Different real change.," "Explanation layer /
Advisory · non-authoritative," "Database rehearsal," "Analysis coverage."
The counterfactual panel now shows "The verdict changed because the
evidence changed" — but only when the two real runs actually produced
different decisions, computed from the two live results, not asserted
unconditionally.

**Motion** — every existing transition (disclosure chevrons, node
selection, panel reveals, hover states) now uses the specified
`cubic-bezier(0.2,0.9,0.2,1)` easing and 180–420ms/600–900ms budgets; the
existing global `prefers-reduced-motion` rule (added last turn) still zeros
out all animation durations, and the staged-analysis sequence additionally
skips its own interval-driven reveal under that same media query rather
than relying on the CSS-only fallback alone.

**Accessibility** — added a visually-hidden `aria-live="polite"` status
region announcing pipeline start/completion/failure (screen-reader users
get the staged sequence's outcome even though the visual list is
`aria-hidden` for them); focus-visible outlines now use the primary token
consistently; all interactive elements remain real `<button>`/`<a>`
elements (unchanged from last turn — already true).

## What did not change (deliberately)

- **No component-folder reorganization** into the suggested
  `components/hero/`, `components/verdict/`, etc. nesting. The brief
  explicitly allows this ("the exact structure may differ if the existing
  project has a better architecture"); the existing flat, focused
  `app/components/*.tsx` set (one component per concern, no giant page
  component) already satisfies the actual requirement. Reorganizing files
  with no behavior change was judged lower value than the visual/motion
  work above, given the size of this task.
- **No graph visualization library** (React Flow, Canvas/WebGL). The blast
  radius graph is 3–7 nodes; the brief itself says not to load a heavy
  visualization library when graph size doesn't justify it. The existing
  hierarchical column layout (built from real `hop_distance` data) stays.
- **`lib/validation.ts` / `lib/formatting.ts` split** not done — `lib/api.ts`
  already centralizes all fetch calls and runtime validation (the brief's
  actual requirement: "centralize API access, do not scatter fetch calls");
  splitting one file into three with identical behavior was deprioritized
  under the same reasoning as the component reorg.
- Nothing about capabilities changed: still no camera, voice, Office Kit,
  on-device/NPU claim anywhere — the anti-fabrication section of this brief
  restates the same constraint already honored last turn.

## Verification

```
$ cd frontend && npx tsc --noEmit -p tsconfig.json   # clean
$ npm run lint                                        # clean
$ npm run build                                       # ✓ compiled, ✓ static pages, 0 warnings
$ NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 node scripts/api-integration.mjs
Frontend API integration: PASS
  destructive -> DO_NOT_DEPLOY (100/100, 9a0d8eb4...)
  safe        -> SAFE (9/100, e76e6fe4...)

$ PYTHONPATH=src python -m pytest tests/ -q            # 378 passed (backend untouched)
```

Every CSS class referenced from a component was cross-checked against the
stylesheet mechanically (extracted every `styles.xxx` / `styles[\`xxx\`]`
usage from all `.tsx` files and diffed against every defined selector) —
one true gap (`.explanation`) was found and fixed before the build was
declared clean, rather than relying on the build alone to catch it.

**Visual QA remains PARTIAL, as in the last report.** No headless-browser
tool is available in this environment, so no screenshot of the populated,
restyled report was captured this turn either. What's verified: the
production build renders the server-side (empty-state) shell without
error, the hero copy is confirmed present in the served HTML, both
scenarios round-trip through the live API with the new client, and every
class reference resolves. Actual rendered layout, spacing rhythm, and
motion feel at each breakpoint are unverified by a real browser — opening
`http://localhost:3000` yourself remains the fastest way to close that gap.
