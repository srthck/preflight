from __future__ import annotations

from preflight.blast_radius import BlastRadiusEngine, blast_radius_sha256, canonical_report_json
from preflight.domain.blast_radius import BlastRadiusRequest, ImpactCategory
from preflight.domain.entities import Entity
from preflight.domain.enums import EdgeKind, EntityKind
from preflight.domain.graph_models import DependencyEdge
from preflight.graph.builder import GraphBuilder


def graph_with_edges(edges: list[DependencyEdge]) -> object:
    builder = GraphBuilder()
    ids = {value for edge in edges for value in (edge.source, edge.target)}
    for entity_id in sorted(ids):
        builder.add_entity(
            Entity(
                entity_id=entity_id,
                name=entity_id,
                kind=EntityKind.SERVICE,
                service="test",
            )
        )
    for edge in edges:
        builder.add_dependency(edge)
    return builder.build()


def edge(source: str, target: str, kind: EdgeKind) -> DependencyEdge:
    return DependencyEdge(
        source=source,
        target=target,
        kind=kind,
        metadata={"evidence": [{"source_file": "test.py", "line": 4, "column": 2}]},
    )


def test_linear_chain_preserves_paths_and_evidence() -> None:
    graph = graph_with_edges([
        edge("A", "B", EdgeKind.DB_READ),
        edge("B", "C", EdgeKind.HTTP_CALL),
        edge("C", "D", EdgeKind.API_CONSUMES),
    ])
    report = BlastRadiusEngine().analyze(graph, BlastRadiusRequest(target="A", max_hops=3))

    assert report.summary.direct_count == 1
    assert report.summary.indirect_count == 2
    assert report.findings[-1].path.nodes == ("A", "B", "C", "D")
    assert report.findings[-1].path.evidence[0]["source_file"] == "test.py"


def test_cycle_is_bounded_and_max_hops_is_honored() -> None:
    graph = graph_with_edges([
        edge("A", "B", EdgeKind.CALL),
        edge("B", "C", EdgeKind.CALL),
        edge("C", "A", EdgeKind.CALL),
    ])
    report = BlastRadiusEngine().analyze(graph, BlastRadiusRequest(target="A", max_hops=2))

    assert {finding.affected_entity for finding in report.findings} == {"B", "C"}
    assert all(finding.hop_distance <= 2 for finding in report.findings)


def test_branch_and_diamond_retain_multiple_paths() -> None:
    graph = graph_with_edges([
        edge("A", "B", EdgeKind.DB_READ),
        edge("A", "C", EdgeKind.HTTP_CALL),
        edge("B", "D", EdgeKind.API_CONSUMES),
        edge("C", "D", EdgeKind.API_CONSUMES),
    ])
    report = BlastRadiusEngine().analyze(graph, BlastRadiusRequest(target="A", max_hops=2))

    paths_to_d = [finding for finding in report.findings if finding.affected_entity == "D"]
    assert len(paths_to_d) == 2
    assert paths_to_d[0].category == ImpactCategory.INDIRECT


def test_ranking_and_report_hash_are_deterministic() -> None:
    first = graph_with_edges([
        edge("A", "B", EdgeKind.DB_READ),
        edge("A", "C", EdgeKind.IMPORT),
    ])
    second = graph_with_edges([
        edge("A", "C", EdgeKind.IMPORT),
        edge("A", "B", EdgeKind.DB_READ),
    ])
    request = BlastRadiusRequest(target="A", max_hops=1)
    report_a = BlastRadiusEngine().analyze(first, request)
    report_b = BlastRadiusEngine().analyze(second, request)

    assert report_a.findings[0].affected_entity == "B"
    assert canonical_report_json(report_a) == canonical_report_json(report_b)
    assert blast_radius_sha256(report_a) == blast_radius_sha256(report_b)


def test_max_paths_is_deterministic() -> None:
    graph = graph_with_edges([
        edge("A", "B", EdgeKind.CALL),
        edge("A", "C", EdgeKind.CALL),
        edge("A", "D", EdgeKind.CALL),
    ])
    report = BlastRadiusEngine().analyze(graph, BlastRadiusRequest(target="A", max_hops=1, max_paths=2))

    assert len(report.findings) == 2
    assert [finding.affected_entity for finding in report.findings] == ["B", "C"]
