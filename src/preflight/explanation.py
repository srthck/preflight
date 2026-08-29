"""Advisory explanation and remediation layer for deterministic decisions.

The decision report remains authoritative. Providers receive only the sanitized
structured input and may explain it, but cannot return a verdict or mutate it.
"""

from __future__ import annotations

import json
import re
from enum import Enum
from time import perf_counter
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from preflight.decision import (
    CompoundRisk,
    DecisionEvidence,
    DecisionReport,
    DecisionState,
    FindingSeverity,
    NormalizedFinding,
    RiskFeatures,
)


class ClaimType(str, Enum):
    PROVEN = "PROVEN"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


class RemediationPriority(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class GroundedClaim(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: str = Field(min_length=1)
    claim_type: ClaimType
    evidence_ids: tuple[str, ...] = ()


class RemediationStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    step_id: str = Field(min_length=1)
    priority: RemediationPriority
    action: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    affected_component: str = Field(min_length=1)
    verification: str = Field(min_length=1)
    provenance_ids: tuple[str, ...] = Field(min_length=1)


class ExplanationInput(BaseModel):
    """The only report-shaped data permitted to cross the AI boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(min_length=1)
    decision: DecisionState
    risk_score: int = Field(ge=0, le=100)
    base_risk: int = Field(ge=0, le=100)
    compound_adjustment: int = Field(ge=0)
    risk_features: RiskFeatures
    top_findings: tuple[NormalizedFinding, ...] = ()
    # Computed by AIContextSanitizer from the FULL finding list (never from
    # top_findings, which is capped at 5 and could truncate the very marker
    # that proves blast radius didn't run) — see DAY_P0.2 forensics.
    blast_radius_available: bool = True
    blast_radius_affected_count: int = Field(default=0, ge=0)
    compound_risks: tuple[CompoundRisk, ...] = ()
    policy_rules: tuple[str, ...] = ()
    affected_entities: tuple[str, ...] = ()
    evidence_chain: tuple[DecisionEvidence, ...] = ()
    unknowns: tuple[str, ...] = ()
    recommendations: tuple[str, ...] = ()


class ExplanationResponse(BaseModel):
    """Strict advisory output. Deliberately has no decision or risk fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(min_length=1)
    executive_summary: str = Field(min_length=1)
    verdict_explanation: str = Field(min_length=1)
    top_risks: tuple[GroundedClaim, ...] = ()
    evidence_summary: tuple[GroundedClaim, ...] = ()
    blast_radius_summary: str = Field(min_length=1)
    rollback_summary: str = Field(min_length=1)
    deployment_summary: str = Field(min_length=1)
    uncertainty_summary: str = Field(min_length=1)
    remediation_plan: tuple[RemediationStep, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)


class ExplanationQuality(str, Enum):
    FULL_AI = "FULL_AI"
    DETERMINISTIC_FALLBACK = "DETERMINISTIC_FALLBACK"
    AI_UNAVAILABLE = "AI_UNAVAILABLE"


class ExplanationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quality: ExplanationQuality
    response: ExplanationResponse | None = None
    error: str | None = None
    preparation_ms: float = Field(ge=0)
    provider_ms: float = Field(ge=0)
    validation_ms: float = Field(ge=0)
    total_ms: float = Field(ge=0)


_SECRET_KEY = re.compile(
    r"(?i)(api[_-]?key|access[_-]?key|secret|password|passwd|token|authorization|credential)"
)
_SECRET_VALUE = re.compile(
    r"(?i)(bearer\s+[A-Za-z0-9._~+/=-]+|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9._-]+\.[A-Za-z0-9._-]+)"
)
_CONNECTION = re.compile(r"(?i)\b(?:postgres|mysql|mongodb(?:\+srv)?|redis)://[^\s]+")


def _sanitize(value: Any, *, key: str = "") -> Any:  # noqa: ANN401
    if _SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _sanitize(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        value = _SECRET_VALUE.sub("[REDACTED]", value)
        return _CONNECTION.sub("[REDACTED]", value)
    return value


class AIContextSanitizer:
    """Convert a report into structured, recursively sanitized AI context."""

    def sanitize(self, report: DecisionReport) -> ExplanationInput:
        blast_radius_available = not any(
            f.rule_id == "ANALYZER-UNAVAILABLE" and f.source_module == "blast_radius"
            for f in report.findings
        )
        blast_radius_affected_count = len(
            {
                entity
                for f in report.findings
                if f.category.value == "BLAST_RADIUS"
                for entity in f.affected_entities
            }
        )
        payload = {
            "schema_version": report.schema_version,
            "decision": report.decision,
            "risk_score": report.risk_score,
            "base_risk": report.base_risk,
            "compound_adjustment": report.compound_adjustment,
            "risk_features": report.risk_features,
            "top_findings": report.findings[:5],
            "blast_radius_available": blast_radius_available,
            "blast_radius_affected_count": blast_radius_affected_count,
            "compound_risks": report.compound_risks,
            "policy_rules": report.policy_rules_triggered,
            "affected_entities": report.affected_entities,
            "evidence_chain": report.evidence_chain,
            "unknowns": report.unknowns,
            "recommendations": report.recommendations,
        }
        return ExplanationInput.model_validate(_sanitize(_dump(payload)))


def _dump(value: Any) -> Any:  # noqa: ANN401
    if isinstance(value, BaseModel):
        return _dump(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {key: _dump(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_dump(item) for item in value]
    return value


class ExplanationProvider(Protocol):
    def explain(self, input: ExplanationInput) -> ExplanationResponse: ...


def _priority(severity: FindingSeverity) -> RemediationPriority:
    return {
        FindingSeverity.CRITICAL: RemediationPriority.CRITICAL,
        FindingSeverity.HIGH: RemediationPriority.HIGH,
        FindingSeverity.MEDIUM: RemediationPriority.MEDIUM,
    }.get(severity, RemediationPriority.LOW)


def _blast_radius_summary(input: ExplanationInput) -> str:
    """Ground the blast-radius sentence in the real, category-scoped result.

    Never derived from ``risk_features.affected_entity_count`` — that field
    is a decision-wide union across every finding category (deployment,
    rollback, blast radius) and can include entities unrelated to blast
    radius, or be nonzero even when blast radius itself never ran. See
    DAY_P0.2 forensics for the observed contradiction this replaces.
    """
    if not input.blast_radius_available:
        return "Blast radius could not be established because required evidence was unavailable."
    if input.blast_radius_affected_count == 0:
        return "Blast radius was analyzed: zero downstream dependents were found."
    count = input.blast_radius_affected_count
    unit = "entity" if count == 1 else "entities"
    return f"{count} affected {unit} identified by blast-radius analysis."


class DeterministicExplanationProvider:
    def explain(self, input: ExplanationInput) -> ExplanationResponse:
        findings = tuple(
            sorted(
                input.top_findings,
                key=lambda item: (item.severity.value, item.finding_id),
                reverse=True,
            )
        )
        risks = tuple(
            GroundedClaim(
                claim=f"{finding.title}: {finding.description}",
                claim_type=ClaimType.UNKNOWN if finding.uncertainty else ClaimType.PROVEN,
                evidence_ids=(finding.finding_id,),
            )
            for finding in findings
        )
        steps = remediation_for(input)
        rollback = (
            "UNSAFE"
            if input.risk_features.rollback_unsafety >= 1
            else "No rollback unsafety was proven."
        )
        blast_radius = _blast_radius_summary(input)
        return ExplanationResponse(
            schema_version="1.0",
            executive_summary=(
                f"PreFlight decision: {input.decision.value} ({input.risk_score}/100)."
            ),
            verdict_explanation=(
                f"The deterministic policy selected {input.decision.value}; "
                "this explanation is advisory."
            ),
            top_risks=risks,
            evidence_summary=tuple(
                GroundedClaim(
                    claim=f"{item.source} -> {item.target}: {item.value}",
                    claim_type=ClaimType.PROVEN,
                    evidence_ids=(item.source,),
                )
                for item in input.evidence_chain
            ),
            blast_radius_summary=blast_radius,
            rollback_summary=rollback,
            deployment_summary=(
                f"{input.risk_features.destructive_change_count} destructive database "
                "changes detected."
            ),
            uncertainty_summary="; ".join(input.unknowns)
            if input.unknowns
            else "No unknowns were recorded.",
            remediation_plan=steps,
            confidence=1.0,
        )


def remediation_for(input: ExplanationInput) -> tuple[RemediationStep, ...]:
    steps: list[RemediationStep] = []
    for finding in input.top_findings:
        if finding.rule_id in {"DROP_COLUMN", "DROP_TABLE"}:
            provenance = (finding.finding_id,)
            steps.extend(
                (
                    RemediationStep(
                        step_id=f"{finding.finding_id}:expand",
                        priority=_priority(finding.severity),
                        action=(
                            "Replace the destructive migration with an expand-and-contract "
                            "sequence."
                        ),
                        rationale="Preserve compatibility while consumers migrate.",
                        affected_component=finding.affected_entities[0]
                        if finding.affected_entities
                        else "database",
                        verification="Validate the migration rehearsal and dependency graph.",
                        provenance_ids=provenance,
                    ),
                    RemediationStep(
                        step_id=f"{finding.finding_id}:verify",
                        priority=RemediationPriority.HIGH,
                        action="Deploy consumers that no longer depend on the removed field.",
                        rationale=(
                            "The old application dependency must be cleared before contraction."
                        ),
                        affected_component=finding.affected_entities[0]
                        if finding.affected_entities
                        else "application",
                        verification="Re-run contract and rollback analysis.",
                        provenance_ids=provenance,
                    ),
                )
            )
    for rule in input.policy_rules:
        if not steps and rule:
            steps.append(
                RemediationStep(
                    step_id=f"policy:{rule}",
                    priority=RemediationPriority.HIGH,
                    action="Resolve the policy-triggering evidence before deployment.",
                    rationale="The deterministic policy marked this report for review.",
                    affected_component="analyzed scope",
                    verification="Re-run PreFlight and confirm the policy rule clears.",
                    provenance_ids=(rule,),
                )
            )
    return tuple(
        sorted(
            steps, key=lambda item: (list(RemediationPriority).index(item.priority), item.step_id)
        )
    )


class LLMExplanationProvider:
    """Vendor-neutral adapter; callers supply a configured JSON callable."""

    def __init__(self, complete: Any) -> None:  # noqa: ANN401
        self._complete = complete

    def explain(self, input: ExplanationInput) -> ExplanationResponse:
        raw = self._complete(json.dumps(input.model_dump(mode="json"), sort_keys=True))
        if isinstance(raw, str):
            raw = json.loads(raw)
        return ExplanationResponse.model_validate(raw)


def _validate_advisory(response: ExplanationResponse, context: ExplanationInput) -> None:
    serialized = json.dumps(response.model_dump(mode="json"), sort_keys=True)
    if (
        _SECRET_KEY.search(serialized)
        or _SECRET_VALUE.search(serialized)
        or _CONNECTION.search(serialized)
    ):
        raise ValueError("secret detected in explanation output")
    evidence_ids = {finding.finding_id for finding in context.top_findings}
    evidence_ids.update(item.source for item in context.evidence_chain)
    for claim in (*response.top_risks, *response.evidence_summary):
        if not set(claim.evidence_ids).issubset(evidence_ids):
            raise ValueError("explanation claim is not grounded in report evidence")
    entities = set(context.affected_entities)
    for step in response.remediation_plan:
        if step.affected_component not in entities and step.affected_component not in {
            "database",
            "application",
            "analyzed scope",
        }:
            raise ValueError("remediation references an unknown component")


def explain(
    report: DecisionReport, provider: ExplanationProvider | None = None
) -> ExplanationResult:
    started = perf_counter()
    prep_started = perf_counter()
    context = AIContextSanitizer().sanitize(report)
    preparation_ms = (perf_counter() - prep_started) * 1000
    provider_started = perf_counter()
    selected = provider or DeterministicExplanationProvider()
    validation_started = perf_counter()
    validation_ms = 0.0
    try:
        response = selected.explain(context)
        validation_started = perf_counter()
        _validate_advisory(response, context)
        if response.schema_version != context.schema_version:
            raise ValueError("explanation schema version mismatch")
        if response.confidence > 1:
            raise ValueError("invalid confidence")
        validation_ms = (perf_counter() - validation_started) * 1000
        quality = (
            ExplanationQuality.DETERMINISTIC_FALLBACK
            if provider is None
            else ExplanationQuality.FULL_AI
        )
        error = None
    except (
        ValueError,
        TypeError,
        KeyError,
        TimeoutError,
        RuntimeError,
        json.JSONDecodeError,
        ValidationError,
    ) as exc:
        response = None
        quality = (
            ExplanationQuality.AI_UNAVAILABLE
            if provider is not None
            else ExplanationQuality.DETERMINISTIC_FALLBACK
        )
        error = "AI_EXPLANATION_UNAVAILABLE: " + type(exc).__name__
    provider_ms = (perf_counter() - provider_started) * 1000
    total_ms = (perf_counter() - started) * 1000
    return ExplanationResult(
        quality=quality,
        response=response,
        error=error,
        preparation_ms=preparation_ms,
        provider_ms=provider_ms,
        validation_ms=validation_ms,
        total_ms=total_ms,
    )


__all__ = [
    "AIContextSanitizer",
    "ClaimType",
    "DeterministicExplanationProvider",
    "ExplanationInput",
    "ExplanationProvider",
    "ExplanationQuality",
    "ExplanationResponse",
    "ExplanationResult",
    "GroundedClaim",
    "LLMExplanationProvider",
    "RemediationPriority",
    "RemediationStep",
    "explain",
    "remediation_for",
]
