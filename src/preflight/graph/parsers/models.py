"""Normalized extraction models for the PreFlight parser layer.

These models are the Tree-sitter-independent output of parsing.
They form the boundary between the parser implementation details and
the rest of PreFlight.

Architectural invariant:
    No Tree-sitter node objects ever appear outside this package.
    All parser output is expressed in terms of the models in this file.

Model hierarchy
---------------
ParseStatus    — enum: SUCCESS, SYNTAX_ERROR, PARSE_FAILURE
Language       — enum: PYTHON, KOTLIN
SymbolKind     — enum: MODULE, CLASS, FUNCTION, ASYNC_FUNCTION, METHOD, ...
ResolutionStatus — enum: EXACT, IMPORTED, QUALIFIED, PROJECT_UNIQUE, UNRESOLVED, ...
Symbol         — a detected declaration in a source file
Reference      — a detected usage / call / import reference
SourceFile     — the complete normalized result for one parsed file

Symbol ID scheme (documented in docs/DAY_2.md)
----------------------------------------------
Format: ``<service>/<relative_file_path>::<kind>::<qualified_name>``
Example: ``user-service/src/user_service.py::class::UserService``

This ID is:
- deterministic (same input → same ID)
- project-relative (no absolute paths)
- collision-resistant (kind is part of the key)
- stable across repeated analysis of the same file
"""

from __future__ import annotations

import hashlib
from enum import Enum
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, Field

from preflight.graph.parsers.diagnostics import Diagnostic


class ParseStatus(str, Enum):
    """Result of attempting to parse a source file."""

    SUCCESS = "SUCCESS"
    """File parsed with no syntax errors."""

    SYNTAX_ERROR = "SYNTAX_ERROR"
    """File parsed but the AST contains syntax error nodes."""

    PARSE_FAILURE = "PARSE_FAILURE"
    """Parser raised an unexpected exception; file could not be analyzed."""


class Language(str, Enum):
    """Source languages supported by Day 2 parsers."""

    PYTHON = "python"
    KOTLIN = "kotlin"


class SymbolKind(str, Enum):
    """Classifies a source-level symbol declaration."""

    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    ASYNC_FUNCTION = "async_function"
    METHOD = "method"
    ASYNC_METHOD = "async_method"
    DATA_CLASS = "data_class"
    INTERFACE = "interface"
    OBJECT = "object"  # Kotlin object declaration
    PACKAGE = "package"  # Kotlin package declaration


class ResolutionStatus(str, Enum):
    """How confidently a reference was resolved.

    These are deterministic resolution categories, NOT probabilities.
    Do not add numeric confidence scores without a justified statistical model.
    """

    # Resolved categories
    EXACT = "EXACT"
    """Resolved to a single symbol in the same file by exact name match."""

    IMPORTED = "IMPORTED"
    """Resolved via an explicit import statement in the same file."""

    QUALIFIED = "QUALIFIED"
    """Resolved via a qualified name (module.ClassName)."""

    PROJECT_UNIQUE = "PROJECT_UNIQUE"
    """Resolved because the name is unique across all symbols in the project."""

    # Unresolved categories
    UNRESOLVED = "UNRESOLVED"
    """No matching symbol found with available information."""

    AMBIGUOUS = "AMBIGUOUS"
    """Multiple candidate symbols match; cannot choose deterministically."""

    DYNAMIC = "DYNAMIC"
    """Reference uses dynamic dispatch (getattr, reflection); not statically resolvable."""


class SourceLocation(BaseModel):
    """A precise location in a source file.

    Line numbers are 1-based (human-facing convention).
    Column numbers are 0-based (matching tree-sitter's convention).
    """

    model_config = {"frozen": True}

    file_path: str = Field(..., description="Project-relative file path.", min_length=1)
    line: int = Field(..., description="1-based line number.", ge=1)
    column: int = Field(..., description="0-based column number.", ge=0)


