"""Secure ingestion boundary for uploaded project archives.

``extracted_project()`` (archive.py) is the only sanctioned way to turn
untrusted archive bytes into files on disk. ``build_manifest()``
(manifest.py) then inventories what was extracted, and the ``discovery``
module locates the specific files (semantic sources, migration SQL, schema
snapshot, API contract) the existing orchestration pipeline needs. This
package contains no analysis logic of its own — see
``preflight.orchestration.pipeline.run_project_analysis`` for how an
extracted project is handed to the real analyzers.
"""

from __future__ import annotations

from preflight.ingestion.archive import extracted_project
from preflight.ingestion.errors import (
    ArchiveTooLargeError,
    IngestionError,
    MalformedArchiveError,
    TooManyFilesError,
    UnsafeArchiveError,
)
from preflight.ingestion.manifest import build_manifest
from preflight.ingestion.models import ManifestEntry, ProjectManifest
from preflight.ingestion.multipart import MultipartField, parse_multipart_form

__all__ = [
    "ArchiveTooLargeError",
    "IngestionError",
    "ManifestEntry",
    "MalformedArchiveError",
    "MultipartField",
    "ProjectManifest",
    "TooManyFilesError",
    "UnsafeArchiveError",
    "build_manifest",
    "extracted_project",
    "parse_multipart_form",
]
