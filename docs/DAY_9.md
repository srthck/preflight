# Day 9: Safe Explanation and Remediation

## Boundary

The Day 8 `DecisionReport` is authoritative. `AIContextSanitizer` converts it into the strict, structured `ExplanationInput`; source code, comments, filenames, API descriptions, migration notes, and evidence values are untrusted project content and are **data only**, never instructions. No raw repository source, full diff, environment credentials, or arbitrary files cross this boundary.

The response contract is `ExplanationResponse`. It intentionally has no `decision`, `risk_score`, policy, severity, rollback, or deterministic-hash field. A provider can explain evidence, but cannot authorize deployment or change the report. Extra fields, malformed JSON, ungrounded evidence references, unknown components, and secret-bearing output are rejected.

## Claims and Remediation

`GroundedClaim` labels every claim `PROVEN`, `INFERRED`, or `UNKNOWN` and carries evidence IDs. The deterministic fallback only emits claims from normalized findings and the evidence chain. Remediation steps contain a stable ID, priority, action, rationale, affected component, verification, and provenance IDs. Destructive schema changes recommend expand-and-contract sequencing; they do not generate or execute production SQL.

Priorities are deterministic: `CRITICAL`, `HIGH`, `MEDIUM`, then `LOW`. A critical step can only originate from a critical finding. Remediation is advisory and must be verified by rerunning PreFlight.

## Providers and Failure Modes

`ExplanationProvider` is vendor-neutral. `DeterministicExplanationProvider` is always available. `LLMExplanationProvider` accepts an externally configured completion callable; no vendor SDK or API key is hardcoded. There is no claim of local or on-device inference.

`explain()` measures input preparation, provider execution, validation, and total latency. A timeout, unavailable provider, malformed response, missing field, contradictory `decision` field, secret, hallucinated entity, or ungrounded claim produces `AI_UNAVAILABLE` while preserving the original deterministic report. Without a provider, the result is `DETERMINISTIC_FALLBACK`.

## Security Threat Model

| ID | Threat | Impact | Mitigation | Residual risk |
|---|---|---|---|---|
| T1 | Injection in source comments | Misleading explanation | Structured input; project content is data only | Models may still phrase data misleadingly |
| T2 | Injection in OpenAPI descriptions | Same | No instruction channel; grounded claims | Unsupported descriptions remain unknown |
| T3 | Injection in migration comments | Unsafe advice | Comments are not decision authority | Provider may be unavailable |
| T4 | Secret leakage | Credential disclosure | Recursive key/value redaction before provider and output scanning | Novel secret formats may evade patterns |
| T5 | Hallucinated entities | False impact | Entity and provenance containment checks | Ambiguous natural language is possible |
| T6 | Hallucinated remediation | Unsafe change | Deterministic remediation and provenance requirements | Verification is still required |
| T7 | Verdict override | Unauthorized deployment | Response has no authoritative decision field; report remains immutable | Consumers must display report verdict |
| T8 | Provider compromise | Malicious or leaked output | Strict schema, redaction, grounding, and failure fallback | Provider sees sanitized evidence |
| T9 | Malformed output | Broken developer UX | Pydantic validation and bounded failure | No automatic retry |
| T10 | Provider unavailability | Missing explanation | Deterministic fallback | Fallback is less conversational |

## Determinism and Tests

The fallback response contains no clock values. Identical input produces identical serialized output; the focused test runs it ten times. Day 8's deterministic hash remains unchanged. The Day 9 focused suite covers safe, caution, blocked, unknown, destructive schema, rollback, compound risk, injection, redaction, malformed output, missing fields, contradiction, hallucination, unavailable providers, remediation provenance, ordering, and hash/verdict preservation.

## Limitations

This layer does not prove runtime safety, execute SQL, modify files, authorize deployments, or infer dependencies outside the deterministic analyzer's evidence. Secret redaction uses conservative key and common-token patterns, so additional deployment controls are required. A real LLM provider, network policy, authentication, and production latency budget remain deployment concerns.