def make_symbol_id(
    service: str,
    relative_file_path: str,
    kind: SymbolKind,
    qualified_name: str,
) -> str:
    """Construct a stable, deterministic symbol ID.

    Format: ``<service>/<normalized_path>::<kind>::<qualified_name>``

    Parameters
    ----------
    service:
        The service directory name (e.g. "user-service").
    relative_file_path:
        Path relative to the fixture root (e.g. "user-service/src/user_service.py").
        Backslashes are normalized to forward slashes for cross-platform determinism.
    kind:
        Symbol kind (class, function, etc.).
    qualified_name:
        Fully-qualified symbol name within the file (e.g. "UserService.get_user").

    Returns
    -------
    str
        A stable symbol ID that never contains random or time-based components.
    """
    # Replace Windows backslashes before passing to PurePosixPath.
    normalized_path = PurePosixPath(relative_file_path.replace("\\", "/")).as_posix()
    return f"{service}/{normalized_path}::{kind.value}::{qualified_name}"


def make_content_hash(source_bytes: bytes) -> str:
    """Compute a SHA-256 content hash of normalized source bytes.

    Excludes all filesystem metadata (mtime, inode, etc.).
    This hash enables future incremental analysis / caching.

    The hash is over the raw source bytes — NOT over normalized whitespace —
    because whitespace changes are semantically significant in Python.
    """
    return hashlib.sha256(source_bytes).hexdigest()


class Symbol(BaseModel):
    """A detected declaration in a source file.

    Symbols are produced by language-specific extractors and are
    Tree-sitter-independent — they carry only the normalized information
    that PreFlight's resolver and graph builder need.
    """

    model_config = {"frozen": True}

    symbol_id: str = Field(
        ...,
        description=(
            "Stable, deterministic ID. "
            "Format: <service>/<path>::<kind>::<qualified_name>"
        ),
        min_length=1,
    )
    qualified_name: str = Field(
        ...,
        description="Fully-qualified name within the file (e.g. 'UserService.get_user').",
        min_length=1,
    )
    symbol_kind: SymbolKind = Field(..., description="Kind of symbol.")
    location: SourceLocation = Field(..., description="Declaration location.")
    is_public: bool = Field(
        default=True,
        description=(
            "Whether the symbol is considered public. "
            "In Python: True unless name starts with _. "
            "In Kotlin: True unless marked private/internal."
        ),
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Extension data. Not used for identity or ordering.",
    )


class Reference(BaseModel):
    """A detected reference (import, call, attribute access) in a source file.

    References are what the resolver works with. An unresolved reference
    remains in the output as an explicit UNRESOLVED diagnostic rather than
    being silently dropped.
    """

    model_config = {"frozen": True}

    reference_text: str = Field(
        ...,
        description="The raw reference text as it appears in the source.",
        min_length=1,
    )
    location: SourceLocation = Field(..., description="Location of the reference.")
    resolution_status: ResolutionStatus = Field(
        default=ResolutionStatus.UNRESOLVED,
        description="How this reference was resolved.",
    )
    resolved_symbol_id: str | None = Field(
        default=None,
        description="symbol_id of the resolved target, if resolution succeeded.",
    )
    candidate_symbol_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        description="All matching candidates when resolution is AMBIGUOUS.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Extension data (e.g. import alias, call type).",
    )


class SourceFile(BaseModel):
    """Complete normalized extraction result for one parsed source file.

    This is the primary output of the parser layer. It contains:
    - parse status (was the file understood?)
    - content hash (for future caching)
    - all extracted symbols
    - all extracted references (resolved and unresolved)
    - all diagnostics generated during extraction

    The SourceFile is intentionally immutable — it represents a snapshot.
    """

    model_config = {"frozen": True}

    file_path: str = Field(
        ...,
        description="Project-relative path (forward slashes).",
        min_length=1,
    )
    language: Language = Field(..., description="Detected language.")
    parse_status: ParseStatus = Field(..., description="Result of parsing.")
    content_hash: str = Field(
        ...,
        description="SHA-256 of raw source bytes. For future caching support.",
        min_length=64,
        max_length=64,
    )
    syntax_error_count: int = Field(
        default=0,
        description="Number of syntax error nodes in the AST.",
        ge=0,
    )
    symbols: tuple[Symbol, ...] = Field(
        default_factory=tuple,
        description="All symbols extracted from this file, sorted by location.",
    )
    references: tuple[Reference, ...] = Field(
        default_factory=tuple,
        description="All references extracted from this file, sorted by location.",
    )
    diagnostics: tuple[Diagnostic, ...] = Field(
        default_factory=tuple,
        description="All diagnostics generated while processing this file.",
    )
