"""Unit tests for graph traversal.

Tests cover:
- Canonical 3-hop path discovery (the Day 1 acceptance criterion)
- Correct node ordering in path
- Correct edge type ordering in path
- hop_count == 3
- find_canonical_path between specific endpoints
- Unknown origin raises UnknownEntityError
- No-path raises ValueError
- Linear graph produces single path
- Branching graph produces multiple paths, sorted correctly
"""

from __future__ import annotations

import pytest

from preflight.domain.entities import Entity
from preflight.domain.enums import EdgeKind, EntityKind
from preflight.domain.errors import UnknownEntityError
from preflight.domain.graph_models import DependencyEdge
from preflight.graph.builder import GraphBuilder
from preflight.graph.traversal import find_canonical_path, find_downstream_paths

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entity(eid: str, kind: EntityKind = EntityKind.SERVICE) -> Entity:
    return Entity(
        entity_id=eid,
        name=eid.split(".")[-1],
        kind=kind,
        service=eid.split(".")[0],
    )


def _edge(src: str, tgt: str, kind: EdgeKind = EdgeKind.HTTP_CALL) -> DependencyEdge:
    return DependencyEdge(source=src, target=tgt, kind=kind)


def _build_canonical_graph() -> object:
    """Build the Day 1 canonical demo-commerce graph."""
    return (
        GraphBuilder()
        .add_entity(_entity("users.phone_number", EntityKind.DATABASE))
        .add_entity(_entity("user-service.UserService", EntityKind.SERVICE))
        .add_entity(_entity("profile-api.ProfileAPI", EntityKind.API))
        .add_entity(_entity("android-client.ProfileClient", EntityKind.CLIENT))
        .add_dependency(_edge("users.phone_number", "user-service.UserService", EdgeKind.DB_READ))
        .add_dependency(_edge("user-service.UserService", "profile-api.ProfileAPI", EdgeKind.HTTP_CALL))
        .add_dependency(_edge("profile-api.ProfileAPI", "android-client.ProfileClient", EdgeKind.API_CONSUMES))
        .build()
    )


# ---------------------------------------------------------------------------
# Canonical 3-hop path — Day 1 acceptance criterion
# ---------------------------------------------------------------------------


class TestCanonicalThreeHopPath:
    """
    The canonical Day 1 traversal MUST produce:

        nodes: ["users.phone_number",
                "user-service.UserService",
                "profile-api.ProfileAPI",
                "android-client.ProfileClient"]
        edges: [DB_READ, HTTP_CALL, API_CONSUMES]
        hop_count: 3
    """

    def setup_method(self) -> None:
        self.graph = _build_canonical_graph()

    def test_find_canonical_path_returns_three_hops(self) -> None:
        path = find_canonical_path(
            self.graph,
            origin="users.phone_number",
            terminal="android-client.ProfileClient",
        )
        assert path.hop_count == 3

    def test_canonical_path_nodes_are_correct(self) -> None:
        path = find_canonical_path(
            self.graph,
            origin="users.phone_number",
            terminal="android-client.ProfileClient",
        )
        assert path.nodes == (
            "users.phone_number",
            "user-service.UserService",
            "profile-api.ProfileAPI",
            "android-client.ProfileClient",
        )

    def test_canonical_path_edge_types_are_correct(self) -> None:
        path = find_canonical_path(
            self.graph,
            origin="users.phone_number",
            terminal="android-client.ProfileClient",
        )
        assert path.edges == (
            EdgeKind.DB_READ,
            EdgeKind.HTTP_CALL,
            EdgeKind.API_CONSUMES,
        )

    def test_canonical_path_origin(self) -> None:
        path = find_canonical_path(
            self.graph,
            origin="users.phone_number",
            terminal="android-client.ProfileClient",
        )
        assert path.origin == "users.phone_number"

    def test_canonical_path_terminal(self) -> None:
        path = find_canonical_path(
            self.graph,
            origin="users.phone_number",
            terminal="android-client.ProfileClient",
        )
        assert path.terminal == "android-client.ProfileClient"

    def test_downstream_paths_from_origin_contains_canonical_path(self) -> None:
        paths = find_downstream_paths(self.graph, origin="users.phone_number")
        three_hop = [p for p in paths if p.hop_count == 3]
        assert len(three_hop) == 1
        assert three_hop[0].terminal == "android-client.ProfileClient"

    def test_downstream_paths_are_sorted_shortest_first(self) -> None:
        paths = find_downstream_paths(self.graph, origin="users.phone_number")
        hop_counts = [p.hop_count for p in paths]
        assert hop_counts == sorted(hop_counts)


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestTraversalErrors:
    def setup_method(self) -> None:
        self.graph = _build_canonical_graph()

    def test_unknown_origin_raises(self) -> None:
        with pytest.raises(UnknownEntityError):
            find_downstream_paths(self.graph, origin="nonexistent.Entity")

    def test_unknown_canonical_origin_raises(self) -> None:
        with pytest.raises(UnknownEntityError):
            find_canonical_path(
                self.graph,
                origin="nonexistent.Entity",
                terminal="android-client.ProfileClient",
            )

    def test_unknown_canonical_terminal_raises(self) -> None:
        with pytest.raises(UnknownEntityError):
            find_canonical_path(
                self.graph,
                origin="users.phone_number",
                terminal="nonexistent.Entity",
            )

    def test_no_path_raises_value_error(self) -> None:
        # android-client.ProfileClient has no outbound edges
        with pytest.raises(ValueError, match="No path exists"):
            find_canonical_path(
                self.graph,
                origin="android-client.ProfileClient",
                terminal="users.phone_number",
            )


