"""Deterministic risk and policy decision engine for PreFlight Day 8."""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from preflight.api_contract import APIContractFinding
from preflight.domain.blast_radius import BlastRadiusReport
from preflight.rollback_truth import RollbackFinding, RollbackReport, RollbackStatus
from preflight.schema import DeploymentFinding


class DecisionState(str, Enum):
    SAFE = "SAFE"
    CAUTION = "CAUTION"
    DO_NOT_DEPLOY = "DO_NOT_DEPLOY"
    UNKNOWN = "UNKNOWN"


class FindingCategory(str, Enum):
    BLAST_RADIUS = "BLAST_RADIUS"
    SCHEMA = "SCHEMA"
    DATABASE = "DATABASE"
    API_CONTRACT = "API_CONTRACT"
    ROLLBACK = "ROLLBACK"
    CONFIGURATION = "CONFIGURATION"
    SEMANTIC = "SEMANTIC"
    DYNAMIC_REFERENCE = "DYNAMIC_REFERENCE"
    AMBIGUITY = "AMBIGUITY"


class FindingSeverity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class NormalizedFinding(BaseModel):
    """Common finding contract consumed by risk and policy evaluation."""

    model_config = {"frozen": True}

    finding_id: str = Field(..., min_length=1)
    category: FindingCategory
    severity: FindingSeverity
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    rule_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    affected_entities: tuple[str, ...] = Field(default_factory=tuple)
    evidence: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    provenance: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    source_module: str = Field(..., min_length=1)
    blocking: bool = False
    uncertainty: str | None = None
    direct: bool = True

    @model_validator(mode="after")
    def _sort_content(self) -> NormalizedFinding:
        object.__setattr__(self, "affected_entities", tuple(sorted(set(self.affected_entities))))
        object.__setattr__(
            self,
            "evidence",
            tuple(sorted((_redact(item) for item in self.evidence), key=_canonical_json)),
        )
        object.__setattr__(
            self,
            "provenance",
            tuple(sorted((_redact(item) for item in self.provenance), key=_canonical_json)),
        )
        return self


class RiskFeatures(BaseModel):
    model_config = {"frozen": True}

    blast_severity: float = Field(ge=0.0, le=1.0)
    deployment_severity: float = Field(ge=0.0, le=1.0)
    rollback_unsafety: float = Field(ge=0.0, le=1.0)
    critical_dependency_count: int = Field(ge=0)
    high_dependency_count: int = Field(ge=0)
    destructive_change_count: int = Field(ge=0)
    breaking_api_count: int = Field(ge=0)
    rollback_violation_count: int = Field(ge=0)
    unknown_finding_count: int = Field(ge=0)
    ambiguity_count: int = Field(ge=0)
    unresolved_reference_count: int = Field(ge=0)
    affected_entity_count: int = Field(ge=0)
    max_dependency_hops: int = Field(ge=0)
    compound_failure_count: int = Field(ge=0)


class CompoundRisk(BaseModel):
    model_config = {"frozen": True}

    id: str
    rules_triggered: tuple[str, ...]
    affected_entities: tuple[str, ...]
    severity: FindingSeverity
    multiplier: float = Field(gt=1.0)
    evidence: tuple[dict[str, Any], ...] = Field(default_factory=tuple)


class DecisionEvidence(BaseModel):
    model_config = {"frozen": True}

    source: str
    target: str
    relation: str
    value: str


class DecisionReport(BaseModel):
    model_config = {"frozen": True}

    schema_version: str = "1.0"
    decision: DecisionState
    risk_score: int = Field(ge=0, le=100)
    base_risk: int = Field(ge=0, le=100)
    compound_adjustment: int = Field(ge=0)
    compound_multiplier: float = Field(ge=1.0)
    risk_features: RiskFeatures
    findings: tuple[NormalizedFinding, ...] = Field(default_factory=tuple)
    compound_risks: tuple[CompoundRisk, ...] = Field(default_factory=tuple)
    policy_rules_triggered: tuple[str, ...] = Field(default_factory=tuple)
    affected_entities: tuple[str, ...] = Field(default_factory=tuple)
    evidence_chain: tuple[DecisionEvidence, ...] = Field(default_factory=tuple)
    unknowns: tuple[str, ...] = Field(default_factory=tuple)
    recommendations: tuple[str, ...] = Field(default_factory=tuple)
    deterministic_hash: str = ""

    def with_hash(self) -> DecisionReport:
        digest = hashlib.sha256(canonical_decision_json(self).encode("utf-8")).hexdigest()
        return self.model_copy(update={"deterministic_hash": digest})


