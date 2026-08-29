"""Deterministic repository comparison — turns two extracted snapshots into a ``ChangeSet``.

This module never executes anything from either snapshot: every operation is
a filesystem stat, a content read for hashing, or a path-string
classification. It never depends on directory walk order or archive-entry
order — every collection is sorted by relative path before use, and file
identity is SHA-256 content, never mtime or filename alone.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from preflight.domain.change_set import (
    ChangeDomain,
    ChangeSet,
    ChangeSource,
    FileChange,
    FileChangeStatus,
    RepositoryDiff,
)
from preflight.ingestion.discovery import (
    API_CONTRACT_NAMES,
    PROJECT_MARKER_NAMES,
    PROJECT_MARKER_SUFFIXES,
    SEMANTIC_SUFFIXES,
    UNSUPPORTED_SOURCE_SUFFIXES,
    is_ignored,
)

_DEPLOYMENT_SUFFIXES = frozenset({".tf", ".tfvars", ".hcl"})
_CONFIG_NAMES = frozenset(
    {
        "config.yaml",
        "config.yml",
        "config.json",
        "settings.yaml",
        "settings.yml",
        "application.yml",
        "application.yaml",
        "application.properties",
    }
)


def _sha256_of(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def classify_change_domain(relative_path: str) -> tuple[ChangeDomain, ...]:
    """Map one repository-relative path to the real evidence domain(s) it belongs to.

    Pure filename/path classification, evidenced by real, well-known naming
    conventions (Dockerfile, docker-compose.yml, package.json, .env, ...) —
    never a guess and never risk-bearing. A path can carry more than one
    domain (e.g. a ``.sql`` file is DATABASE only; a ``Dockerfile`` is
    DEPLOYMENT only) or none of the recognized ones, in which case it is
    UNKNOWN rather than silently dropped.
    """
    path = Path(relative_path)
    suffix = path.suffix.lower()
    name = path.name.lower()
    parts_lower = [p.lower() for p in path.parts]
    domains: set[ChangeDomain] = set()

    if suffix in SEMANTIC_SUFFIXES or suffix in UNSUPPORTED_SOURCE_SUFFIXES:
        domains.add(ChangeDomain.SOURCE)
    if suffix == ".sql":
        domains.add(ChangeDomain.DATABASE)
    if name in API_CONTRACT_NAMES:
        domains.add(ChangeDomain.API)
    if (
        name == "dockerfile"
        or name.startswith("docker-compose")
        or suffix in _DEPLOYMENT_SUFFIXES
        or "helm" in parts_lower
        or "k8s" in parts_lower
        or "kubernetes" in parts_lower
        or (".github" in parts_lower and "workflows" in parts_lower)
        or name.startswith(".gitlab-ci")
    ):
        domains.add(ChangeDomain.DEPLOYMENT)
    if name in PROJECT_MARKER_NAMES or suffix in PROJECT_MARKER_SUFFIXES:
        domains.add(ChangeDomain.DEPENDENCY)
    if name.startswith(".env") or name in _CONFIG_NAMES:
        domains.add(ChangeDomain.CONFIG)

    if not domains:
        domains.add(ChangeDomain.UNKNOWN)
    return tuple(sorted(domains, key=lambda d: d.value))


def _content_index(root: Path) -> dict[str, tuple[str, int]]:
    """``{relative_posix_path: (sha256, size)}`` for every non-ignored file under ``root``."""
    index: dict[str, tuple[str, int]] = {}
    for path in root.rglob("*"):
        if not path.is_file() or is_ignored(path, root):
            continue
        relative = path.relative_to(root).as_posix()
        try:
            index[relative] = (_sha256_of(path), path.stat().st_size)
        except OSError:
            index[relative] = ("0" * 64, 0)
    return index


def compare_repositories(
    old_root: Path, new_root: Path, *, old_label: str, new_label: str
) -> RepositoryDiff:
    """Deterministically diff two extracted repository snapshots by content identity."""
    old_index = _content_index(old_root)
    new_index = _content_index(new_root)

    all_paths = sorted(set(old_index) | set(new_index))
    files: list[FileChange] = []
    added = removed = modified = same = 0

    for relative in all_paths:
        old_entry = old_index.get(relative)
        new_entry = new_index.get(relative)
        domains = classify_change_domain(relative)

        if old_entry is not None and new_entry is not None:
            status = (
                FileChangeStatus.SAME
                if old_entry[0] == new_entry[0]
                else FileChangeStatus.MODIFIED
            )
            old_sha, old_size = old_entry
            new_sha, new_size = new_entry
        elif old_entry is not None:
            status = FileChangeStatus.REMOVED
            old_sha, old_size = old_entry
            new_sha, new_size = None, None
        else:
            assert new_entry is not None
            status = FileChangeStatus.ADDED
            old_sha, old_size = None, None
            new_sha, new_size = new_entry

        if status is FileChangeStatus.SAME:
            same += 1
        elif status is FileChangeStatus.ADDED:
            added += 1
        elif status is FileChangeStatus.REMOVED:
            removed += 1
        else:
            modified += 1

        files.append(
            FileChange(
                path=relative,
                status=status,
                domains=domains,
                old_sha256=old_sha,
                new_sha256=new_sha,
                old_size=old_size,
                new_size=new_size,
            )
        )

    diff = RepositoryDiff(
        old_label=old_label,
        new_label=new_label,
        files=tuple(files),
        added_count=added,
        removed_count=removed,
        modified_count=modified,
        same_count=same,
    )
    return diff.with_hash()


def build_change_set(diff: RepositoryDiff) -> ChangeSet:
    """Wrap a ``RepositoryDiff`` into the ``ChangeSet`` the orchestrator consumes."""
    changed_domains: set[ChangeDomain] = set()
    for file_change in diff.changed_files:
        changed_domains.update(file_change.domains)
    change_set = ChangeSet(
        source=ChangeSource.SNAPSHOT_PAIR,
        repository_diff=diff,
        changed_domains=tuple(changed_domains),
    )
    return change_set.with_hash()


__all__ = ["build_change_set", "classify_change_domain", "compare_repositories"]
