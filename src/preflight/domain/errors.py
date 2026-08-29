"""Domain-specific exceptions for PreFlight.

All exceptions derive from PreFlightError, allowing callers to catch the
full domain surface with a single base class while still being able to
distinguish specific failure modes.

Low-level library errors (e.g. NetworkX exceptions) must be wrapped into
these types at the boundary where they are caught. Raw library exceptions
must not escape into callers as the application's contract.
"""

from __future__ import annotations


class PreFlightError(Exception):
    """Base class for all PreFlight domain errors."""


class GraphValidationError(PreFlightError):
    """Raised when a graph-construction operation violates a domain invariant.

    Examples:
    * An edge references an entity_id that has not been registered.
    * Graph construction is called on an invalid state.
    """


class DuplicateEntityError(GraphValidationError):
    """Raised when an entity with an already-registered entity_id is added.

    This protects the deterministic identity contract: two distinct entities
    must never share the same entity_id.
    """

    def __init__(self, entity_id: str) -> None:
        super().__init__(
            f"Entity with entity_id {entity_id!r} is already registered in this graph."
        )
        self.entity_id = entity_id


class UnknownEntityError(GraphValidationError):
    """Raised when a reference is made to an entity_id that does not exist.

    Typically surfaced when adding an edge whose source or target has not
    been registered.
    """

    def __init__(self, entity_id: str, *, context: str = "") -> None:
        detail = f" ({context})" if context else ""
        super().__init__(
            f"No entity with entity_id {entity_id!r} is registered{detail}."
        )
        self.entity_id = entity_id


class InvalidDependencyError(GraphValidationError):
    """Raised when a dependency edge fails a domain-level validation rule.

    Examples:
    * Self-loop edge (source == target).
    * Duplicate edge with identical source, target, and kind.
    """
