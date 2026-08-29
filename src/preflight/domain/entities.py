"""Core entity model for the PreFlight domain.

An Entity represents any tracked artifact in the system under analysis:
a database column, a service, an API, a client, etc.

Design notes
------------
* ``entity_id`` is the stable identity key. It must be determined by the
  *caller* from stable, deterministic inputs — never generated randomly here.
  See docs/DETERMINISM.md for the canonical ID formation rules.
* All fields that are optional in production use ``None`` as sentinel rather
  than empty strings, to avoid ambiguity.
* ``metadata`` is an open dict for future extension; it must not be used for
  identity or comparison purposes in Day 1.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from preflight.domain.enums import EntityKind


class Entity(BaseModel):
    """A tracked artifact in the system under analysis.

    ``entity_id`` uniquely identifies the entity across all analysis runs.
    It must be derived deterministically from stable inputs, for example::

        "users.phone_number"       # <table>.<column>
        "user-service.UserService" # <service-name>.<symbol>
        "profile-api.ProfileAPI"   # <service-name>.<symbol>
        "android-client.ProfileClient"

    The model is immutable after construction (``model_config`` enforces this).
    """

    model_config = {"frozen": True}

    entity_id: str = Field(
        ...,
        description="Stable, deterministic identifier. Must not be random or time-based.",
        min_length=1,
    )
    name: str = Field(..., description="Human-readable name of the entity.", min_length=1)
    kind: EntityKind = Field(..., description="Semantic classification of this entity.")
    service: str = Field(
        ...,
        description=(
            "Logical service or component that owns this entity. "
            "For database entities this is the database name (e.g. 'demo-commerce-db')."
        ),
        min_length=1,
    )
    file: str | None = Field(
        default=None,
        description="Source-file path relative to the repository root, if known.",
    )
    line: int | None = Field(
        default=None,
        description="Line number within ``file`` where the entity is defined, if known.",
        ge=1,
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Arbitrary extension data. Must not be used for identity, sorting, "
            "or comparison. Excluded from canonical serialization."
        ),
    )

    @field_validator("entity_id")
    @classmethod
    def entity_id_must_not_contain_whitespace(cls, value: str) -> str:
        """Entity IDs must not contain whitespace — they are used as graph keys."""
        if any(ch.isspace() for ch in value):
            raise ValueError(
                f"entity_id must not contain whitespace, got: {value!r}"
            )
        return value
