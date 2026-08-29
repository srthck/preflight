"""Language registry — maps file extensions to parser instances.

The registry is the single point where file extensions are resolved to
concrete parsers. It is deterministic: the same extension always maps
to the same parser.

Design principles
-----------------
- Unknown extensions produce a structured UNSUPPORTED_LANGUAGE diagnostic,
  not an exception.
- The registry is initialized once and shared; parsers are stateless.
- Parser instances are created eagerly to catch import errors at startup.
- The registry does NOT access the filesystem; callers pass file paths.

Supported extensions (Day 2)
-----------------------------
.py, .pyw  → PythonParser
.kt        → KotlinParser

All other extensions → UNSUPPORTED_LANGUAGE diagnostic
"""

from __future__ import annotations

from preflight.graph.parsers.base import SourceParser
from preflight.graph.parsers.diagnostics import DiagnosticCode, make_diagnostic
from preflight.graph.parsers.kotlin import KotlinParser
from preflight.graph.parsers.models import Language, ParseStatus, SourceFile, make_content_hash
from preflight.graph.parsers.python import PythonParser

# ---------------------------------------------------------------------------
# Extension map — deterministic, lowercase, forward-slash normalized
# ---------------------------------------------------------------------------

_EXTENSION_MAP: dict[str, Language] = {
    ".py": Language.PYTHON,
    ".pyw": Language.PYTHON,
    ".kt": Language.KOTLIN,
}


class LanguageRegistry:
    """Deterministic registry mapping file extensions to SourceParser instances.

    Usage::

        registry = LanguageRegistry()
        source_file = registry.parse_file(
            source_bytes=b"class Foo: ...",
            file_path="user-service/src/user_service.py",
            service_name="user-service",
        )
    """

    def __init__(self) -> None:
        # Eager initialization — fail fast if language packages are missing.
        self._parsers: dict[Language, SourceParser] = {
            Language.PYTHON: PythonParser(),
            Language.KOTLIN: KotlinParser(),
        }

    def get_parser(self, extension: str) -> SourceParser | None:
        """Return the parser for a given file extension, or None if unsupported.

        Parameters
        ----------
        extension:
            Lowercase file extension including dot (e.g. ``".py"``).
        """
        lang = _EXTENSION_MAP.get(extension.lower())
        if lang is None:
            return None
        return self._parsers[lang]

    def supported_extensions(self) -> frozenset[str]:
        """Return the set of supported file extensions."""
        return frozenset(_EXTENSION_MAP.keys())

    def parse_file(
        self,
        source_bytes: bytes,
        file_path: str,
        service_name: str,
    ) -> SourceFile:
        """Parse a source file and return a SourceFile.

        For unsupported extensions, returns a SourceFile with
        parse_status=PARSE_FAILURE and a UNSUPPORTED_LANGUAGE diagnostic.
        This is never a silent failure.

        Parameters
        ----------
        source_bytes:
            Raw source bytes. Never executed.
        file_path:
            Project-relative path (forward slashes).
        service_name:
            Logical service that owns this file.
        """
        ext = _file_extension(file_path)
        parser = self.get_parser(ext)

        if parser is None:
            diag = make_diagnostic(
                DiagnosticCode.UNSUPPORTED_LANGUAGE,
                (
                    f"File extension {ext!r} is not supported. "
                    f"Supported: {sorted(self.supported_extensions())}."
                ),
                file_path,
            )
            return SourceFile(
                file_path=file_path,
                # We cannot determine the language, so we use PYTHON as a
                # placeholder — the parse_status makes the real situation clear.
                language=Language.PYTHON,
                parse_status=ParseStatus.PARSE_FAILURE,
                content_hash=make_content_hash(source_bytes),
                diagnostics=(diag,),
            )

        return parser.parse(source_bytes, file_path, service_name)

    def language_for_extension(self, extension: str) -> Language | None:
        """Return the Language enum for an extension, or None."""
        return _EXTENSION_MAP.get(extension.lower())


def _file_extension(file_path: str) -> str:
    """Extract the lowercase file extension from a path string."""
    # Use str operations — we deliberately avoid pathlib here to keep
    # this function dependency-free and testable with plain strings.
    dot_idx = file_path.rfind(".")
    if dot_idx == -1:
        return ""
    return file_path[dot_idx:].lower()