# ---------------------------------------------------------------------------
# Topology tests
# ---------------------------------------------------------------------------


class TestTraversalTopology:
    def test_linear_graph_single_path(self) -> None:
        graph = (
            GraphBuilder()
            .add_entity(_entity("a.A"))
            .add_entity(_entity("b.B"))
            .add_entity(_entity("c.C"))
            .add_dependency(_edge("a.A", "b.B"))
            .add_dependency(_edge("b.B", "c.C"))
            .build()
        )
        paths = find_downstream_paths(graph, origin="a.A")
        # Expect paths to b.B (1 hop) and c.C (2 hops)
        hop_counts = sorted(p.hop_count for p in paths)
        assert 1 in hop_counts
        assert 2 in hop_counts

    def test_isolated_node_produces_no_paths(self) -> None:
        graph = (
            GraphBuilder()
            .add_entity(_entity("a.A"))
            .build()
        )
        paths = find_downstream_paths(graph, origin="a.A")
        assert paths == []

    def test_branching_graph_produces_multiple_paths(self) -> None:
        """A → B and A → C should yield two 1-hop paths."""
        graph = (
            GraphBuilder()
            .add_entity(_entity("a.A"))
            .add_entity(_entity("b.B"))
            .add_entity(_entity("c.C"))
            .add_dependency(_edge("a.A", "b.B"))
            .add_dependency(_edge("a.A", "c.C"))
            .build()
        )
        paths = find_downstream_paths(graph, origin="a.A")
        assert len(paths) == 2
        terminals = sorted(p.terminal for p in paths)
        assert terminals == ["b.B", "c.C"]

    def test_branching_equal_length_sorted_lexicographically(self) -> None:
        """When two paths have equal hop counts, lexicographic order applies."""
        graph = (
            GraphBuilder()
            .add_entity(_entity("a.A"))
            .add_entity(_entity("b.B"))
            .add_entity(_entity("z.Z"))
            .add_dependency(_edge("a.A", "z.Z"))
            .add_dependency(_edge("a.A", "b.B"))
            .build()
        )
        paths = find_downstream_paths(graph, origin="a.A")
        assert len(paths) == 2
        # Both are 1-hop; lexicographic sort: b.B < z.Z
        assert paths[0].terminal == "b.B"
        assert paths[1].terminal == "z.Z"