class DecisionExplanationInput(BaseModel):
    """Structured-only future explanation input; it cannot change the verdict."""

    model_config = {"frozen": True}

    decision: DecisionState
    risk_score: int
    risk_features: RiskFeatures
    findings: tuple[NormalizedFinding, ...]
    evidence_chain: tuple[DecisionEvidence, ...]
    policy_rules: tuple[str, ...]
    recommendations: tuple[str, ...]


class DecisionRequest(BaseModel):
    """Inputs from existing analyzers or already-normalized findings."""

    model_config = {"frozen": True}

    findings: tuple[NormalizedFinding, ...] = Field(default_factory=tuple)
    blast_radius: BlastRadiusReport | None = None
    deployment_findings: tuple[DeploymentFinding, ...] = Field(default_factory=tuple)
    api_contract: APIContractFinding | None = None
    rollback: RollbackReport | None = None
    unavailable_components: tuple[str, ...] = Field(default_factory=tuple)


_SEVERITY_VALUE = {
    FindingSeverity.INFO: 0.0,
    FindingSeverity.LOW: 0.25,
    FindingSeverity.MEDIUM: 0.5,
    FindingSeverity.HIGH: 0.75,
    FindingSeverity.CRITICAL: 1.0,
}


def normalize_findings(request: DecisionRequest) -> tuple[NormalizedFinding, ...]:
    findings = list(request.findings)
    if request.blast_radius:
        for index, blast_finding in enumerate(request.blast_radius.findings):
            findings.append(
                NormalizedFinding(
                    finding_id=f"blast:{blast_finding.affected_entity}:{index}",
                    category=FindingCategory.BLAST_RADIUS,
                    severity=_severity_from_score(blast_finding.severity),
                    confidence=1.0,
                    rule_id="BLAST-DOWNSTREAM-IMPACT",
                    title="Downstream dependency impact",
                    description=blast_finding.reason,
                    affected_entities=(blast_finding.affected_entity,),
                    evidence=blast_finding.path.evidence,
                    source_module="blast_radius",
                    direct=blast_finding.hop_distance == 1,
                )
            )
    for deployment_finding in request.deployment_findings:
        findings.append(
            NormalizedFinding(
                finding_id=deployment_finding.finding_id,
                category=FindingCategory.DATABASE,
                severity=_severity_from_text(deployment_finding.severity),
                confidence=1.0 if deployment_finding.deployment_status != "UNKNOWN" else 0.5,
                rule_id=deployment_finding.change,
                title=deployment_finding.change,
                description=deployment_finding.explanation_key,
                # "UNKNOWN" is DeploymentAnalyzer's placeholder schema_object for
                # PARSE_ERROR/NO_CHANGE — it never identifies a real entity, so it
                # must never be counted as one (see DAY_P0.2 forensics).
                affected_entities=()
                if deployment_finding.schema_object == "UNKNOWN"
                else (deployment_finding.schema_object,),
                evidence=tuple(_pairs_to_dicts(deployment_finding.evidence)),
                source_module="deployment_rehearsal",
                blocking=deployment_finding.deployment_status == "UNSAFE",
                uncertainty=None
                if deployment_finding.deployment_status != "UNKNOWN"
                else "deployment status is unknown",
            )
        )
    if request.api_contract:
        for index, api_change in enumerate(request.api_contract.changes):
            findings.append(
                NormalizedFinding(
                    finding_id=f"api:{api_change.rule_id}:{index}",
                    category=FindingCategory.API_CONTRACT,
                    severity=_severity_from_text(api_change.severity),
                    confidence=1.0,
                    rule_id=api_change.rule_id,
                    title=api_change.rule_id,
                    description=api_change.reason,
                    affected_entities=(f"{api_change.method} {api_change.path}",),
                    evidence=(
                        {
                            "location": api_change.location,
                            "before": api_change.before,
                            "after": api_change.after,
                        },
                    ),
                    source_module="api_contract",
                    blocking=api_change.compatibility.value == "BREAKING",
                )
            )
    if request.rollback:
        for rollback_finding in request.rollback.findings:
            findings.append(_rollback_normalized(rollback_finding))
        if request.rollback.status == RollbackStatus.UNKNOWN and not any(
            finding.category == FindingCategory.ROLLBACK for finding in findings
        ):
            findings.append(
                NormalizedFinding(
                    finding_id="rollback:unknown",
                    category=FindingCategory.ROLLBACK,
                    severity=FindingSeverity.MEDIUM,
                    confidence=0.0,
                    rule_id="RB-UNKNOWN",
                    title="Rollback evidence unavailable",
                    description="Rollback compatibility could not be established.",
                    source_module="rollback_truth",
                    uncertainty="rollback evidence is unavailable",
                )
            )
    for component in request.unavailable_components:
        findings.append(
            NormalizedFinding(
                finding_id=f"missing:{component}",
                category=FindingCategory.DYNAMIC_REFERENCE,
                severity=FindingSeverity.MEDIUM,
                confidence=0.0,
                rule_id="ANALYZER-UNAVAILABLE",
                title=f"{component} unavailable",
                description="An analyzer did not provide its evidence.",
                source_module=component,
                uncertainty="required analyzer unavailable",
            )
        )
    return tuple(
        sorted(findings, key=lambda item: (item.category.value, item.rule_id, item.finding_id))
    )


