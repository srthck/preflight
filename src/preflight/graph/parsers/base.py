"""Abstract base for all PreFlight language parsers.

Every language parser must implement SourceParser.
This abstraction allows the registry and extractor to operate
without knowing which language is being parsed.

Tree-sitter is used as the backing AST engine inside each concrete
implementation. However, this base class has no Tree-sitter imports —
the coupling to Tree-sitter is confined to python.py and kotlin.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from preflight.graph.parsers.models import Language, SourceFile


class SourceParser(ABC):
    """Abstract parser for a single source language.

    Responsibilities
    ----------------
    - Accept raw source bytes.
    - Produce a normalized :class:`~preflight.graph.parsers.models.SourceFile`.
    - Handle syntax errors gracefully — a malformed file must produce a
      SYNTAX_ERROR status and a diagnostic, not an exception.
    - Never execute the parsed source code.
    - Never access the filesystem, network, or environment.

    The parser must be stateless and re-entrant. No instance state is
    modified between calls to :meth:`parse`.
    """

    @property
    @abstractmethod
    def language(self) -> Language:
        """The language this parser handles."""

    @abstractmethod
    def parse(
        self,
        source_bytes: bytes,
        file_path: str,
        service_name: str,
    ) -> SourceFile:
        """Parse ``source_bytes`` and return a normalized :class:`SourceFile`.

        Parameters
        ----------
        source_bytes:
            Raw UTF-8 bytes of the source file. Never executed.
        file_path:
            Project-relative path (forward slashes). Used for symbol IDs
            and diagnostics. Must not be an absolute path.
        service_name:
            Logical service that owns this file (e.g. "user-service").
            Used in symbol ID formation.

        Returns
        -------
        SourceFile
            Fully populated, immutable extraction result.
            On syntax error: parse_status=SYNTAX_ERROR, diagnostics populated.
            On parser failure: parse_status=PARSE_FAILURE, diagnostics populated.

        Notes
        -----
        This method must never:
        - Import the analyzed module.
        - Execute any code from the analyzed source.
        - Access the filesystem (beyond the bytes already provided).
        - Raise exceptions for syntax errors — those become diagnostics.
        """
