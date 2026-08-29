"""Deterministic downstream blast-radius analysis over the PreFlight graph."""

from __future__ import annotations

import hashlib
import json
from typing import Final

import networkx as nx

from preflight.domain.blast_radius import (
    BlastRadiusFinding,
    BlastRadiusReport,
    BlastRadiusRequest,
    ImpactCategory,
    ImpactPath,
    ImpactSummary,
)
from preflight.domain.enums import EdgeKind
from preflight.graph.builder import PreFlightGraph

EDGE_WEIGHTS: Final[dict[EdgeKind, float]] = {
    EdgeKind.DB_WRITE: 1.00,
    EdgeKind.DB_READ: 0.90,
    EdgeKind.API_CONSUMES: 0.85,
    EdgeKind.HTTP_CALL: 0.75,
    EdgeKind.CONFIG_DEPENDENCY: 0.70,
    EdgeKind.CALL: 0.60,
    EdgeKind.IMPORT: 0.35,
}
HOP_DECAY_ALPHA: Final[float] = 0.50


class BlastRadiusEngine:
    """Compute bounded, ranked downstream impact paths."""

    def analyze(self, graph: PreFlightGraph, request: BlastRadiusRequest) -> BlastRadiusReport:
        if request.target not in graph.digraph:
            raise ValueError(f"Unknown blast-radius target: {request.target}")

        paths = self._simple_paths(graph, request)
        findings = tuple(
            sorted(
                (self._finding(graph, request.target, path) for path in paths),
                key=lambda finding: (
                    -finding.severity,
                    finding.hop_distance,
                    finding.affected_entity,
                    finding.path.nodes,
                ),
            )
        )
        direct = {
            finding.affected_entity
            for finding in findings
            if finding.category == ImpactCategory.DIRECT
        }
        indirect = {
            finding.affected_entity
            for finding in findings
            if finding.category == ImpactCategory.INDIRECT
        }
        return BlastRadiusReport(
            target=request.target,
            max_hops=request.max_hops,
            max_paths=request.max_paths,
            findings=findings,
            summary=ImpactSummary(
                direct_count=len(direct),
                indirect_count=len(indirect),
                affected_count=len(direct | indirect),
            ),
        )

    def _simple_paths(
        self, graph: PreFlightGraph, request: BlastRadiusRequest
    ) -> list[tuple[str, ...]]:
        digraph = graph.digraph
        raw_paths: list[tuple[str, ...]] = []
        for target in sorted(digraph.nodes):
            if target == request.target:
                continue
            raw_paths.extend(
                tuple(path)
                for path in nx.all_simple_paths(
                    digraph, request.target, target, cutoff=request.max_hops
                )
            )
        return sorted(set(raw_paths), key=lambda path: (len(path), path))[: request.max_paths]

    def _finding(
        self, graph: PreFlightGraph, target: str, nodes: tuple[str, ...]
    ) -> BlastRadiusFinding:
        edge_types: list[EdgeKind] = []
        evidence: list[dict[str, object]] = []
        edge_score = 1.0
        for source, destination in zip(nodes, nodes[1:], strict=False):
            dependency = graph.digraph.edges[source, destination]["dependency"]
            edge_types.append(dependency.kind)
            edge_score *= EDGE_WEIGHTS.get(dependency.kind, 0.50)
            evidence.extend(dependency.metadata.get("evidence", []))
        hop_distance = len(nodes) - 1
        severity = edge_score / (1.0 + HOP_DECAY_ALPHA * (hop_distance - 1))
        category = ImpactCategory.DIRECT if hop_distance == 1 else ImpactCategory.INDIRECT
        edge_names = " -> ".join(kind.value for kind in edge_types)
        reason = f"{category.value.title()} impact through {edge_names}."
        return BlastRadiusFinding(
            target=target,
            affected_entity=nodes[-1],
            severity=round(severity, 6),
            hop_distance=hop_distance,
            category=category,
            path=ImpactPath(nodes=nodes, edge_types=tuple(edge_types), evidence=tuple(evidence)),
            reason=reason,
        )


def canonical_report_json(report: BlastRadiusReport) -> str:
    """Serialize a report without timestamps, object identities, or random data."""

    return json.dumps(
        report.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def blast_radius_sha256(report: BlastRadiusReport) -> str:
    """Return the stable SHA-256 of a canonical blast-radius report."""

    return hashlib.sha256(canonical_report_json(report).encode("utf-8")).hexdigest()


__all__ = [
    "EDGE_WEIGHTS",
    "HOP_DECAY_ALPHA",
    "BlastRadiusEngine",
    "blast_radius_sha256",
    "canonical_report_json",
]
