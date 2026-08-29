"""Safe extraction of an untrusted ZIP archive.

The one rule this module exists to enforce: no path derived from an
archive entry is ever written outside the isolated extraction directory,
and no archive is trusted to describe its own size honestly. Every entry
is validated *before* anything is written, and every byte actually written
is counted and bounded independently of what the archive's own headers
claim.
"""

from __future__ import annotations

import io
import posixpath
import shutil
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

from preflight.ingestion.errors import (
    ArchiveTooLargeError,
    MalformedArchiveError,
    TooManyFilesError,
    UnsafeArchiveError,
)
from preflight.ingestion.limits import (
    BOMB_RATIO_MIN_SIZE,
    MAX_ARCHIVE_BYTES,
    MAX_COMPRESSION_RATIO,
    MAX_FILE_COUNT,
    MAX_SINGLE_FILE_BYTES,
    MAX_UNCOMPRESSED_BYTES,
)

_S_IFLNK = 0o120000
_READ_CHUNK = 65536


@contextmanager
def extracted_project(archive_bytes: bytes) -> Iterator[Path]:
    """Validate and extract ``archive_bytes`` into an isolated temp directory.

    Yields the extraction root while the context is open. The directory —
    and everything written into it — is deleted unconditionally on exit,
    whether extraction succeeded or a later analysis step raised.

    Raises
    ------
    ArchiveTooLargeError, TooManyFilesError, MalformedArchiveError, UnsafeArchiveError
    """
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise ArchiveTooLargeError(
            f"archive is {len(archive_bytes)} bytes; the limit is {MAX_ARCHIVE_BYTES} bytes"
        )

    temp_root = Path(tempfile.mkdtemp(prefix="preflight-upload-"))
    try:
        _extract_validated(archive_bytes, temp_root)
        yield temp_root
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def _extract_validated(archive_bytes: bytes, temp_root: Path) -> None:
    try:
        zf = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except zipfile.BadZipFile as exc:
        raise MalformedArchiveError(f"not a valid ZIP archive: {exc}") from exc

    with zf:
        try:
            infolist = zf.infolist()
        except (zipfile.BadZipFile, OSError, ValueError) as exc:
            raise MalformedArchiveError(f"could not read archive directory: {exc}") from exc

        if len(infolist) > MAX_FILE_COUNT:
            raise TooManyFilesError(
                f"archive contains {len(infolist)} entries; the limit is {MAX_FILE_COUNT}"
            )

        try:
            first_bad = zf.testzip()
        except (zipfile.BadZipFile, OSError, ValueError, RuntimeError) as exc:
            raise MalformedArchiveError(f"archive failed integrity check: {exc}") from exc
        if first_bad is not None:
            raise MalformedArchiveError(f"archive entry failed its CRC check: {first_bad!r}")

        planned = _plan_extraction(infolist, temp_root)
        _write_planned_entries(zf, planned)


def _plan_extraction(
    infolist: list[zipfile.ZipInfo], temp_root: Path
) -> list[tuple[zipfile.ZipInfo, Path]]:
    """Validate every entry and compute its destination before writing anything."""
    planned: list[tuple[zipfile.ZipInfo, Path]] = []
    total_declared = 0
    for info in infolist:
        destination = _safe_destination(info.filename, temp_root)
        if info.is_dir():
            planned.append((info, destination))
            continue
        if _is_symlink_entry(info):
            raise UnsafeArchiveError(f"archive entry is a symlink: {info.filename!r}")
        if info.file_size > MAX_SINGLE_FILE_BYTES:
            raise ArchiveTooLargeError(
                f"{info.filename!r} declares {info.file_size} bytes; "
                f"the per-file limit is {MAX_SINGLE_FILE_BYTES}"
            )
        if info.file_size >= BOMB_RATIO_MIN_SIZE and info.compress_size > 0:
            ratio = info.file_size / info.compress_size
            if ratio > MAX_COMPRESSION_RATIO:
                raise UnsafeArchiveError(
                    f"{info.filename!r} has a suspicious compression ratio ({ratio:.0f}x); "
                    "rejected as a possible decompression bomb"
                )
        total_declared += info.file_size
        if total_declared > MAX_UNCOMPRESSED_BYTES:
            raise ArchiveTooLargeError(
                f"declared uncompressed contents exceed the {MAX_UNCOMPRESSED_BYTES}-byte limit"
            )
        planned.append((info, destination))
    return planned


def _write_planned_entries(
    zf: zipfile.ZipFile, planned: list[tuple[zipfile.ZipInfo, Path]]
) -> None:
    written_total = 0
    for info, destination in planned:
        if info.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with zf.open(info) as source, open(destination, "wb") as target:
                written_total += _copy_bounded(source, target, written_total)
        except (zipfile.BadZipFile, OSError) as exc:
            raise MalformedArchiveError(f"failed to extract {info.filename!r}: {exc}") from exc
        if destination.is_symlink():
            raise UnsafeArchiveError(f"extracted entry became a symlink: {info.filename!r}")


def _copy_bounded(source: IO[bytes], target: IO[bytes], already_written: int) -> int:
    """Copy ``source`` to ``target``, never trusting declared sizes.

    Enforces both the per-file limit and the running total limit against
    bytes actually read, independent of any header claim.
    """
    written = 0
    while True:
        chunk = source.read(_READ_CHUNK)
        if not chunk:
            break
        written += len(chunk)
        if written > MAX_SINGLE_FILE_BYTES:
            raise ArchiveTooLargeError(
                f"entry exceeded the {MAX_SINGLE_FILE_BYTES}-byte per-file limit during extraction"
            )
        if already_written + written > MAX_UNCOMPRESSED_BYTES:
            raise ArchiveTooLargeError(
                f"extraction exceeded the {MAX_UNCOMPRESSED_BYTES}-byte total limit"
            )
        target.write(chunk)
    return written


def _is_symlink_entry(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return (mode & 0o170000) == _S_IFLNK


def _safe_destination(name: str, extraction_root: Path) -> Path:
    """Return the validated destination path for one archive entry name.

    Rejects absolute paths (POSIX and Windows-drive-letter form) and any
    entry whose normalized path would resolve outside ``extraction_root``,
    including backslash-style (Windows) traversal sequences.
    """
    if not name or not name.strip():
        raise UnsafeArchiveError("archive entry has an empty name")

    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        raise UnsafeArchiveError(f"archive entry has an absolute path: {name!r}")
    if len(normalized) >= 2 and normalized[1] == ":" and normalized[0].isalpha():
        raise UnsafeArchiveError(f"archive entry has an absolute path: {name!r}")

    posix_normalized = posixpath.normpath(normalized)
    parts = posix_normalized.split("/")
    if posix_normalized in {".", ""} :
        raise UnsafeArchiveError(f"archive entry resolves to the extraction root: {name!r}")
    if any(part == ".." for part in parts):
        raise UnsafeArchiveError(f"archive entry attempts path traversal: {name!r}")

    root_resolved = extraction_root.resolve()
    destination = (extraction_root / posix_normalized).resolve()
    try:
        destination.relative_to(root_resolved)
    except ValueError as exc:
        raise UnsafeArchiveError(f"archive entry escapes the extraction root: {name!r}") from exc
    return destination


__all__ = ["extracted_project"]
