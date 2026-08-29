"""Integration tests for the demo-commerce fixture.

These tests construct the actual canonical graph from the fixture loader
and validate the end-to-end Day 1 acceptance criteria.

Acceptance criteria verified here:
- Four canonical entities exist with correct IDs
- Three typed edges exist
- Canonical 3-hop path exists
- Traversal returns correct ordered nodes
- Traversal returns correct edge types
- Serialization is deterministic (same graph built twice → same SHA-256)
- AnalysisReport can be built from fixture graph
"""

from __future__ import annotations

from preflight.domain.enums import EdgeKind, EntityKind
from preflight.domain.reports import SCHEMA_VERSION, AnalysisReport, ReportMetadata
from preflight.fixtures.loader import (
    ENTITY_ANDROID_CLIENT,
    ENTITY_DB_COLUMN,
    ENTITY_PROFILE_API,
    ENTITY_USER_SERVICE,
    build_demo_commerce_graph,
)
from preflight.graph.serialization import canonical_sha256
from preflight.graph.traversal import find_canonical_path, find_downstream_paths

# ---------------------------------------------------------------------------
# Fixture graph construction
# ---------------------------------------------------------------------------


class TestFixtureGraphConstruction:
    def setup_method(self) -> None:
        self.graph = build_demo_commerce_graph()

    def test_graph_has_four_nodes(self) -> None:
        assert self.graph.node_count == 4

    def test_graph_has_three_edges(self) -> None:
        assert self.graph.edge_count == 3

    def test_all_canonical_entity_ids_present(self) -> None:
        ids = set(self.graph.entity_ids)
        assert ENTITY_DB_COLUMN in ids
        assert ENTITY_USER_SERVICE in ids
        assert ENTITY_PROFILE_API in ids
        assert ENTITY_ANDROID_CLIENT in ids

    def test_db_column_entity_kind(self) -> None:
        entity = self.graph.get_entity(ENTITY_DB_COLUMN)
        assert entity.kind == EntityKind.DATABASE

    def test_user_service_entity_kind(self) -> None:
        entity = self.graph.get_entity(ENTITY_USER_SERVICE)
        assert entity.kind == EntityKind.SERVICE

    def test_profile_api_entity_kind(self) -> None:
        entity = self.graph.get_entity(ENTITY_PROFILE_API)
        assert entity.kind == EntityKind.API

    def test_android_client_entity_kind(self) -> None:
        entity = self.graph.get_entity(ENTITY_ANDROID_CLIENT)
        assert entity.kind == EntityKind.CLIENT

    def test_edge_kinds_are_correct(self) -> None:
        deps = self.graph.get_dependencies()
        kind_map = {(d.source, d.target): d.kind for d in deps}

        assert kind_map[(ENTITY_DB_COLUMN, ENTITY_USER_SERVICE)] == EdgeKind.DB_READ
        assert kind_map[(ENTITY_USER_SERVICE, ENTITY_PROFILE_API)] == EdgeKind.HTTP_CALL
        assert kind_map[(ENTITY_PROFILE_API, ENTITY_ANDROID_CLIENT)] == EdgeKind.API_CONSUMES


# ---------------------------------------------------------------------------
# Canonical 3-hop path — integration
# ---------------------------------------------------------------------------


class TestFixtureCanonicalPath:
    def setup_method(self) -> None:
        self.graph = build_demo_commerce_graph()

    def test_canonical_path_hop_count(self) -> None:
        path = find_canonical_path(
            self.graph,
            origin=ENTITY_DB_COLUMN,
            terminal=ENTITY_ANDROID_CLIENT,
        )
        assert path.hop_count == 3

    def test_canonical_path_nodes_exact(self) -> None:
        path = find_canonical_path(
            self.graph,
            origin=ENTITY_DB_COLUMN,
            terminal=ENTITY_ANDROID_CLIENT,
        )
        assert path.nodes == (
            "users.phone_number",
            "user-service.UserService",
            "profile-api.ProfileAPI",
            "android-client.ProfileClient",
        )

    def test_canonical_path_edge_types_exact(self) -> None:
        path = find_canonical_path(
            self.graph,
            origin=ENTITY_DB_COLUMN,
            terminal=ENTITY_ANDROID_CLIENT,
        )
        assert path.edges == (
            EdgeKind.DB_READ,
            EdgeKind.HTTP_CALL,
            EdgeKind.API_CONSUMES,
        )

    def test_downstream_paths_include_three_hop(self) -> None:
        paths = find_downstream_paths(self.graph, origin=ENTITY_DB_COLUMN)
        three_hop_paths = [p for p in paths if p.hop_count == 3]
        assert len(three_hop_paths) == 1
        assert three_hop_paths[0].terminal == ENTITY_ANDROID_CLIENT


# ---------------------------------------------------------------------------
# Determinism — integration
# ---------------------------------------------------------------------------


class TestFixtureDeterminism:
    """
    Day 1 determinism contract (integration level):
    Building the fixture graph twice must produce identical SHA-256.
    """

    def test_sha256_identical_across_two_fixture_builds(self) -> None:
        graph_a = build_demo_commerce_graph()
        graph_b = build_demo_commerce_graph()
        digest_a = canonical_sha256(graph_a)
        digest_b = canonical_sha256(graph_b)
        assert digest_a == digest_b, (
            f"Determinism violation: SHA-256 mismatch.\n"
            f"  Run A: {digest_a}\n"
            f"  Run B: {digest_b}"
        )

    def test_sha256_is_nonempty(self) -> None:
        graph = build_demo_commerce_graph()
        assert len(canonical_sha256(graph)) == 64


# ---------------------------------------------------------------------------
# AnalysisReport integration
# ---------------------------------------------------------------------------


class TestFixtureAnalysisReport:
    """Verify that an AnalysisReport can be constructed from fixture graph data."""

    def setup_method(self) -> None:
        self.graph = build_demo_commerce_graph()

    def test_analysis_report_construction(self) -> None:
        path = find_canonical_path(
            self.graph,
            origin=ENTITY_DB_COLUMN,
            terminal=ENTITY_ANDROID_CLIENT,
        )
        entities = tuple(
            self.graph.get_entity(eid) for eid in self.graph.entity_ids
        )
        report = AnalysisReport(
            target=ENTITY_DB_COLUMN,
            entities=entities,
            edges=tuple(self.graph.get_dependencies()),
            paths=(path,),
            metadata=ReportMetadata(
                source_fixture="demo-commerce",
                notes=["Day 1 integration test report."],
            ),
        )
        assert report.schema_version == SCHEMA_VERSION
        assert report.target == ENTITY_DB_COLUMN
        assert len(report.entities) == 4
        assert len(report.edges) == 3
        assert len(report.paths) == 1
        assert report.paths[0].hop_count == 3
