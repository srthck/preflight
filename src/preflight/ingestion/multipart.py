"""Minimal ``multipart/form-data`` parser for the upload endpoint.

Deliberately not using the standard-library ``cgi`` module: it is
deprecated since Python 3.11 and removed in 3.13, and this project targets
3.10-3.12. This parser handles exactly what a browser's ``FormData``/
``fetch`` upload produces — it is not a general MIME parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from preflight.ingestion.errors import MalformedArchiveError

_BOUNDARY_RE = re.compile(r'boundary="?([^";]+)"?', re.IGNORECASE)
_DISPOSITION_RE = re.compile(r'Content-Disposition:\s*form-data;([^\r\n]*)', re.IGNORECASE)
_NAME_RE = re.compile(r'name="([^"]*)"')
_FILENAME_RE = re.compile(r'filename="([^"]*)"')


@dataclass(frozen=True)
class MultipartField:
    name: str
    filename: str | None
    content: bytes


def extract_boundary(content_type: str) -> str:
    match = _BOUNDARY_RE.search(content_type or "")
    if not match:
        raise MalformedArchiveError("multipart request is missing a boundary")
    return match.group(1)


def parse_multipart_form(content_type: str, body: bytes) -> dict[str, MultipartField]:
    """Parse a ``multipart/form-data`` body into named fields.

    Returns a mapping of field name to :class:`MultipartField`. Raises
    :class:`MalformedArchiveError` if the body cannot be parsed as valid
    multipart data — this is a client-input error, not a server fault.
    """
    boundary = extract_boundary(content_type)
    delimiter = b"--" + boundary.encode("utf-8")

    parts = body.split(delimiter)
    fields: dict[str, MultipartField] = {}
    for raw_part in parts:
        part = raw_part
        if part in (b"", b"--\r\n", b"--"):
            continue
        if part.startswith(b"\r\n"):
            part = part[2:]
        # A trailing "--\r\n" (final boundary) or plain "\r\n" remains on the
        # last real part's tail; strip one trailing CRLF if present.
        if part.endswith(b"\r\n"):
            part = part[:-2]
        if b"\r\n\r\n" not in part:
            continue
        header_block, _, content = part.partition(b"\r\n\r\n")
        headers = header_block.decode("utf-8", errors="replace")

        disposition_match = _DISPOSITION_RE.search(headers)
        if not disposition_match:
            continue
        params = disposition_match.group(1)
        name_match = _NAME_RE.search(params)
        if not name_match:
            continue
        filename_match = _FILENAME_RE.search(params)
        fields[name_match.group(1)] = MultipartField(
            name=name_match.group(1),
            filename=filename_match.group(1) if filename_match else None,
            content=content,
        )

    if not fields:
        raise MalformedArchiveError("multipart request contained no usable form fields")
    return fields


__all__ = ["MultipartField", "extract_boundary", "parse_multipart_form"]
