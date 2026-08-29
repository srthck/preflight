"""Ingestion-layer errors.

Every failure mode a caller needs to distinguish gets its own type so the
HTTP boundary can map it to a specific, honest status code and error
string — never a blanket 500, and never a silently-downgraded success.
"""

from __future__ import annotations

from preflight.domain.errors import PreFlightError


class IngestionError(PreFlightError):
    """Base class for all archive-ingestion failures."""


class MalformedArchiveError(IngestionError):
    """The upload is not a valid, readable ZIP archive."""


class UnsafeArchiveError(IngestionError):
    """The archive contains an entry that cannot be safely extracted.

    Path traversal, absolute paths, symlinks, and decompression-bomb
    ratios all raise this — the archive is well-formed ZIP, but its
    contents are not safe to place on disk.
    """


class ArchiveTooLargeError(IngestionError):
    """The archive (compressed or uncompressed) exceeds the configured limit."""


class TooManyFilesError(IngestionError):
    """The archive contains more entries than the configured limit."""


__all__ = [
    "ArchiveTooLargeError",
    "IngestionError",
    "MalformedArchiveError",
    "TooManyFilesError",
    "UnsafeArchiveError",
]
