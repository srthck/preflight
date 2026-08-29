# Day 8: Deterministic Policy and Risk Decision Engine

Day 8 unifies the structured outputs of Days 3-7. It does not parse source, SQL, or OpenAPI documents and contains no LLM decision path.

## Pipeline

```text
existing analyzers -> NormalizedFinding -> RiskFeatures -> CompoundRisk
                   -> published risk formula -> Policy Engine -> DecisionReport
```

`NormalizedFinding` preserves the originating module, rule ID, severity,
confidence, affected entities, evidence, provenance, blocking state, and
uncertainty. Findings are sorted canonically before feature extraction.

## Risk formula

All three components are normalized to `[0, 1]`:

```text
base_risk = round(100 * (
    0.40 * blast_severity +
    0.35 * deployment_severity +
    0.25 * rollback_unsafety
))
```

Blast severity reuses Day 4's published path severity, including its edge
weights and hop decay. Deployment severity is derived from structured Day 5 and
Day 6 severities. Rollback unsafety is derived from Day 7 statuses. The score is
an engineering prioritization score, not a probability.

Compound risks are explicit. For example, destructive database evidence plus
`RB-SCHEMA-REMOVED-OLD-DEPENDENCY` activates `COMPOUND-ROLLBACK-SCHEMA` and its
multiplier. The report exposes `base_risk`, `compound_multiplier`, and
`compound_adjustment`; no adjustment is hidden.

## Policy states

The policy engine emits only `SAFE`, `CAUTION`, `DO_NOT_DEPLOY`, or `UNKNOWN`.
Confirmed critical blocking findings, unsafe rollback with destructive change,
and risk at least 70 block deployment. Risk from 40 through 69 produces
caution. Missing analyzer evidence, unresolved dynamic references, or unknown
rollback evidence produces `UNKNOWN` unless a confirmed blocking failure has
already made the decision `DO_NOT_DEPLOY`. Empty analysis is `UNKNOWN`, not
proof of safety.

## Evidence graph and AI boundary

`DecisionEvidence` nodes connect finding rule to risk feature, risk feature to
base risk, compound risk to adjustment, and policy rule to verdict. A future
explanation adapter may receive `DecisionExplanationInput`, which contains only
structured decision data. It cannot mutate `DecisionReport.decision` and is not
required for analysis.

## Security, determinism, and failure isolation

The decision layer receives redacted upstream evidence. Canonical JSON excludes
the existing hash and uses sorted keys and collections; `decision_sha256()` is
stable across equivalent finding orderings and repeated analyses. Unavailable
components become explicit unknown findings rather than a safe result.

The CLI accepts a normalized JSON analysis envelope:

```text
python scripts/preflight_decide.py --analysis analysis.json --json
```

## Canonical example

The old application depends on `users.phone_number`, the new migration drops
that column, and the new application no longer uses it. Day 7 reports forward
compatibility `SAFE` and rollback compatibility `UNSAFE`. Day 8 preserves both
facts, raises rollback and deployment features, activates the compound rollback
rule, and emits `DO_NOT_DEPLOY` with an evidence chain explaining that forward
deployment may succeed while rollback is unsafe.

Static analysis cannot prove arbitrary runtime behavior. Dynamic SQL,
reflection, generated code, external state, incomplete dependency extraction,
and unsupported analyzer constructs remain limitations.
