"""Canonical, deterministic graph serialization.

Determinism contract
--------------------
Given identical normalized input, ``canonical_graph()`` must produce
identical output — including identical byte sequences — across all
invocations, Python processes, and operating systems.

To guarantee this:

1. Nodes are sorted by ``entity_id`` (stable string sort).
2. Edges are sorted by ``(source, target, kind.value)`` (all stable strings).
3. ``json.dumps`` is called with ``sort_keys=True`` and ``separators=(',', ':')``.
4. The following values are NEVER included in canonical output:
   - Wall-clock timestamps.
   - Memory addresses.
   - Random or UUID identifiers.
   - Entity ``metadata`` dicts (extension data, not part of identity).
   - Edge ``metadata`` dicts.

SHA-256 verification
--------------------
``canonical_sha256()`` computes the SHA-256 digest of the UTF-8-encoded
canonical JSON.  Use this in tests to assert byte-level determinism.
DO NOT use the hash as a production "Determinism Verification Hash" yet;
that infrastructure belongs to Day 11.

See docs/DETERMINISM.md for the full specification.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from preflight.graph.builder import PreFlightGraph


def canonical_graph(graph: PreFlightGraph) -> dict[str, Any]:
    """Return a canonical dictionary representation of ``graph``.

    The dictionary is suitable for JSON serialization via ``json.dumps``
    with ``sort_keys=True`` to guarantee a stable byte sequence.

    Structure::

        {
          "schema_version": "1.0",
          "nodes": [
            {
              "entity_id": "...",
              "name": "...",
              "kind": "...",
              "service": "...",
              "file": "..." | null,
              "line": int | null
            },
            ...   # sorted by entity_id
          ],
          "edges": [
            {
              "source": "...",
              "target": "...",
              "kind": "...",
              "weight": float
            },
            ...   # sorted by (source, target, kind)
          ]
        }

    ``metadata`` fields are intentionally excluded; they are extension data
    and must not influence canonical identity.
    """
    # Nodes sorted by entity_id.
    sorted_entity_ids = sorted(graph.entity_ids)
    nodes: list[dict[str, Any]] = []
    for eid in sorted_entity_ids:
        entity = graph.get_entity(eid)
        nodes.append(
            {
                "entity_id": entity.entity_id,
                "name": entity.name,
                "kind": entity.kind.value,
                "service": entity.service,
                "file": entity.file,
                "line": entity.line,
            }
        )

    # Edges sorted by (source, target, kind.value).
    sorted_edges = graph.get_dependencies()
    edges: list[dict[str, Any]] = []
    for edge in sorted_edges:
        edges.append(
            {
                "source": edge.source,
                "target": edge.target,
                "kind": edge.kind.value,
                "weight": edge.weight,
            }
        )

    return {
        "schema_version": "1.0",
        "nodes": nodes,
        "edges": edges,
    }


def canonical_json(graph: PreFlightGraph) -> str:
    """Return the canonical JSON string for ``graph``.

    Uses ``sort_keys=True`` and compact ``separators=(',', ':')`` to
    eliminate all non-deterministic whitespace and key ordering.
    """
    data = canonical_graph(graph)
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_sha256(graph: PreFlightGraph) -> str:
    """Return the SHA-256 hex digest of the canonical JSON for ``graph``.

    The digest is computed over UTF-8-encoded bytes of :func:`canonical_json`.
    Identical input graphs must always produce identical digests.

    This is the Day 1 determinism verification primitive.
    See docs/DETERMINISM.md.
    """
    encoded = canonical_json(graph).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
