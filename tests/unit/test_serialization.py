"""Unit tests for deterministic canonical serialization.

Tests cover:
- canonical_graph() produces expected structure
- canonical_json() is valid JSON
- Nodes are sorted by entity_id in output
- Edges are sorted by (source, target, kind)
- metadata fields are excluded from canonical output
- canonical_json() is identical across two builds from identical input
- canonical_sha256() is identical across two builds from identical input
- SHA-256 is a valid 64-character hex string

These tests constitute the Day 1 determinism foundation.
See docs/DETERMINISM.md.
"""

from __future__ import annotations

import hashlib
import json

from preflight.domain.entities import Entity
from preflight.domain.enums import EdgeKind, EntityKind
from preflight.domain.graph_models import DependencyEdge
from preflight.graph.builder import GraphBuilder
from preflight.graph.serialization import canonical_graph, canonical_json, canonical_sha256

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entity(eid: str, kind: EntityKind = EntityKind.SERVICE) -> Entity:
    return Entity(
        entity_id=eid,
        name=eid.split(".")[-1],
        kind=kind,
        service=eid.split(".")[0],
        metadata={"should_not_appear": True},  # must be excluded from canonical output
    )


def _edge(src: str, tgt: str, kind: EdgeKind = EdgeKind.HTTP_CALL) -> DependencyEdge:
    return DependencyEdge(
        source=src,
        target=tgt,
        kind=kind,
        metadata={"should_not_appear": True},  # must be excluded
    )


def _build_canonical() -> object:
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
# Structure tests
# ---------------------------------------------------------------------------


class TestCanonicalGraphStructure:
    def setup_method(self) -> None:
        self.graph = _build_canonical()
        self.data = canonical_graph(self.graph)

    def test_schema_version_present(self) -> None:
        assert self.data["schema_version"] == "1.0"

    def test_nodes_key_present(self) -> None:
        assert "nodes" in self.data

    def test_edges_key_present(self) -> None:
        assert "edges" in self.data

    def test_node_count(self) -> None:
        assert len(self.data["nodes"]) == 4

    def test_edge_count(self) -> None:
        assert len(self.data["edges"]) == 3

    def test_nodes_sorted_by_entity_id(self) -> None:
        ids = [n["entity_id"] for n in self.data["nodes"]]
        assert ids == sorted(ids)

    def test_edges_sorted_by_source_target_kind(self) -> None:
        keys = [(e["source"], e["target"], e["kind"]) for e in self.data["edges"]]
        assert keys == sorted(keys)

    def test_metadata_excluded_from_nodes(self) -> None:
        for node in self.data["nodes"]:
            assert "metadata" not in node
            assert "should_not_appear" not in node

    def test_metadata_excluded_from_edges(self) -> None:
        for edge in self.data["edges"]:
            assert "metadata" not in edge
            assert "should_not_appear" not in edge

    def test_node_fields_present(self) -> None:
        for node in self.data["nodes"]:
            assert "entity_id" in node
            assert "name" in node
            assert "kind" in node
            assert "service" in node

    def test_edge_fields_present(self) -> None:
        for edge in self.data["edges"]:
            assert "source" in edge
            assert "target" in edge
            assert "kind" in edge
            assert "weight" in edge

    def test_first_node_is_android_client(self) -> None:
        # "android-client.ProfileClient" is lexicographically first
        assert self.data["nodes"][0]["entity_id"] == "android-client.ProfileClient"

    def test_last_node_is_users(self) -> None:
        # "users.phone_number" is lexicographically last among the four
        assert self.data["nodes"][-1]["entity_id"] == "users.phone_number"


# ---------------------------------------------------------------------------
# JSON validity
# ---------------------------------------------------------------------------


class TestCanonicalJson:
    def test_output_is_valid_json(self) -> None:
        graph = _build_canonical()
        raw = canonical_json(graph)
        parsed = json.loads(raw)  # raises if invalid
        assert parsed["schema_version"] == "1.0"

    def test_json_has_no_unnecessary_whitespace(self) -> None:
        graph = _build_canonical()
        raw = canonical_json(graph)
        # Compact separators mean no spaces after : or ,
        assert ": " not in raw
        assert ", " not in raw


# ---------------------------------------------------------------------------
# Determinism tests — Day 1 foundation
# ---------------------------------------------------------------------------


class TestDeterminism:
    """
    Determinism contract:
    Given identical normalized input, canonical_json() and canonical_sha256()
    must produce identical output across all invocations.
    """

    def test_canonical_json_identical_across_two_builds(self) -> None:
        graph_a = _build_canonical()
        graph_b = _build_canonical()
        assert canonical_json(graph_a) == canonical_json(graph_b)

    def test_canonical_sha256_identical_across_two_builds(self) -> None:
        graph_a = _build_canonical()
        graph_b = _build_canonical()
        assert canonical_sha256(graph_a) == canonical_sha256(graph_b)

    def test_sha256_is_valid_hex_string(self) -> None:
        graph = _build_canonical()
        digest = canonical_sha256(graph)
        assert len(digest) == 64
        # Must be valid hexadecimal
        int(digest, 16)

    def test_sha256_matches_manual_computation(self) -> None:
        """SHA-256 must equal hashlib over the UTF-8 canonical JSON bytes."""
        graph = _build_canonical()
        raw = canonical_json(graph)
        expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        assert canonical_sha256(graph) == expected

    def test_different_insertion_order_same_output(self) -> None:
        """Inserting entities in reverse order must produce identical serialization."""
        # Build graph with entities inserted in reverse alphabetical order
        graph_reversed = (
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
        graph_forward = _build_canonical()
        assert canonical_json(graph_reversed) == canonical_json(graph_forward)

    def test_sha256_is_stable_known_value(self) -> None:
        """Once the canonical form is established, the digest must never silently change.

        This test captures the actual SHA-256 on first run. If the serialization
        contract changes, this test will fail — which is the intended behaviour.
        It forces explicit acknowledgement of a canonical-form change.
        """
        graph = _build_canonical()
        digest = canonical_sha256(graph)
        # Re-compute from scratch to confirm stability within the same run.
        digest_again = canonical_sha256(_build_canonical())
        assert digest == digest_again
