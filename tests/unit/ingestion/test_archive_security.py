"""Adversarial ZIP-ingestion test matrix.

Every test here proves a specific attack shape is rejected before a single
byte is written to disk outside the isolated extraction directory. Limits
are monkeypatched down to small values so the tests stay fast without
weakening what the module actually enforces at its real thresholds.
"""

from __future__ import annotations

import io
import stat
import zipfile

import pytest

from preflight.ingestion import archive
from preflight.ingestion.errors import (
    ArchiveTooLargeError,
    MalformedArchiveError,
    TooManyFilesError,
    UnsafeArchiveError,
)
from preflight.ingestion.manifest import build_manifest


def _zip_bytes(entries: dict[str, bytes], *, symlink: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "target.txt")
    return buf.getvalue()


# TEST 1 — valid ZIP is accepted, and only within the isolated extraction root.
def test_valid_zip_is_accepted() -> None:
    data = _zip_bytes({"app/main.py": b"print(1)\n", "app/database/schema.sql": b"CREATE TABLE t();\n"})
    with archive.extracted_project(data) as root:
        assert (root / "app" / "main.py").exists()
        assert (root / "app" / "database" / "schema.sql").exists()
    assert not root.exists()  # cleaned up on exit


# TEST 2/3 — POSIX-style path traversal, shallow and deep.
@pytest.mark.parametrize("evil_name", ["../../etc/escape.txt", "../../../../tmp/escape"])
def test_posix_path_traversal_is_rejected(evil_name: str) -> None:
    data = _zip_bytes({evil_name: b"pwned"})
    with pytest.raises(UnsafeArchiveError, match="traversal"), archive.extracted_project(data):
        pass


# TEST 4 — absolute paths (POSIX and Windows drive-letter form).
@pytest.mark.parametrize("evil_name", ["/etc/passwd", "C:/Windows/System32/evil.dll"])
def test_absolute_path_is_rejected(evil_name: str) -> None:
    data = _zip_bytes({evil_name: b"pwned"})
    with pytest.raises(UnsafeArchiveError, match="absolute path"), archive.extracted_project(data):
        pass


# TEST 5 — Windows-style backslash traversal.
def test_windows_style_traversal_is_rejected() -> None:
    data = _zip_bytes({"..\\..\\escape.txt": b"pwned"})
    with pytest.raises(UnsafeArchiveError, match="traversal"), archive.extracted_project(data):
        pass


# TEST 6 — symlink entries are rejected outright.
def test_symlink_entry_is_rejected() -> None:
    data = _zip_bytes({}, symlink="link.txt")
    with pytest.raises(UnsafeArchiveError, match="symlink"), archive.extracted_project(data):
        pass


# TEST 7 — oversized (compressed) archive.
def test_oversized_archive_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(archive, "MAX_ARCHIVE_BYTES", 10)
    data = _zip_bytes({"app/main.py": b"print(1)\n" * 50})
    assert len(data) > 10
    with pytest.raises(ArchiveTooLargeError), archive.extracted_project(data):
        pass


# TEST 8 — excessive declared uncompressed size (zip-bomb shape).
def test_excessive_uncompressed_size_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(archive, "MAX_SINGLE_FILE_BYTES", 1_000_000)
    monkeypatch.setattr(archive, "MAX_UNCOMPRESSED_BYTES", 100)
    data = _zip_bytes({"app/main.py": b"x" * 1000})
    with pytest.raises(ArchiveTooLargeError), archive.extracted_project(data):
        pass


def test_suspicious_compression_ratio_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(archive, "BOMB_RATIO_MIN_SIZE", 100)
    monkeypatch.setattr(archive, "MAX_COMPRESSION_RATIO", 5)
    # Highly compressible content triggers a large real/compressed ratio.
    data = _zip_bytes({"app/bomb.txt": b"0" * 200_000})
    with pytest.raises(UnsafeArchiveError, match="compression ratio"), archive.extracted_project(data):
        pass


# TEST 9 — excessive file count.
def test_excessive_file_count_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(archive, "MAX_FILE_COUNT", 3)
    data = _zip_bytes({f"file_{i}.py": b"x" for i in range(10)})
    with pytest.raises(TooManyFilesError), archive.extracted_project(data):
        pass


# TEST 10 — malformed / corrupted ZIP.
def test_malformed_archive_is_rejected() -> None:
    with pytest.raises(MalformedArchiveError), archive.extracted_project(b"not a zip file at all"):
        pass


def test_corrupted_zip_crc_is_rejected() -> None:
    content = b"print('hello world')\n" * 5
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("app/main.py", content)
    data = bytearray(buf.getvalue())

    # ZIP_STORED embeds the file's bytes verbatim, so the literal content is
    # guaranteed to be locatable and flipping a byte inside it corrupts the
    # entry's CRC without touching the ZIP directory structure around it.
    offset = data.find(content)
    assert offset != -1
    data[offset] ^= 0xFF

    with pytest.raises(MalformedArchiveError), archive.extracted_project(bytes(data)):
        pass


# TEST 11 — nested archive: not extracted recursively, classified as ignored.
def test_nested_archive_is_classified_ignored_not_extracted() -> None:
    inner = _zip_bytes({"whatever.py": b"print(1)"})
    data = _zip_bytes({"app/main.py": b"print(1)\n", "bundled/inner.zip": inner})
    with archive.extracted_project(data) as root:
        manifest = build_manifest(root)
        inner_entry = next(f for f in manifest.files if f.path == "bundled/inner.zip")
        assert inner_entry.classification == "ignored"
        # The nested archive's own contents must never appear as top-level files.
        assert not any(f.path == "whatever.py" for f in manifest.files)


# TEST 12 — binary-heavy project extracts and manifests without crashing.
def test_binary_heavy_project_is_handled_gracefully() -> None:
    data = _zip_bytes(
        {
            "app/main.py": b"print(1)\n",
            "assets/logo.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 200,
            "assets/font.woff2": b"\x00" * 500,
        }
    )
    with archive.extracted_project(data) as root:
        manifest = build_manifest(root)
    classifications = {f.path: f.classification for f in manifest.files}
    assert classifications["app/main.py"] == "semantic"
    assert classifications["assets/logo.png"] == "ignored"
    assert classifications["assets/font.woff2"] == "ignored"


# TEST 13 — unsupported (but recognized) source language is labeled honestly.
def test_unsupported_language_is_explicitly_labeled() -> None:
    data = _zip_bytes({"app/server.go": b"package main\n"})
    with archive.extracted_project(data) as root:
        manifest = build_manifest(root)
    entry = next(f for f in manifest.files if f.path == "app/server.go")
    assert entry.classification == "unsupported"
    assert entry.ignored_reason is not None and "go" in entry.ignored_reason