def decide(request: DecisionRequest) -> DecisionReport:
    findings = normalize_findings(request)
    if not findings and not request.unavailable_components:
        findings = (
            NormalizedFinding(
                finding_id="analysis:no-evidence",
                category=FindingCategory.DYNAMIC_REFERENCE,
                severity=FindingSeverity.INFO,
                confidence=0.0,
                rule_id="NO_ANALYSIS_EVIDENCE",
                title="No analysis evidence",
                description="No analyzer findings or completed evidence were supplied.",
                source_module="decision_engine",
                uncertainty="analysis evidence is unavailable",
            ),
        )
    compounds = _compound_risks(findings)
    features = _features(findings, compounds, request.blast_radius)
    base_risk = round(
        100
        * (
            0.40 * features.blast_severity
            + 0.35 * features.deployment_severity
            + 0.25 * features.rollback_unsafety
        )
    )
    multiplier = 1.0
    for compound in compounds:
        multiplier *= compound.multiplier
    multiplier = round(min(multiplier, 1.5), 6)
    final_risk = min(100, round(base_risk * multiplier))
    policy_rules, decision = _policy(findings, features, final_risk)
    unknowns = tuple(
        sorted(f.uncertainty or f.rule_id for f in findings if f.uncertainty or f.confidence == 0.0)
    )
    affected = tuple(
        sorted({entity for finding in findings for entity in finding.affected_entities})
    )
    chain = _evidence_chain(findings, features, compounds, policy_rules, decision)
    report = DecisionReport(
        decision=decision,
        risk_score=final_risk,
        base_risk=base_risk,
        compound_adjustment=final_risk - base_risk,
        compound_multiplier=multiplier,
        risk_features=features,
        findings=findings,
        compound_risks=tuple(compounds),
        policy_rules_triggered=tuple(policy_rules),
        affected_entities=affected,
        evidence_chain=tuple(chain),
        unknowns=unknowns,
        recommendations=_recommendations(decision, features),
    )
    return report.with_hash()


def decision_sha256(report: DecisionReport) -> str:
    return hashlib.sha256(canonical_decision_json(report).encode("utf-8")).hexdigest()


def canonical_decision_json(report: DecisionReport) -> str:
    return _canonical_json(report.model_dump(mode="json", exclude={"deterministic_hash"}))


