"""Demo-Commerce fixture loader.

This module defines the canonical Day 1 dependency graph for the
``demo-commerce`` fixture as explicit, typed domain objects.

Day 1 rationale
---------------
The graph is defined here as structured data rather than being parsed
from the fixture source files. Tree-sitter parsing (Day 2) will
eventually derive these relationships automatically from source code.

Until then, this loader serves as the single source of truth for:
* The four canonical entities.
* The three typed edges.
* The canonical 3-hop dependency path.

Entity ID formation rules (see docs/DETERMINISM.md)
----------------------------------------------------
Database columns:   "<table>.<column>"
Services/symbols:   "<service-name>.<ClassName>"
APIs:               "<service-name>.<ClassName>"
Clients:            "<service-name>.<ClassName>"

All IDs are lowercase-kebab for the service prefix and PascalCase for
the class suffix, matching the fixture source code identifiers.
"""

from __future__ import annotations

from preflight.domain.entities import Entity
from preflight.domain.enums import EdgeKind, EntityKind
from preflight.domain.graph_models import DependencyEdge
from preflight.graph.builder import GraphBuilder, PreFlightGraph

# ---------------------------------------------------------------------------
# Canonical entity IDs — stable, deterministic, never random
# ---------------------------------------------------------------------------

ENTITY_DB_COLUMN = "users.phone_number"
ENTITY_USER_SERVICE = "user-service.UserService"
ENTITY_PROFILE_API = "profile-api.ProfileAPI"
ENTITY_ANDROID_CLIENT = "android-client.ProfileClient"


def build_demo_commerce_graph() -> PreFlightGraph:
    """Construct and return the canonical Demo Commerce dependency graph.

    The graph encodes the following dependency chain::

        users.phone_number
          --DB_READ-->
        user-service.UserService
          --HTTP_CALL-->
        profile-api.ProfileAPI
          --API_CONSUMES-->
        android-client.ProfileClient

    This function is deterministic: calling it N times always produces
    graphs with identical canonical serializations.

    Returns
    -------
    PreFlightGraph
        A built, validated, immutable graph.
    """
    entities = _define_entities()
    edges = _define_edges()

    builder = GraphBuilder()
    for entity in entities:
        builder.add_entity(entity)
    for edge in edges:
        builder.add_dependency(edge)

    return builder.build()


# ---------------------------------------------------------------------------
# Internal definition functions — separated for testability
# ---------------------------------------------------------------------------


def _define_entities() -> list[Entity]:
    """Return the four canonical Demo Commerce entities.

    Returned in a deterministic order (alphabetical by entity_id) so that
    callers do not depend on definition order.
    """
    raw = [
        Entity(
            entity_id=ENTITY_ANDROID_CLIENT,
            name="ProfileClient",
            kind=EntityKind.CLIENT,
            service="android-client",
            file="fixtures/demo-commerce/android-client/src/profile_client.kt",
            line=10,
            metadata={"language": "kotlin", "platform": "android"},
        ),
        Entity(
            entity_id=ENTITY_DB_COLUMN,
            name="phone_number",
            kind=EntityKind.DATABASE,
            service="demo-commerce-db",
            file="fixtures/demo-commerce/database/schema.sql",
            line=6,
            metadata={"table": "users", "column_type": "TEXT", "nullable": True},
        ),
        Entity(
            entity_id=ENTITY_PROFILE_API,
            name="ProfileAPI",
            kind=EntityKind.API,
            service="profile-api",
            file="fixtures/demo-commerce/profile-api/src/profile_api.py",
            line=27,
            metadata={"framework": "fastapi", "route": "GET /profile/{user_id}"},
        ),
        Entity(
            entity_id=ENTITY_USER_SERVICE,
            name="UserService",
            kind=EntityKind.SERVICE,
            service="user-service",
            file="fixtures/demo-commerce/user-service/src/user_service.py",
            line=20,
            metadata={"language": "python"},
        ),
    ]
    # Sort by entity_id for deterministic definition order.
    return sorted(raw, key=lambda e: e.entity_id)


def _define_edges() -> list[DependencyEdge]:
    """Return the three canonical Demo Commerce dependency edges.

    Returned sorted by (source, target, kind.value) for determinism.
    """
    raw = [
        DependencyEdge(
            source=ENTITY_DB_COLUMN,
            target=ENTITY_USER_SERVICE,
            kind=EdgeKind.DB_READ,
            metadata={
                "description": (
                    "UserService reads users.phone_number from the database "
                    "to expose phone data to the profile layer."
                )
            },
        ),
        DependencyEdge(
            source=ENTITY_USER_SERVICE,
            target=ENTITY_PROFILE_API,
            kind=EdgeKind.HTTP_CALL,
            metadata={
                "description": (
                    "UserService forwards enriched user data (including phone_number) "
                    "to ProfileAPI via an internal HTTP call."
                )
            },
        ),
        DependencyEdge(
            source=ENTITY_PROFILE_API,
            target=ENTITY_ANDROID_CLIENT,
            kind=EdgeKind.API_CONSUMES,
            metadata={
                "description": (
                    "AndroidClient consumes the ProfileAPI GET /profile/{user_id} "
                    "endpoint and displays phone_number in the UI."
                )
            },
        ),
    ]
    return sorted(raw, key=lambda e: (e.source, e.target, e.kind.value))
