"""Enumerated types for the PreFlight domain.

These enums are intentionally kept narrow for Day 1.
New values must be justified by a concrete implementation requirement;
do not add speculative values.
"""

from enum import Enum


class EntityKind(str, Enum):
    """Classifies what a tracked entity *is* within the system under analysis."""

    DATABASE = "DATABASE"
    """A database table, view, or column — a persistent-storage artifact."""

    SERVICE = "SERVICE"
    """A backend service or microservice that exposes business logic."""

    API = "API"
    """An API surface (REST, gRPC, GraphQL endpoint, etc.)."""

    CLIENT = "CLIENT"
    """A consumer of an API — e.g. a mobile or web client."""

    SYMBOL = "SYMBOL"
    """A code-level symbol: function, class, or method within a service."""

    ENDPOINT = "ENDPOINT"
    """A specific URL route or RPC method within a service or API."""

    CONFIG = "CONFIG"
    """A configuration artefact whose change can affect runtime behaviour."""


class EdgeKind(str, Enum):
    """Classifies the *nature* of a dependency between two entities.

    Each value represents a distinct semantic relationship.
    The type drives impact-propagation rules in the analysis engine.
    """

    DB_READ = "DB_READ"
    """A service reads data from a database entity.

    Direction: database_entity --> service
    Example: users.phone_number --DB_READ--> UserService
    """

    DB_WRITE = "DB_WRITE"
    """A service writes data to a database entity.

    Direction: service --> database_entity
    Example: UserService --DB_WRITE--> users.phone_number
    """

    CALL = "CALL"
    """A function or service invokes another symbol or component.

    Direction: caller --> callee
    Example: UserService --CALL--> ProfileAPI
    """

    HTTP_CALL = "HTTP_CALL"
    """A service makes an outbound HTTP call to another service or API.

    Direction: caller --> callee
    Example: UserService --HTTP_CALL--> ProfileAPI
    """

    API_CONSUMES = "API_CONSUMES"
    """A client consumes an API endpoint.

    Direction: api --> client  (the API is the dependency source)
    Example: ProfileAPI --API_CONSUMES--> AndroidClient
    """

    IMPORT = "IMPORT"
    """A code module imports another module.

    Direction: importer --> imported
    Used by the future Tree-sitter parser (Day 2).
    """

    CONFIG_DEPENDENCY = "CONFIG_DEPENDENCY"
    """An entity depends on a configuration artefact.

    Direction: config --> dependent_entity
    Used by the future environment-analysis module (Day 7).
    """