def _features(
    findings: tuple[NormalizedFinding, ...],
    compounds: list[CompoundRisk],
    blast: BlastRadiusReport | None,
) -> RiskFeatures:
    blast_items = [f for f in findings if f.category == FindingCategory.BLAST_RADIUS]
    deployment = [
        f
        for f in findings
        if f.category in {FindingCategory.DATABASE, FindingCategory.API_CONTRACT}
    ]
    rollback = [f for f in findings if f.category == FindingCategory.ROLLBACK]
    blast_score = max(
        ((_SEVERITY_VALUE[f.severity] * f.confidence) for f in blast_items), default=0.0
    )
    deployment_score = max(
        ((_SEVERITY_VALUE[f.severity] * f.confidence) for f in deployment), default=0.0
    )
    rollback_score = max(
        ((_SEVERITY_VALUE[f.severity] * f.confidence) for f in rollback), default=0.0
    )
    return RiskFeatures(
        blast_severity=round(blast_score, 6),
        deployment_severity=round(deployment_score, 6),
        rollback_unsafety=round(rollback_score, 6),
        critical_dependency_count=sum(f.severity == FindingSeverity.CRITICAL for f in findings),
        high_dependency_count=sum(f.severity == FindingSeverity.HIGH for f in findings),
        destructive_change_count=sum(f.rule_id in {"DROP_COLUMN", "DROP_TABLE"} for f in findings),
        breaking_api_count=sum(
            f.category == FindingCategory.API_CONTRACT and f.blocking for f in findings
        ),
        rollback_violation_count=sum(
            f.category == FindingCategory.ROLLBACK and f.rule_id.startswith(("RB-", "EXPAND_"))
            for f in findings
        ),
        unknown_finding_count=sum(
            f.uncertainty is not None or f.confidence == 0.0 for f in findings
        ),
        ambiguity_count=sum(f.category == FindingCategory.AMBIGUITY for f in findings),
        unresolved_reference_count=sum(
            f.category == FindingCategory.DYNAMIC_REFERENCE for f in findings
        ),
        affected_entity_count=len({entity for f in findings for entity in f.affected_entities}),
        max_dependency_hops=max((f.hop_distance for f in blast.findings), default=0)
        if blast
        else 0,
        compound_failure_count=len(compounds),
    )


def _compound_risks(findings: tuple[NormalizedFinding, ...]) -> list[CompoundRisk]:
    rules = {f.rule_id for f in findings}
    entities = tuple(sorted({entity for f in findings for entity in f.affected_entities}))
    compounds: list[CompoundRisk] = []
    if any(f.category == FindingCategory.DATABASE and f.blocking for f in findings) and any(
        f.rule_id == "RB-SCHEMA-REMOVED-OLD-DEPENDENCY" for f in findings
    ):
        compounds.append(
            CompoundRisk(
                id="COMPOUND-ROLLBACK-SCHEMA",
                rules_triggered=tuple(
                    sorted(
                        rules & {"DROP_COLUMN", "DROP_TABLE", "RB-SCHEMA-REMOVED-OLD-DEPENDENCY"}
                    )
                ),
                affected_entities=entities,
                severity=FindingSeverity.CRITICAL,
                multiplier=1.12,
                evidence=tuple(f.evidence[0] for f in findings if f.evidence),
            )
        )
    if any(f.category == FindingCategory.API_CONTRACT and f.blocking for f in findings) and any(
        f.category == FindingCategory.DATABASE for f in findings
    ):
        compounds.append(
            CompoundRisk(
                id="COMPOUND-API-SCHEMA",
                rules_triggered=tuple(sorted(rules)),
                affected_entities=entities,
                severity=FindingSeverity.HIGH,
                multiplier=1.08,
                evidence=(),
            )
        )
    if any(
        f.category == FindingCategory.BLAST_RADIUS and f.severity == FindingSeverity.CRITICAL
        for f in findings
    ) and any(f.category == FindingCategory.ROLLBACK and f.blocking for f in findings):
        compounds.append(
            CompoundRisk(
                id="COMPOUND-BLAST-ROLLBACK",
                rules_triggered=tuple(sorted(rules)),
                affected_entities=entities,
                severity=FindingSeverity.CRITICAL,
                multiplier=1.1,
                evidence=(),
            )
        )
    return sorted(compounds, key=lambda item: item.id)


def _policy(
    findings: tuple[NormalizedFinding, ...], features: RiskFeatures, risk: int
) -> tuple[list[str], DecisionState]:
    rules: list[str] = []
    if any(
        f.blocking and f.severity == FindingSeverity.CRITICAL and f.confidence >= 0.75
        for f in findings
    ):
        rules.append("CRITICAL_BLOCKING_FINDING")
    if features.rollback_unsafety >= 1.0 and features.destructive_change_count > 0:
        rules.append("UNSAFE_ROLLBACK_DESTRUCTIVE_CHANGE")
    if risk >= 70:
        rules.append("RISK_THRESHOLD_70")
    if rules:
        return rules, DecisionState.DO_NOT_DEPLOY
    if features.unknown_finding_count > 0:
        return ["REQUIRED_EVIDENCE_UNKNOWN"], DecisionState.UNKNOWN
    if risk >= 40:
        return ["RISK_THRESHOLD_40"], DecisionState.CAUTION
    return ["NO_BLOCKING_FINDING_LOW_RISK"], DecisionState.SAFE


