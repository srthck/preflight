"""Build a deterministic manifest of an ingested project.

The manifest is inventory, not analysis: it records what exists and how it
was classified for the analysis pipeline, with no risk, severity, or
decision content of its own.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from preflight.ingestion.discovery import classify, find_framework_signals, is_ignored
from preflight.ingestion.models import ManifestEntry, ProjectManifest

_LANGUAGE_BY_SUFFIX = {".py": "python", ".kt": "kotlin", ".sql": "sql"}


def build_manifest(root: Path) -> ProjectManifest:
    """Walk ``root`` and produce a sorted, content-hashed :class:`ProjectManifest`."""
    entries: list[ManifestEntry] = []
    language_counts: dict[str, int] = {}
    ignored_count = 0
    unsupported_count = 0

    files = sorted(
        (p for p in root.rglob("*") if p.is_file()),
        key=lambda p: p.relative_to(root).as_posix(),
    )
    for path in files:
        relative = path.relative_to(root).as_posix()
        classification, reason = classify(path, root)
        try:
            size = path.stat().st_size
            digest = _sha256_of(path)
        except OSError:
            size = 0
            digest = "0" * 64
        language = (
            _LANGUAGE_BY_SUFFIX.get(path.suffix.lower()) if not is_ignored(path, root) else None
        )
        if classification == "api_contract":
            language = language or "openapi"
        entries.append(
            ManifestEntry(
                path=relative,
                language=language,
                size=size,
                sha256=digest,
                classification=classification,
                ignored_reason=reason,
            )
        )
        if classification == "ignored":
            ignored_count += 1
        if classification == "unsupported":
            unsupported_count += 1
        if language:
            language_counts[language] = language_counts.get(language, 0) + 1

    manifest = ProjectManifest(
        files=tuple(entries),
        file_count=len(entries),
        ignored_count=ignored_count,
        unsupported_count=unsupported_count,
        language_counts=language_counts,
        framework_signals=find_framework_signals(root),
    )
    return manifest.with_hash()


def _sha256_of(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


__all__ = ["build_manifest"]
