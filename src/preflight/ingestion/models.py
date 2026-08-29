"""Deterministic data contracts for the ingestion boundary."""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, Field, model_validator


class ManifestEntry(BaseModel):
    """One file discovered inside an ingested project."""

    model_config = {"frozen": True}

    path: str = Field(
        ..., min_length=1, description="POSIX-normalized path relative to project root."
    )
    language: str | None = Field(default=None)
    size: int = Field(..., ge=0)
    sha256: str = Field(..., min_length=64, max_length=64)
    classification: str = Field(
        ...,
        description=(
            "One of: semantic, migration, schema, api_contract, unsupported, ignored, other."
        ),
    )
    ignored_reason: str | None = Field(default=None)


class ProjectManifest(BaseModel):
    """Deterministic inventory of an ingested project, independent of analysis."""

    model_config = {"frozen": True}

    files: tuple[ManifestEntry, ...] = Field(default_factory=tuple)
    file_count: int = Field(..., ge=0)
    ignored_count: int = Field(..., ge=0)
    language_counts: dict[str, int] = Field(default_factory=dict)
    unsupported_count: int = Field(default=0, ge=0)
    framework_signals: tuple[str, ...] = Field(
        default_factory=tuple,
        description=(
            "Repository-relative paths of recognized project-marker files "
            "(package.json, pyproject.toml, go.mod, ...) — informational "
            "signals for root/boundary detection, never a hardcoded root."
        ),
    )
    manifest_hash: str = Field(default="")

    @model_validator(mode="after")
    def _sort_files(self) -> ProjectManifest:
        object.__setattr__(self, "files", tuple(sorted(self.files, key=lambda f: f.path)))
        object.__setattr__(self, "framework_signals", tuple(sorted(self.framework_signals)))
        return self

    def with_hash(self) -> ProjectManifest:
        payload = self.model_dump(mode="json", exclude={"manifest_hash"})
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        return self.model_copy(update={"manifest_hash": digest})


__all__ = ["ManifestEntry", "ProjectManifest"]