def _rollback_normalized(item: RollbackFinding) -> NormalizedFinding:
    return NormalizedFinding(
        finding_id=f"rollback:{item.rule_id}:{item.entity}",
        category=FindingCategory.ROLLBACK,
        severity=_severity_from_text(item.severity),
        confidence=1.0 if item.status != RollbackStatus.UNKNOWN else 0.0,
        rule_id=item.rule_id,
        title=item.rule_id,
        description=item.reason,
        # When rollback_truth.py's _unknown() produces this finding,
        # item.entity holds a description of *what evidence is missing*
        # (e.g. "old_schema/new_schema"), not a real graph entity — it must
        # never be counted as an affected entity (see DAY_P0.2 forensics).
        affected_entities=() if item.missing_evidence else (item.entity,),
        evidence=item.evidence,
        provenance=item.provenance,
        source_module="rollback_truth",
        blocking=item.status == RollbackStatus.UNSAFE,
        uncertainty=None
        if item.status != RollbackStatus.UNKNOWN
        else "rollback evidence is unknown",
        direct=item.direct,
    )


def _severity_from_score(score: float) -> FindingSeverity:
    return (
        FindingSeverity.CRITICAL
        if score >= 0.9
        else FindingSeverity.HIGH
        if score >= 0.7
        else FindingSeverity.MEDIUM
        if score >= 0.45
        else FindingSeverity.LOW
    )


def _severity_from_text(value: str) -> FindingSeverity:
    try:
        return FindingSeverity(value.upper())
    except ValueError:
        return FindingSeverity.MEDIUM


def _pairs_to_dicts(values: tuple[Any, ...]) -> tuple[dict[str, Any], ...]:
    return tuple({"value": str(value)} for value in values)


def _evidence_chain(
    findings: tuple[NormalizedFinding, ...],
    features: RiskFeatures,
    compounds: list[CompoundRisk],
    rules: list[str],
    decision: DecisionState,
) -> list[DecisionEvidence]:
    chain: list[DecisionEvidence] = []
    for finding in findings:
        chain.append(
            DecisionEvidence(
                source=finding.rule_id,
                target=f"feature:{finding.category.value.lower()}",
                relation="contributes_to",
                value=finding.severity.value,
            )
        )
    chain.extend(
        DecisionEvidence(
            source="risk_features",
            target="base_risk",
            relation="formula",
            value=str(
                round(
                    100
                    * (
                        0.40 * features.blast_severity
                        + 0.35 * features.deployment_severity
                        + 0.25 * features.rollback_unsafety
                    )
                )
            ),
        )
        for _ in [0]
    )
    for compound in compounds:
        chain.append(
            DecisionEvidence(
                source=compound.id,
                target="compound_adjustment",
                relation="multiplier",
                value=str(compound.multiplier),
            )
        )
    chain.append(
        DecisionEvidence(
            source="policy", target="verdict", relation="selected", value=decision.value
        )
    )
    return chain


def _recommendations(decision: DecisionState, features: RiskFeatures) -> tuple[str, ...]:
    if decision == DecisionState.DO_NOT_DEPLOY:
        return ("Resolve blocking compatibility findings before deployment.",)
    if decision == DecisionState.UNKNOWN:
        return ("Provide the missing analyzer evidence and review unresolved dependencies.",)
    if decision == DecisionState.CAUTION:
        return ("Review the caution findings and deployment sequencing.",)
    return ("Proceed only within the analyzed evidence scope.",)


def _canonical_json(value: Any) -> str:  # noqa: ANN401
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _canonical_provenance(items: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    return sorted(items, key=_canonical_json)


def _redact(value: Any) -> Any:  # noqa: ANN401
    secret_key = re.compile(r"(?i)(password|token|secret|api[_-]?key|authorization|database_url)")
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if secret_key.search(str(key)) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str) and ("Bearer " in value or "://" in value):
        return "[REDACTED]"
    return value


__all__ = [
    "CompoundRisk",
    "DecisionEvidence",
    "DecisionExplanationInput",
    "DecisionReport",
    "DecisionRequest",
    "DecisionState",
    "FindingCategory",
    "FindingSeverity",
    "NormalizedFinding",
    "RiskFeatures",
    "canonical_decision_json",
    "decision_sha256",
    "decide",
    "normalize_findings",
]
