"""GraphBuilder — constructs a validated, deterministic dependency graph.

Responsibilities
----------------
* Accept validated Entity and DependencyEdge objects.
* Enforce domain invariants (no duplicates, no dangling edges).
* Produce a NetworkX DiGraph with typed, deterministic node/edge data.
* Expose no NetworkX internals in the public API surface.

The builder does NOT
--------------------
* Parse source code.
* Calculate risk scores.
* Access the filesystem, network, or environment.
* Mutate global state.

Usage example::

    from preflight.graph.builder import GraphBuilder
    from preflight.domain.entities import Entity
    from preflight.domain.enums import EntityKind, EdgeKind
    from preflight.domain.graph_models import DependencyEdge

    graph = (
        GraphBuilder()
        .add_entity(Entity(entity_id="a", name="A", kind=EntityKind.SERVICE, service="svc"))
        .add_entity(Entity(entity_id="b", name="B", kind=EntityKind.API, service="svc"))
        .add_dependency(DependencyEdge(source="a", target="b", kind=EdgeKind.HTTP_CALL))
        .build()
    )
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import networkx as nx

from preflight.domain.entities import Entity
from preflight.domain.errors import (
    DuplicateEntityError,
    InvalidDependencyError,
    UnknownEntityError,
)
from preflight.domain.graph_models import DependencyEdge

if TYPE_CHECKING:
    pass

# The key used to store the Entity object on a NetworkX node.
_NODE_ENTITY_ATTR = "entity"
# The key used to store the DependencyEdge object on a NetworkX edge.
_EDGE_DEP_ATTR = "dependency"


class PreFlightGraph:
    """An immutable snapshot of a validated dependency graph.

    Produced by :meth:`GraphBuilder.build`. Callers must not mutate the
    underlying NetworkX graph directly; use the accessors provided here.
    """

    def __init__(
        self,
        digraph: nx.DiGraph,
        entities: dict[str, Entity],
        edges: list[DependencyEdge],
    ) -> None:
        # These are considered owned by this instance; callers must not mutate.
        self._digraph = digraph
        self._entities = entities
        self._edges = edges

    # ------------------------------------------------------------------
    # Read accessors
    # ------------------------------------------------------------------

    @property
    def digraph(self) -> nx.DiGraph:
        """The underlying NetworkX DiGraph. Treat as read-only."""
        return self._digraph

    @property
    def entity_ids(self) -> list[str]:
        """Sorted list of all registered entity_ids."""
        return sorted(self._entities.keys())

    @property
    def node_count(self) -> int:
        return len(self._entities)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    def get_entity(self, entity_id: str) -> Entity:
        """Return the Entity for a given entity_id.

        Raises :class:`~preflight.domain.errors.UnknownEntityError` if not found.
        """
        try:
            return self._entities[entity_id]
        except KeyError as err:
            raise UnknownEntityError(entity_id) from err

    def get_dependencies(self) -> list[DependencyEdge]:
        """Return a copy of all edges, sorted deterministically.

        Sort key: (source, target, kind.value) — all stable strings.
        """
        return sorted(
            self._edges,
            key=lambda e: (e.source, e.target, e.kind.value),
        )


class GraphBuilder:
    """Fluent builder for :class:`PreFlightGraph`.

    The builder accumulates entities and edges, validates them on addition,
    and produces a :class:`PreFlightGraph` on :meth:`build`.

    Each call to :meth:`build` produces an independent graph; the builder
    itself is not consumed and may be called again (idempotent for identical
    inputs, which is a property tests should verify).
    """

    def __init__(self) -> None:
        # Keyed by entity_id for O(1) duplicate detection.
        self._entities: dict[str, Entity] = {}
        # Stored in registration order; sorted deterministically on build.
        self._edges_list: list[DependencyEdge] = []
        # Track (source, target, kind) tuples for duplicate-edge detection.
        self._edge_keys: set[tuple[str, str, str]] = set()

    def add_entity(self, entity: Entity) -> GraphBuilder:
        """Register an entity.

        Raises :class:`~preflight.domain.errors.DuplicateEntityError` if an
        entity with the same ``entity_id`` has already been added.
        """
        if entity.entity_id in self._entities:
            raise DuplicateEntityError(entity.entity_id)
        self._entities[entity.entity_id] = entity
        return self

    def add_dependency(self, edge: DependencyEdge) -> GraphBuilder:
        """Register a dependency edge.

        Raises
        ------
        UnknownEntityError
            If ``edge.source`` or ``edge.target`` has not been registered.
        InvalidDependencyError
            If an identical (source, target, kind) edge already exists.
        """
        if edge.source not in self._entities:
            raise UnknownEntityError(edge.source, context="edge source")
        if edge.target not in self._entities:
            raise UnknownEntityError(edge.target, context="edge target")

        edge_key = (edge.source, edge.target, edge.kind.value)
        if edge_key in self._edge_keys:
            raise InvalidDependencyError(
                f"Duplicate edge: {edge.source!r} --{edge.kind.value}--> {edge.target!r}"
            )

        self._edge_keys.add(edge_key)
        self._edges_list.append(edge)
        return self

    def build(self) -> PreFlightGraph:
        """Construct and return a validated :class:`PreFlightGraph`.

        The NetworkX DiGraph is built from the registered entities and edges.
        Node and edge insertion order is deterministic: nodes are inserted
        sorted by entity_id; edges are inserted sorted by (source, target,
        kind.value).
        """
        g: nx.DiGraph = nx.DiGraph()

        # Insert nodes in sorted order so nx.nodes() iteration is stable.
        for entity_id in sorted(self._entities.keys()):
            entity = self._entities[entity_id]
            g.add_node(entity_id, **{_NODE_ENTITY_ATTR: entity})

        # Insert edges in sorted order.
        sorted_edges = sorted(
            self._edges_list,
            key=lambda e: (e.source, e.target, e.kind.value),
        )
        for edge in sorted_edges:
            g.add_edge(
                edge.source,
                edge.target,
                **{_EDGE_DEP_ATTR: edge},
            )

        return PreFlightGraph(
            digraph=g,
            entities=dict(self._entities),  # defensive copy
            edges=list(self._edges_list),    # defensive copy
        )
