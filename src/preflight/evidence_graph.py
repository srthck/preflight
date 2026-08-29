"""Materialized evidence graph — the causal chain from change to verdict.

This module is an **integration model, not an analyzer**. It performs no
parsing, no traversal, no risk arithmetic and no policy evaluation: every
node and edge it emits is a projection of evidence that the existing
analyzers already produced and that ``decide()`` already scored. If a fact
is not present in the :class:`~preflight.orchestration.models.AnalysisRunResult`
handed to :func:`build_evidence_graph`, it does not become a node — missing
evidence stays missing rather than being interpolated.

The chain it materializes:

    CHANGE -> SCHEMA_ENTITY -> SOURCE_SYMBOL/SERVICE -> API_ENDPOINT
           -> FINDING -> RISK_FEATURE -> POLICY_RULE -> VERDICT

Identity is content-derived: node IDs are built from semantic values
(``entity:users.phone_number``), never from array position, UUIDs,
timestamps, or the temporary extraction path. Every collection is sorted
before emission, so the same analyzed evidence always produces a
byte-identical graph regardless of ZIP entry order, filesystem walk order,
or which temp directory the archive happened to be extracted into.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, model_validator

if TYPE_CHECKING:  # pragma: no cover - typing only
    from preflight.orchestration.models import AnalysisRunResult

# Risk features that are genuinely weighted by decide(); mirrored here only
# to know which contributions to project, never to recompute the score.
_WEIGHTED_FEATURES: tuple[tuple[str, str], ...] = (
    ("blast_severity", "Blast severity"),
    ("deployment_severity", "Deployment severity"),
    ("rollback_unsafety", "Rollback unsafety"),
)

# Which finding category feeds which weighted risk feature. Used only to draw
# CONTRIBUTES_TO edges between facts that already exist.
_CATEGORY_TO_FEATURE: dict[str, str] = {
    "BLAST_RADIUS": "blast_severity",
    "DATABASE": "deployment_severity",
    "SCHEMA": "deployment_severity",
    "ROLLBACK": "rollback_unsafety",
    "API_CONTRACT": "blast_severity",
}


class EvidenceNodeKind(str, Enum):
    """What a node actually is. Every kind maps to real domain evidence."""

    CHANGE = "CHANGE"
    SCHEMA_ENTITY = "SCHEMA_ENTITY"
    SOURCE_SYMBOL = "SOURCE_SYMBOL"
    SERVICE = "SERVICE"
    API_ENDPOINT = "API_ENDPOINT"
    CLIENT = "CLIENT"
    FINDING = "FINDING"
    RISK_FEATURE = "RISK_FEATURE"
    POLICY_RULE = "POLICY_RULE"
    VERDICT = "VERDICT"


class EvidenceEdgeKind(str, Enum):
    """Causal relationships. Each one means something specific."""

    AFFECTS = "AFFECTS"
    DEPENDS_ON = "DEPENDS_ON"
    PRODUCES = "PRODUCES"
    CONTRIBUTES_TO = "CONTRIBUTES_TO"
    TRIGGERS = "TRIGGERS"
    DETERMINES = "DETERMINES"


class EvidenceNode(BaseModel):
    """One node. ``provenance`` answers 'what source artifact proves this?'."""

    model_config = {"frozen": True}

    id: str = Field(..., min_length=1)
    kind: EvidenceNodeKind
    label: str = Field(..., min_length=1)
    # Semantic layer for presentation: 0 change, 1 direct, 2+ indirect,
    # 90 finding, 91 risk feature, 92 policy, 93 verdict. Derived from real
    # hop distance, never from drawing convenience.
    layer: int = Field(default=0, ge=0)
    hop_distance: int | None = Field(default=None, ge=0)
    detail: str = Field(default="")
    severity: str | None = Field(default=None)
    provenance: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceEdge(BaseModel):
    """One causal relationship, with the provenance that justifies drawing it."""

    model_config = {"frozen": True}

    source: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)
    kind: EvidenceEdgeKind
    label: str = Field(default="")
    # Which changed target this edge belongs to. Convergent entities have
    # several incoming edges that differ only by this field — which is what
    # keeps both causal paths intact instead of collapsing them.
    via_target: str | None = Field(default=None)
    provenance: tuple[dict[str, Any], ...] = Field(default_factory=tuple)

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.source, self.target, self.kind.value, self.via_target or "")


class EvidenceGraph(BaseModel):
    """Deterministic, materialized causal graph for one analysis run."""

    model_config = {"frozen": True}

    nodes: tuple[EvidenceNode, ...] = Field(default_factory=tuple)
    edges: tuple[EvidenceEdge, ...] = Field(default_factory=tuple)
    roots: tuple[str, ...] = Field(default_factory=tuple)
    convergence: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    evidence_count: int = Field(default=0, ge=0)
    reachable_verdict: bool = Field(default=False)
    graph_hash: str = Field(default="")

    @model_validator(mode="after")
    def _sort(self) -> EvidenceGraph:
        object.__setattr__(self, "nodes", tuple(sorted(self.nodes, key=lambda n: n.id)))
        object.__setattr__(self, "edges", tuple(sorted(self.edges, key=lambda e: e.key)))
        object.__setattr__(self, "roots", tuple(sorted(self.roots)))
        return self

    def with_hash(self) -> EvidenceGraph:
        payload = self.model_dump(mode="json", exclude={"graph_hash"})
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return self.model_copy(
            update={"graph_hash": hashlib.sha256(encoded.encode("utf-8")).hexdigest()}
        )


# ---------------------------------------------------------------------------
# Deterministic, content-derived identity
# ---------------------------------------------------------------------------


def _change_id(kind: str, schema_object: str | None) -> str:
    return f"change:{kind}:{schema_object or 'unresolved'}"


def _entity_id(entity_id: str) -> str:
    return f"entity:{entity_id}"


def _finding_id(finding_id: str) -> str:
    return f"finding:{finding_id}"


def _risk_id(feature: str) -> str:
    return f"risk:{feature}"


def _policy_id(rule: str) -> str:
    return f"policy:{rule}"


_VERDICT_ID = "verdict"


def _entity_kind(kind_value: str) -> EvidenceNodeKind:
    return {
        "DATABASE": EvidenceNodeKind.SCHEMA_ENTITY,
        "SERVICE": EvidenceNodeKind.SERVICE,
        "API": EvidenceNodeKind.API_ENDPOINT,
        "CLIENT": EvidenceNodeKind.CLIENT,
        "SYMBOL": EvidenceNodeKind.SOURCE_SYMBOL,
    }.get(kind_value, EvidenceNodeKind.SOURCE_SYMBOL)


def build_evidence_graph(result: AnalysisRunResult) -> EvidenceGraph:
    """Project one completed analysis into its materialized causal graph.

    Pure transform: it reads ``result`` and emits nodes/edges. It never
    re-runs an analyzer, never recomputes risk, and never invents a
    relationship that the underlying evidence does not already contain.
    """
    nodes: dict[str, EvidenceNode] = {}
    edges: dict[tuple[str, str, str, str], EvidenceEdge] = {}
    roots: set[str] = set()

    def add_node(node: EvidenceNode) -> None:
        # First writer wins for stable identity; later duplicates would carry
        # the same content-derived id anyway. A convergent entity is therefore
        # ONE node, while its multiple incoming edges are all preserved below.
        nodes.setdefault(node.id, node)

    def add_edge(edge: EvidenceEdge) -> None:
        edges.setdefault(edge.key, edge)

    graph = result.graph
    decision = result.decision

    # --- LAYER 0: the changes themselves -----------------------------------
    targets = set(result.blast_radius_targets)
    for change in result.schema_changes:
        schema_object = change.schema_object
        node_id = _change_id(change.kind.value, schema_object)
        resolved = schema_object is not None and schema_object in targets
        add_node(
            EvidenceNode(
                id=node_id,
                kind=EvidenceNodeKind.CHANGE,
                label=change.kind.value,
                layer=0,
                hop_distance=0,
                detail=change.reason or change.kind.value,
                severity=change.severity.value,
                provenance=tuple({"sql": item} for item in change.evidence),
                metadata={
                    "schema_object": schema_object,
                    "table": change.table,
                    "category": change.category.value,
                    "domain": "DATABASE",
                    "resolved_as_blast_target": resolved,
                },
            )
        )
        roots.add(node_id)

        # CHANGE --affects--> SCHEMA_ENTITY, only when the changed object is
        # a real entity in the analyzed graph. An unresolvable target draws
        # no edge rather than a speculative one.
        if schema_object and schema_object in graph.entity_ids:
            entity = graph.get_entity(schema_object)
            add_node(
                EvidenceNode(
                    id=_entity_id(schema_object),
                    kind=_entity_kind(entity.kind.value),
                    label=entity.name,
                    layer=0,
                    hop_distance=0,
                    detail=schema_object,
                    provenance=_entity_provenance(entity),
                    metadata={"entity_id": schema_object, "service": entity.service},
                )
            )
            add_edge(
                EvidenceEdge(
                    source=node_id,
                    target=_entity_id(schema_object),
                    kind=EvidenceEdgeKind.AFFECTS,
                    label=change.kind.value,
                    via_target=schema_object,
                )
            )

    # --- LAYERS 1..n: real dependency paths from blast radius --------------
    for finding in result.blast_radius.findings:
        path_nodes = list(finding.path.nodes)
        evidence = tuple(finding.path.evidence)
        for hop, entity_id in enumerate(path_nodes):
            if entity_id not in graph.entity_ids:
                continue
            entity = graph.get_entity(entity_id)
            add_node(
                EvidenceNode(
                    id=_entity_id(entity_id),
                    kind=_entity_kind(entity.kind.value),
                    label=entity.name,
                    layer=hop,
                    hop_distance=hop,
                    detail=entity_id,
                    provenance=_entity_provenance(entity),
                    metadata={"entity_id": entity_id, "service": entity.service},
                )
            )
        # Each consecutive pair is a real dependency edge, tagged with the
        # target it was reached from so convergent arrivals stay distinct.
        for index in range(len(path_nodes) - 1):
            source, target = path_nodes[index], path_nodes[index + 1]
            if source not in graph.entity_ids or target not in graph.entity_ids:
                continue
            edge_kind = (
                finding.path.edge_types[index].value
                if index < len(finding.path.edge_types)
                else "DEPENDS_ON"
            )
            add_edge(
                EvidenceEdge(
                    source=_entity_id(source),
                    target=_entity_id(target),
                    kind=EvidenceEdgeKind.DEPENDS_ON,
                    label=edge_kind,
                    via_target=finding.target,
                    provenance=evidence,
                )
            )

    # --- LAYER 90: findings ------------------------------------------------
    for normalized in decision.findings:
        # An ANALYZER-UNAVAILABLE marker records absent evidence; it is not a
        # causal fact about the repository, so it never becomes a graph node.
        if normalized.rule_id == "ANALYZER-UNAVAILABLE":
            continue
        node_id = _finding_id(normalized.finding_id)
        add_node(
            EvidenceNode(
                id=node_id,
                kind=EvidenceNodeKind.FINDING,
                label=normalized.rule_id,
                layer=90,
                detail=normalized.description,
                severity=normalized.severity.value,
                provenance=normalized.evidence,
                metadata={
                    "category": normalized.category.value,
                    "confidence": normalized.confidence,
                    "blocking": normalized.blocking,
                    "source_module": normalized.source_module,
                },
            )
        )
        # affected entity --produces--> finding, for entities actually present.
        for affected in normalized.affected_entities:
            if _entity_id(affected) in nodes:
                add_edge(
                    EvidenceEdge(
                        source=_entity_id(affected),
                        target=node_id,
                        kind=EvidenceEdgeKind.PRODUCES,
                        label=normalized.category.value,
                    )
                )

        # finding --contributes_to--> risk feature (only weighted features).
        feature = _CATEGORY_TO_FEATURE.get(normalized.category.value)
        if feature is not None:
            add_edge(
                EvidenceEdge(
                    source=node_id,
                    target=_risk_id(feature),
                    kind=EvidenceEdgeKind.CONTRIBUTES_TO,
                    label=feature,
                )
            )

    # --- LAYER 91: risk features (values come from decide(), never recomputed)
    features = decision.risk_features
    for feature, label in _WEIGHTED_FEATURES:
        value = float(getattr(features, feature))
        add_node(
            EvidenceNode(
                id=_risk_id(feature),
                kind=EvidenceNodeKind.RISK_FEATURE,
                label=label,
                layer=91,
                detail=f"{label} = {value:.2f}",
                metadata={"feature": feature, "value": value},
            )
        )

    # --- LAYER 92/93: policy rules and the verdict -------------------------
    for rule in decision.policy_rules_triggered:
        add_node(
            EvidenceNode(
                id=_policy_id(rule),
                kind=EvidenceNodeKind.POLICY_RULE,
                label=rule,
                layer=92,
                detail=f"Policy rule {rule} was triggered.",
                metadata={"rule": rule},
            )
        )
        for feature, _label in _WEIGHTED_FEATURES:
            if float(getattr(features, feature)) > 0.0:
                add_edge(
                    EvidenceEdge(
                        source=_risk_id(feature),
                        target=_policy_id(rule),
                        kind=EvidenceEdgeKind.TRIGGERS,
                        label=rule,
                    )
                )

    add_node(
        EvidenceNode(
            id=_VERDICT_ID,
            kind=EvidenceNodeKind.VERDICT,
            label=decision.decision.value,
            layer=93,
            detail=f"Risk {decision.risk_score}/100",
            metadata={
                "decision": decision.decision.value,
                "risk_score": decision.risk_score,
                "base_risk": decision.base_risk,
                "compound_multiplier": decision.compound_multiplier,
            },
        )
    )
    for rule in decision.policy_rules_triggered:
        add_edge(
            EvidenceEdge(
                source=_policy_id(rule),
                target=_VERDICT_ID,
                kind=EvidenceEdgeKind.DETERMINES,
                label=decision.decision.value,
            )
        )

    # Whether the verdict is reachable through real causal evidence, or was
    # reached only because required evidence was missing (UNKNOWN).
    reachable = bool(decision.policy_rules_triggered) and bool(roots)

    graph_model = EvidenceGraph(
        nodes=tuple(nodes.values()),
        edges=tuple(edges.values()),
        roots=tuple(roots),
        convergence=tuple(result.convergent_entities),
        evidence_count=sum(len(edge.provenance) for edge in edges.values()),
        reachable_verdict=reachable,
    )
    return graph_model.with_hash()


def _entity_provenance(entity: Any) -> tuple[dict[str, Any], ...]:  # noqa: ANN401
    """Source location for an entity, when the parser recorded one."""
    if entity.file is None:
        return ()
    return (
        {
            "source_file": entity.file,
            "line": entity.line,
            "symbol": entity.name,
            "kind": entity.kind.value,
        },
    )


__all__ = [
    "EvidenceEdge",
    "EvidenceEdgeKind",
    "EvidenceGraph",
    "EvidenceNode",
    "EvidenceNodeKind",
    "build_evidence_graph",
]
