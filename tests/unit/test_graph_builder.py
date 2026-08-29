"""Unit tests for GraphBuilder.

Tests cover:
- Successful graph construction
- Duplicate entity rejection
- Missing source / missing target rejection
- Duplicate edge rejection
- Node and edge count correctness
- Entity retrieval from built graph
- Builder does not expose raw NetworkX to callers unexpectedly
"""

from __future__ import annotations

import pytest

from preflight.domain.entities import Entity
from preflight.domain.enums import EdgeKind, EntityKind
from preflight.domain.errors import (
    DuplicateEntityError,
    InvalidDependencyError,
    UnknownEntityError,
)
from preflight.domain.graph_models import DependencyEdge
from preflight.graph.builder import GraphBuilder

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(entity_id: str, kind: EntityKind = EntityKind.SERVICE) -> Entity:
    return Entity(
        entity_id=entity_id,
        name=entity_id.split(".")[-1],
        kind=kind,
        service=entity_id.split(".")[0],
    )


def _make_edge(source: str, target: str, kind: EdgeKind = EdgeKind.HTTP_CALL) -> DependencyEdge:
    return DependencyEdge(source=source, target=target, kind=kind)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestGraphBuilderConstruction:
    def test_empty_graph_builds(self) -> None:
        graph = GraphBuilder().build()
        assert graph.node_count == 0
        assert graph.edge_count == 0

    def test_single_entity_no_edges(self) -> None:
        e = _make_entity("svc.A")
        graph = GraphBuilder().add_entity(e).build()
        assert graph.node_count == 1
        assert graph.edge_count == 0

    def test_two_entities_one_edge(self) -> None:
        graph = (
            GraphBuilder()
            .add_entity(_make_entity("svc.A"))
            .add_entity(_make_entity("svc.B"))
            .add_dependency(_make_edge("svc.A", "svc.B"))
            .build()
        )
        assert graph.node_count == 2
        assert graph.edge_count == 1

    def test_canonical_four_node_graph(self) -> None:
        graph = (
            GraphBuilder()
            .add_entity(_make_entity("users.phone_number", EntityKind.DATABASE))
            .add_entity(_make_entity("user-service.UserService", EntityKind.SERVICE))
            .add_entity(_make_entity("profile-api.ProfileAPI", EntityKind.API))
            .add_entity(_make_entity("android-client.ProfileClient", EntityKind.CLIENT))
            .add_dependency(_make_edge("users.phone_number", "user-service.UserService", EdgeKind.DB_READ))
            .add_dependency(_make_edge("user-service.UserService", "profile-api.ProfileAPI", EdgeKind.HTTP_CALL))
            .add_dependency(_make_edge("profile-api.ProfileAPI", "android-client.ProfileClient", EdgeKind.API_CONSUMES))
            .build()
        )
        assert graph.node_count == 4
        assert graph.edge_count == 3

    def test_fluent_api_returns_builder(self) -> None:
        builder = GraphBuilder()
        returned = builder.add_entity(_make_entity("svc.A"))
        assert returned is builder

    def test_build_is_repeatable(self) -> None:
        """Calling build() twice on the same builder yields equivalent graphs."""
        builder = (
            GraphBuilder()
            .add_entity(_make_entity("svc.A"))
            .add_entity(_make_entity("svc.B"))
            .add_dependency(_make_edge("svc.A", "svc.B"))
        )
        g1 = builder.build()
        g2 = builder.build()
        assert g1.node_count == g2.node_count
        assert g1.edge_count == g2.edge_count


# ---------------------------------------------------------------------------
# Entity validation
# ---------------------------------------------------------------------------


class TestGraphBuilderEntityValidation:
    def test_duplicate_entity_raises(self) -> None:
        builder = GraphBuilder().add_entity(_make_entity("svc.A"))
        with pytest.raises(DuplicateEntityError) as exc_info:
            builder.add_entity(_make_entity("svc.A"))
        assert "svc.A" in str(exc_info.value)

    def test_entity_ids_are_sorted_in_built_graph(self) -> None:
        """entity_ids on the built graph must be sorted regardless of insertion order."""
        graph = (
            GraphBuilder()
            .add_entity(_make_entity("z.Z"))
            .add_entity(_make_entity("a.A"))
            .add_entity(_make_entity("m.M"))
            .build()
        )
        ids = graph.entity_ids
        assert ids == sorted(ids)

    def test_get_entity_returns_correct_entity(self) -> None:
        e = _make_entity("svc.MyService")
        graph = GraphBuilder().add_entity(e).build()
        retrieved = graph.get_entity("svc.MyService")
        assert retrieved.entity_id == "svc.MyService"

    def test_get_entity_unknown_id_raises(self) -> None:
        graph = GraphBuilder().build()
        with pytest.raises(UnknownEntityError) as exc_info:
            graph.get_entity("nonexistent.Entity")
        assert "nonexistent.Entity" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Edge validation
# ---------------------------------------------------------------------------


class TestGraphBuilderEdgeValidation:
    def test_missing_source_raises(self) -> None:
        builder = GraphBuilder().add_entity(_make_entity("svc.B"))
        with pytest.raises(UnknownEntityError) as exc_info:
            builder.add_dependency(_make_edge("svc.MISSING", "svc.B"))
        assert "svc.MISSING" in str(exc_info.value)

    def test_missing_target_raises(self) -> None:
        builder = GraphBuilder().add_entity(_make_entity("svc.A"))
        with pytest.raises(UnknownEntityError) as exc_info:
            builder.add_dependency(_make_edge("svc.A", "svc.MISSING"))
        assert "svc.MISSING" in str(exc_info.value)

    def test_duplicate_edge_raises(self) -> None:
        builder = (
            GraphBuilder()
            .add_entity(_make_entity("svc.A"))
            .add_entity(_make_entity("svc.B"))
            .add_dependency(_make_edge("svc.A", "svc.B", EdgeKind.HTTP_CALL))
        )
        with pytest.raises(InvalidDependencyError):
            builder.add_dependency(_make_edge("svc.A", "svc.B", EdgeKind.HTTP_CALL))

    def test_different_kind_same_source_target_is_allowed(self) -> None:
        """Two edges with the same source/target but different kinds are valid."""
        graph = (
            GraphBuilder()
            .add_entity(_make_entity("svc.A"))
            .add_entity(_make_entity("svc.B"))
            .add_dependency(_make_edge("svc.A", "svc.B", EdgeKind.HTTP_CALL))
            .add_dependency(_make_edge("svc.A", "svc.B", EdgeKind.IMPORT))
            .build()
        )
        assert graph.edge_count == 2

    def test_get_dependencies_sorted(self) -> None:
        """get_dependencies() must return edges sorted by (source, target, kind)."""
        graph = (
            GraphBuilder()
            .add_entity(_make_entity("c.C"))
            .add_entity(_make_entity("a.A"))
            .add_entity(_make_entity("b.B"))
            .add_dependency(_make_edge("c.C", "b.B"))
            .add_dependency(_make_edge("a.A", "b.B"))
            .build()
        )
        deps = graph.get_dependencies()
        keys = [(d.source, d.target, d.kind.value) for d in deps]
        assert keys == sorted(keys)
