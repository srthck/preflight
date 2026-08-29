"""Dependency graph traversal — downstream reachability analysis.

Traversal rules (Day 1)
-----------------------
Given an origin ``entity_id``, the traversal finds all entities reachable
downstream (following directed edges away from origin).

Determinism contract
--------------------
When multiple paths exist, results are ordered by:
1. Shortest path first (fewest hops).
2. Lexicographic ordering of the node sequence for equal-length paths.

This rule is documented in docs/DETERMINISM.md and tested.
No hash randomisation, dictionary ordering, or filesystem ordering is
relied upon.

The canonical Day 1 path
-------------------------
    users.phone_number
      --DB_READ-->
    user-service.UserService
      --HTTP_CALL-->
    profile-api.ProfileAPI
      --API_CONSUMES-->
    android-client.ProfileClient

    nodes:     ["users.phone_number", "user-service.UserService",
                 "profile-api.ProfileAPI", "android-client.ProfileClient"]
    edges:     [EdgeKind.DB_READ, EdgeKind.HTTP_CALL, EdgeKind.API_CONSUMES]
    hop_count: 3
"""

from __future__ import annotations

from preflight.domain.enums import EdgeKind
from preflight.domain.errors import UnknownEntityError
from preflight.domain.graph_models import DependencyPath
from preflight.graph.builder import PreFlightGraph

# NetworkX node attribute key — must match builder constant.
_EDGE_DEP_ATTR = "dependency"


def find_downstream_paths(
    graph: PreFlightGraph,
    origin: str,
) -> list[DependencyPath]:
    """Return all simple downstream paths from ``origin``.

    A simple path visits each node at most once, preventing cycles from
    causing infinite traversal.

    Parameters
    ----------
    graph:
        A built :class:`~preflight.graph.builder.PreFlightGraph`.
    origin:
        The ``entity_id`` from which traversal begins.

    Returns
    -------
    list[DependencyPath]
        All simple paths from ``origin`` to any reachable node, sorted by:
        1. hop_count ascending.
        2. Lexicographic order of ``nodes`` tuple for equal hop counts.

        The origin-only degenerate path (zero hops) is NOT included;
        callers interested in that edge case should handle it explicitly.

    Raises
    ------
    UnknownEntityError
        If ``origin`` is not a registered entity_id.
    """
    if origin not in graph.digraph:
        raise UnknownEntityError(origin, context="traversal origin")

    digraph = graph.digraph
    raw_paths: list[list[str]] = []

    # nx.all_simple_paths returns all simple paths from source to every
    # reachable target. We collect paths to *all* nodes (by not specifying
    # a target cutoff via depth_limit=None), then filter to only those longer
    # than origin-only.
    for target in digraph.nodes:
        if target == origin:
            continue
        import networkx as nx

        for raw_path in nx.all_simple_paths(digraph, source=origin, target=target):
            if len(raw_path) > 1:
                raw_paths.append(raw_path)

    # Deduplicate: nx.all_simple_paths may yield the same path multiple
    # times when iterating over all targets (a path to an intermediate node
    # is a prefix of a longer path and may be emitted as its own path too).
    unique_paths = _deduplicate_paths(raw_paths)

    # Convert raw node lists to DependencyPath domain objects.
    domain_paths: list[DependencyPath] = []
    for node_list in unique_paths:
        edge_kinds = _extract_edge_kinds(digraph, node_list)
        domain_paths.append(
            DependencyPath(
                nodes=tuple(node_list),
                edges=tuple(edge_kinds),
            )
        )

    # Sort: shortest first, then lexicographic on node tuples.
    domain_paths.sort(key=lambda p: (p.hop_count, p.nodes))
    return domain_paths


def find_canonical_path(
    graph: PreFlightGraph,
    origin: str,
    terminal: str,
) -> DependencyPath:
    """Return the single shortest path from ``origin`` to ``terminal``.

    If multiple shortest paths exist, the lexicographically smallest node
    sequence is returned (deterministic tiebreak).

    Parameters
    ----------
    graph:
        A built :class:`~preflight.graph.builder.PreFlightGraph`.
    origin:
        Starting ``entity_id``.
    terminal:
        Destination ``entity_id``.

    Returns
    -------
    DependencyPath
        The canonical (shortest, lexicographically first) path.

    Raises
    ------
    UnknownEntityError
        If either entity_id is not registered.
    ValueError
        If no path exists between ``origin`` and ``terminal``.
    """
    if origin not in graph.digraph:
        raise UnknownEntityError(origin, context="path origin")
    if terminal not in graph.digraph:
        raise UnknownEntityError(terminal, context="path terminal")

    import networkx as nx

    digraph = graph.digraph

    # Collect all simple paths and apply the deterministic ordering rule.
    candidates: list[list[str]] = list(
        nx.all_simple_paths(digraph, source=origin, target=terminal)
    )

    if not candidates:
        raise ValueError(
            f"No path exists from {origin!r} to {terminal!r} in the dependency graph."
        )

    # Sort: shortest first, then lexicographic tiebreak.
    candidates.sort(key=lambda p: (len(p), p))
    chosen = candidates[0]

    edge_kinds = _extract_edge_kinds(digraph, chosen)
    return DependencyPath(nodes=tuple(chosen), edges=tuple(edge_kinds))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_edge_kinds(
    digraph: object,
    node_list: list[str],
) -> list[EdgeKind]:
    """Extract ordered EdgeKind values for consecutive nodes in ``node_list``.

    The ``dependency`` attribute on each NetworkX edge holds the
    :class:`~preflight.domain.graph_models.DependencyEdge` domain object.
    """
    import networkx as nx

    assert isinstance(digraph, nx.DiGraph)

    kinds: list[EdgeKind] = []
    for i in range(len(node_list) - 1):
        src = node_list[i]
        tgt = node_list[i + 1]
        edge_data = digraph.edges[src, tgt]
        dep = edge_data[_EDGE_DEP_ATTR]
        kinds.append(dep.kind)
    return kinds


def _deduplicate_paths(paths: list[list[str]]) -> list[list[str]]:
    """Remove duplicate node-sequence paths, preserving all unique ones."""
    seen: set[tuple[str, ...]] = set()
    unique: list[list[str]] = []
    for path in paths:
        key = tuple(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique
