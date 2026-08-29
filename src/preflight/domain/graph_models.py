"""Graph-level domain models.

These models describe *what* the graph contains at the domain level,
independent of the NetworkX representation.

DependencyEdge  — a typed, directed link between two entities.
DependencyPath  — an ordered sequence of entities connected by typed edges.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from preflight.domain.enums import EdgeKind


class DependencyEdge(BaseModel):
    """A directed, typed dependency between two entities.

    ``source`` and ``target`` are ``entity_id`` values from registered
    :class:`~preflight.domain.entities.Entity` instances.

    ``weight`` defaults to 1.0 and is reserved for future risk-weighted
    traversal; it plays no role in Day 1 analysis.
    """

    model_config = {"frozen": True}

    source: str = Field(
        ...,
        description="entity_id of the dependency source.",
        min_length=1,
    )
    target: str = Field(
        ...,
        description="entity_id of the dependency target.",
        min_length=1,
    )
    kind: EdgeKind = Field(..., description="Semantic type of this dependency.")
    weight: float = Field(
        default=1.0,
        description="Edge weight; reserved for future risk-weighted traversal.",
        gt=0.0,
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extension data. Not used for identity or sorting.",
    )

    @property
    def evidence(self) -> list[Any]:
        """Backwards-compatible access to source evidence stored in metadata."""

        from preflight.semantic import EdgeEvidence

        evidence = self.metadata.get("evidence", [])
        if evidence is None:
            return []
        return [
            EdgeEvidence.model_validate(item) if isinstance(item, dict) else item
            for item in evidence
        ]

    @model_validator(mode="after")
    def source_and_target_must_differ(self) -> DependencyEdge:
        """Self-loops are not permitted; they indicate a modelling error."""
        if self.source == self.target:
            raise ValueError(
                f"source and target must differ; got {self.source!r} for both"
            )
        return self


class DependencyPath(BaseModel):
    """An ordered, directed path through the dependency graph.

    ``nodes``  — ordered list of entity_ids from source to terminal.
    ``edges``  — ordered list of EdgeKind values for each hop.

    Invariant: ``len(edges) == len(nodes) - 1``
    A single-node path has zero edges and zero hops.
    """

    model_config = {"frozen": True}

    nodes: tuple[str, ...] = Field(
        ...,
        description="Ordered entity_ids from path origin to terminal.",
        min_length=1,
    )
    edges: tuple[EdgeKind, ...] = Field(
        ...,
        description="Ordered EdgeKind values, one per hop.",
    )

    @model_validator(mode="after")
    def edges_length_must_be_nodes_minus_one(self) -> DependencyPath:
        if len(self.edges) != len(self.nodes) - 1:
            raise ValueError(
                f"len(edges) must equal len(nodes) - 1; "
                f"got {len(self.edges)} edges and {len(self.nodes)} nodes"
            )
        return self

    @property
    def hop_count(self) -> int:
        """Number of hops in this path (equals number of edges)."""
        return len(self.edges)

    @property
    def origin(self) -> str:
        """The entity_id at the start of the path."""
        return self.nodes[0]

    @property
    def terminal(self) -> str:
        """The entity_id at the end of the path."""
        return self.nodes[-1]
