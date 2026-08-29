"""Hard limits enforced before and during archive extraction.

These are deliberately simple module-level constants, not a configuration
layer — this is a single-tenant demo ingestion path, not a production
multi-tenant upload service. Tightening them later is a one-line change.
"""

from __future__ import annotations

MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
"""Maximum accepted size of the uploaded (compressed) archive itself."""

MAX_UNCOMPRESSED_BYTES = 150 * 1024 * 1024
"""Maximum total size of all extracted file contents combined."""

MAX_FILE_COUNT = 5000
"""Maximum number of entries an archive may contain."""

MAX_SINGLE_FILE_BYTES = 20 * 1024 * 1024
"""Maximum uncompressed size of any single entry."""

MAX_COMPRESSION_RATIO = 200
"""An entry whose uncompressed size exceeds this multiple of its compressed
size is treated as a decompression-bomb candidate and rejected, provided
its uncompressed size also exceeds ``BOMB_RATIO_MIN_SIZE`` (small files
legitimately compress well and must not trip this check)."""

BOMB_RATIO_MIN_SIZE = 1 * 1024 * 1024

__all__ = [
    "BOMB_RATIO_MIN_SIZE",
    "MAX_ARCHIVE_BYTES",
    "MAX_COMPRESSION_RATIO",
    "MAX_FILE_COUNT",
    "MAX_SINGLE_FILE_BYTES",
    "MAX_UNCOMPRESSED_BYTES",
]
