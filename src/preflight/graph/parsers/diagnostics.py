"""Structured diagnostics for the PreFlight parser layer.

Diagnostics represent conditions that the parser found but could not fully
resolve. They are not exceptions — they are first-class structured output
that callers can inspect, log, or surface in a future UI.

Every diagnostic carries:
- code      : machine-readable DiagnosticCode
- severity  : ERROR, WARNING, or INFO
- message   : human-readable explanation
- file_path : project-relative path where the issue was found
- line      : 1-based line number (None if not applicable)
- column    : 0-based column number (None if not applicable)

Design principles
-----------------
* Diagnostics are immutable once created.
* They must NEVER be silently swallowed.
* They flow up to the SourceFile and then to the caller.
* The caller decides whether to fail hard or report softly.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DiagnosticSeverity(str, Enum):
    """Severity level of a diagnostic."""

    ERROR = "ERROR"
    """A condition that prevents correct analysis of a file or symbol."""

    WARNING = "WARNING"
    """A condition that may affect completeness but not correctness."""

    INFO = "INFO"
    """Informational note; no impact on analysis correctness."""


class DiagnosticCode(str, Enum):
    """Machine-readable diagnostic codes.

    These codes are stable identifiers suitable for programmatic filtering.
    Do not rename existing codes without a migration plan.
    """

    UNSUPPORTED_LANGUAGE = "UNSUPPORTED_LANGUAGE"
    """A source file uses a language not supported by the current parser set."""

    SYNTAX_ERROR = "SYNTAX_ERROR"
    """The parser encountered a syntax error in the source file."""

    UNRESOLVED_REFERENCE = "UNRESOLVED_REFERENCE"
    """A reference could not be resolved to any known symbol."""

    AMBIGUOUS_REFERENCE = "AMBIGUOUS_REFERENCE"
    """A reference matches more than one candidate symbol."""

    DYNAMIC_REFERENCE = "DYNAMIC_REFERENCE"
    """A reference uses dynamic dispatch (getattr, reflection, etc.) that
    cannot be statically resolved."""

    PARSER_FAILURE = "PARSER_FAILURE"
    """An unexpected internal error occurred during parsing."""

    DUPLICATE_SYMBOL = "DUPLICATE_SYMBOL"
    """Two symbols in the same scope share the same qualified name."""


# Severity defaults per code — used when creating diagnostics without
# an explicit severity override.
_DEFAULT_SEVERITY: dict[DiagnosticCode, DiagnosticSeverity] = {
    DiagnosticCode.UNSUPPORTED_LANGUAGE: DiagnosticSeverity.WARNING,
    DiagnosticCode.SYNTAX_ERROR: DiagnosticSeverity.ERROR,
    DiagnosticCode.UNRESOLVED_REFERENCE: DiagnosticSeverity.WARNING,
    DiagnosticCode.AMBIGUOUS_REFERENCE: DiagnosticSeverity.WARNING,
    DiagnosticCode.DYNAMIC_REFERENCE: DiagnosticSeverity.INFO,
    DiagnosticCode.PARSER_FAILURE: DiagnosticSeverity.ERROR,
    DiagnosticCode.DUPLICATE_SYMBOL: DiagnosticSeverity.WARNING,
}


class Diagnostic(BaseModel):
    """A single structured diagnostic message from the parser layer.

    All fields are immutable after construction.
    """

    model_config = {"frozen": True}

    code: DiagnosticCode = Field(..., description="Machine-readable diagnostic code.")
    severity: DiagnosticSeverity = Field(
        ..., description="Severity level: ERROR, WARNING, or INFO."
    )
    message: str = Field(..., description="Human-readable explanation.", min_length=1)
    file_path: str = Field(
        ...,
        description="Project-relative path to the file where this diagnostic originates.",
        min_length=1,
    )
    line: int | None = Field(
        default=None,
        description="1-based line number. None if not applicable.",
        ge=1,
    )
    column: int | None = Field(
        default=None,
        description="0-based column number. None if not applicable.",
        ge=0,
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional structured context (e.g. candidate symbols for ambiguous refs).",
    )


def make_diagnostic(
    code: DiagnosticCode,
    message: str,
    file_path: str,
    line: int | None = None,
    column: int | None = None,
    severity: DiagnosticSeverity | None = None,
    context: dict[str, Any] | None = None,
) -> Diagnostic:
    """Convenience constructor — fills default severity from code if not given."""
    resolved_severity = severity if severity is not None else _DEFAULT_SEVERITY[code]
    return Diagnostic(
        code=code,
        severity=resolved_severity,
        message=message,
        file_path=file_path,
        line=line,
        column=column,
        context=context or {},
    )
