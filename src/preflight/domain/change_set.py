"""The ``ChangeSet`` domain model — what is actually changing between two states.

PreFlight's unit of analysis is the change, not the file and not the ZIP.
``ChangeSource`` enumerates where a ``ChangeSet`` can come from; only
``SNAPSHOT_PAIR`` (two full repository snapshots, old and new) is
implemented today. The others are declared so the model is extensible
without a breaking change later, per the P0.3 mission's explicit
instruction not to implement every source immediately.

Nothing in this module executes untrusted content, opens a network
connection, or depends on filesystem/ZIP-entry ordering: every collection
here is sorted before hashing.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ChangeSource(str, Enum):
    """Where a ``ChangeSet``'s evidence came from."""

    SNAPSHOT_PAIR = "SNAPSHOT_PAIR"
    GIT_DIFF = "GIT_DIFF"
    MIGRATION = "MIGRATION"
    API_DIFF = "API_DIFF"
    SOURCE_DIFF = "SOURCE_DIFF"


class FileChangeStatus(str, Enum):
    """One file's status between the OLD and NEW snapshot, by content identity."""

    SAME = "SAME"
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    MODIFIED = "MODIFIED"


class ChangeDomain(str, Enum):
    """Which real evidence domain a changed file belongs to.

    Classification only — assigning a domain never implies risk. A file can
    belong to more than one domain (e.g. a single Python file can be both
    SOURCE and, if it embeds inline SQL literals recognized elsewhere,
    contribute to DATABASE evidence); this enum only labels the file, it does
    not compute impact.
    """

    SOURCE = "SOURCE"
    DATABASE = "DATABASE"
    API = "API"
    CONFIG = "CONFIG"
    DEPLOYMENT = "DEPLOYMENT"
    DEPENDENCY = "DEPENDENCY"
    UNKNOWN = "UNKNOWN"


class FileChange(BaseModel):
    """One file's deterministic before/after identity and domain classification."""

    model_config = {"frozen": True}

    path: str = Field(..., min_length=1)
    status: FileChangeStatus
    domains: tuple[ChangeDomain, ...] = Field(default_factory=tuple)
    old_sha256: str | None = Field(default=None)
    new_sha256: str | None = Field(default=None)
    old_size: int | None = Field(default=None, ge=0)
    new_size: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _sort_domains(self) -> FileChange:
        object.__setattr__(self, "domains", tuple(sorted(self.domains, key=lambda d: d.value)))
        return self


class RepositoryDiff(BaseModel):
    """A deterministic, content-hash-based comparison of two repository snapshots.

    Built exclusively from SHA-256 content identity — never filenames alone,
    never filesystem or ZIP-entry order. Two runs over the same two snapshot
    byte-streams, extracted in any order, on any OS, produce an identical
    ``diff_hash``.
    """

    model_config = {"frozen": True}

    old_label: str
    new_label: str
    files: tuple[FileChange, ...] = Field(default_factory=tuple)
    added_count: int = Field(default=0, ge=0)
    removed_count: int = Field(default=0, ge=0)
    modified_count: int = Field(default=0, ge=0)
    same_count: int = Field(default=0, ge=0)
    diff_hash: str = Field(default="")

    @model_validator(mode="after")
    def _sort_files(self) -> RepositoryDiff:
        object.__setattr__(self, "files", tuple(sorted(self.files, key=lambda f: f.path)))
        return self

    @property
    def changed_files(self) -> tuple[FileChange, ...]:
        """Every file whose status is not SAME — the real diff, added/removed/modified."""
        return tuple(f for f in self.files if f.status != FileChangeStatus.SAME)

    def with_hash(self) -> RepositoryDiff:
        payload = self.model_dump(mode="json", exclude={"diff_hash"})
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return self.model_copy(update={"diff_hash": digest})


class ChangeSet(BaseModel):
    """What is actually changing — the core unit PreFlight analyzes.

    A ``ChangeSet`` is never risk-scored itself; it is the deterministic
    input handed to the analyzers (blast radius, deployment rehearsal, API
    contract, rollback) that produce evidence, which ``decide()`` then
    scores. This model intentionally carries no severity or decision field.
    """

    model_config = {"frozen": True}

    source: ChangeSource
    repository_diff: RepositoryDiff | None = Field(default=None)
    changed_domains: tuple[ChangeDomain, ...] = Field(default_factory=tuple)
    change_set_hash: str = Field(default="")

    @model_validator(mode="after")
    def _sort_domains(self) -> ChangeSet:
        object.__setattr__(
            self, "changed_domains", tuple(sorted(set(self.changed_domains), key=lambda d: d.value))
        )
        return self

    def with_hash(self) -> ChangeSet:
        payload: dict[str, Any] = self.model_dump(mode="json", exclude={"change_set_hash"})
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return self.model_copy(update={"change_set_hash": digest})


__all__ = [
    "ChangeDomain",
    "ChangeSet",
    "ChangeSource",
    "FileChange",
    "FileChangeStatus",
    "RepositoryDiff",
]
