"""Unit tests for domain schema validation.

Tests cover:
- Valid entity construction
- Invalid entity (whitespace in entity_id, missing fields, bad enum)
- Valid edge construction
- Invalid edge (self-loop, bad enum, missing fields)
- DependencyPath invariant (len(edges) == len(nodes) - 1)
- AnalysisReport structure and schema_version
- ReportMetadata
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from preflight.domain.entities import Entity
from preflight.domain.enums import EdgeKind, EntityKind
from preflight.domain.graph_models import DependencyEdge, DependencyPath
from preflight.domain.reports import SCHEMA_VERSION, AnalysisReport, ReportMetadata

# ---------------------------------------------------------------------------
# Entity tests
# ---------------------------------------------------------------------------


class TestEntityValid:
    def test_minimal_valid_entity(self) -> None:
        e = Entity(
            entity_id="users.phone_number",
            name="phone_number",
            kind=EntityKind.DATABASE,
            service="demo-commerce-db",
        )
        assert e.entity_id == "users.phone_number"
        assert e.kind == EntityKind.DATABASE
        assert e.file is None
        assert e.line is None
        assert e.metadata == {}

    def test_full_valid_entity(self) -> None:
        e = Entity(
            entity_id="user-service.UserService",
            name="UserService",
            kind=EntityKind.SERVICE,
            service="user-service",
            file="fixtures/demo-commerce/user-service/src/user_service.py",
            line=20,
            metadata={"language": "python"},
        )
        assert e.line == 20
        assert e.metadata["language"] == "python"

    def test_entity_is_immutable(self) -> None:
        e = Entity(
            entity_id="a.b",
            name="b",
            kind=EntityKind.API,
            service="a",
        )
        with pytest.raises((TypeError, ValidationError)):
            e.entity_id = "x.y"  # type: ignore[misc]

    def test_all_entity_kinds_are_valid(self) -> None:
        for kind in EntityKind:
            e = Entity(
                entity_id=f"svc.{kind.value}",
                name=kind.value,
                kind=kind,
                service="svc",
            )
            assert e.kind == kind


class TestEntityInvalid:
    def test_entity_id_with_whitespace_raises(self) -> None:
        with pytest.raises(ValidationError, match="whitespace"):
            Entity(
                entity_id="users. phone_number",
                name="phone_number",
                kind=EntityKind.DATABASE,
                service="db",
            )

    def test_empty_entity_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            Entity(
                entity_id="",
                name="x",
                kind=EntityKind.SERVICE,
                service="svc",
            )

    def test_empty_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            Entity(
                entity_id="svc.X",
                name="",
                kind=EntityKind.SERVICE,
                service="svc",
            )

    def test_empty_service_raises(self) -> None:
        with pytest.raises(ValidationError):
            Entity(
                entity_id="svc.X",
                name="X",
                kind=EntityKind.SERVICE,
                service="",
            )

    def test_invalid_kind_enum_raises(self) -> None:
        with pytest.raises(ValidationError):
            Entity(
                entity_id="svc.X",
                name="X",
                kind="NONEXISTENT_KIND",  # type: ignore[arg-type]
                service="svc",
            )

    def test_missing_required_field_raises(self) -> None:
        with pytest.raises(ValidationError):
            Entity(  # type: ignore[call-arg]
                entity_id="svc.X",
                name="X",
                # kind is missing
                service="svc",
            )

    def test_negative_line_raises(self) -> None:
        with pytest.raises(ValidationError):
            Entity(
                entity_id="svc.X",
                name="X",
                kind=EntityKind.SERVICE,
                service="svc",
                line=0,  # must be >= 1
            )


# ---------------------------------------------------------------------------
# DependencyEdge tests
# ---------------------------------------------------------------------------


class TestEdgeValid:
    def test_minimal_valid_edge(self) -> None:
        edge = DependencyEdge(
            source="users.phone_number",
            target="user-service.UserService",
            kind=EdgeKind.DB_READ,
        )
        assert edge.source == "users.phone_number"
        assert edge.target == "user-service.UserService"
        assert edge.kind == EdgeKind.DB_READ
        assert edge.weight == 1.0
        assert edge.metadata == {}

    def test_all_edge_kinds_are_constructible(self) -> None:
        for kind in EdgeKind:
            edge = DependencyEdge(source="a", target="b", kind=kind)
            assert edge.kind == kind

    def test_edge_is_immutable(self) -> None:
        edge = DependencyEdge(source="a", target="b", kind=EdgeKind.HTTP_CALL)
        with pytest.raises((TypeError, ValidationError)):
            edge.source = "x"  # type: ignore[misc]

    def test_custom_weight(self) -> None:
        edge = DependencyEdge(
            source="a", target="b", kind=EdgeKind.IMPORT, weight=2.5
        )
        assert edge.weight == 2.5


class TestEdgeInvalid:
    def test_self_loop_raises(self) -> None:
        with pytest.raises(ValidationError, match="source and target must differ"):
            DependencyEdge(
                source="users.phone_number",
                target="users.phone_number",
                kind=EdgeKind.DB_READ,
            )

    def test_invalid_kind_enum_raises(self) -> None:
        with pytest.raises(ValidationError):
            DependencyEdge(
                source="a",
                target="b",
                kind="MADE_UP_KIND",  # type: ignore[arg-type]
            )

    def test_missing_source_raises(self) -> None:
        with pytest.raises(ValidationError):
            DependencyEdge(  # type: ignore[call-arg]
                target="b",
                kind=EdgeKind.HTTP_CALL,
            )

    def test_missing_target_raises(self) -> None:
        with pytest.raises(ValidationError):
            DependencyEdge(  # type: ignore[call-arg]
                source="a",
                kind=EdgeKind.HTTP_CALL,
            )

    def test_zero_weight_raises(self) -> None:
        with pytest.raises(ValidationError):
            DependencyEdge(source="a", target="b", kind=EdgeKind.HTTP_CALL, weight=0.0)

    def test_negative_weight_raises(self) -> None:
        with pytest.raises(ValidationError):
            DependencyEdge(source="a", target="b", kind=EdgeKind.HTTP_CALL, weight=-1.0)


# ---------------------------------------------------------------------------
# DependencyPath tests
# ---------------------------------------------------------------------------


class TestDependencyPath:
    def test_valid_three_hop_path(self) -> None:
        path = DependencyPath(
            nodes=("a", "b", "c", "d"),
            edges=(EdgeKind.DB_READ, EdgeKind.HTTP_CALL, EdgeKind.API_CONSUMES),
        )
        assert path.hop_count == 3
        assert path.origin == "a"
        assert path.terminal == "d"

    def test_valid_single_hop_path(self) -> None:
        path = DependencyPath(
            nodes=("a", "b"),
            edges=(EdgeKind.HTTP_CALL,),
        )
        assert path.hop_count == 1

    def test_edges_length_mismatch_raises(self) -> None:
        with pytest.raises(ValidationError, match="len\\(edges\\)"):
            DependencyPath(
                nodes=("a", "b", "c"),
                edges=(EdgeKind.HTTP_CALL,),  # should be 2 edges for 3 nodes
            )

    def test_empty_nodes_raises(self) -> None:
        with pytest.raises(ValidationError):
            DependencyPath(nodes=(), edges=())

    def test_path_is_immutable(self) -> None:
        from pydantic import ValidationError as PydanticValidationError

        path = DependencyPath(nodes=("a", "b"), edges=(EdgeKind.HTTP_CALL,))
        with pytest.raises((TypeError, AttributeError, PydanticValidationError)):
            path.nodes = ("x",)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AnalysisReport tests
# ---------------------------------------------------------------------------


def _make_minimal_report() -> AnalysisReport:
    entity = Entity(
        entity_id="users.phone_number",
        name="phone_number",
        kind=EntityKind.DATABASE,
        service="db",
    )
    edge = DependencyEdge(
        source="users.phone_number",
        target="user-service.UserService",
        kind=EdgeKind.DB_READ,
    )
    path = DependencyPath(
        nodes=("users.phone_number", "user-service.UserService"),
        edges=(EdgeKind.DB_READ,),
    )
    metadata = ReportMetadata(source_fixture="demo-commerce")
    return AnalysisReport(
        target="users.phone_number",
        entities=(entity,),
        edges=(edge,),
        paths=(path,),
        metadata=metadata,
    )


class TestAnalysisReport:
    def test_schema_version_is_set(self) -> None:
        report = _make_minimal_report()
        assert report.schema_version == SCHEMA_VERSION
        assert report.schema_version == "1.0"

    def test_report_target(self) -> None:
        report = _make_minimal_report()
        assert report.target == "users.phone_number"

    def test_report_contains_entities_and_edges(self) -> None:
        report = _make_minimal_report()
        assert len(report.entities) == 1
        assert len(report.edges) == 1
        assert len(report.paths) == 1

    def test_missing_target_raises(self) -> None:
        with pytest.raises(ValidationError):
            AnalysisReport(  # type: ignore[call-arg]
                entities=(),
                edges=(),
                paths=(),
                metadata=ReportMetadata(source_fixture="x"),
            )

    def test_report_metadata_source_fixture(self) -> None:
        report = _make_minimal_report()
        assert report.metadata.source_fixture == "demo-commerce"

    def test_report_metadata_notes_default_empty(self) -> None:
        meta = ReportMetadata(source_fixture="x")
        assert meta.notes == []
