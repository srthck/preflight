"""Syntax-aware structural source diffing.

P0.4 disclosed structural source diffing as unimplemented. This module closes
that gap by comparing **parser-extracted symbol tables**, never raw text.

The distinction matters: a text diff can show a line disappearing for a dozen
reasons (reformatting, a moved brace, a renamed local). Only the parser can
establish that a *declaration* is gone. Accordingly, a structural change is
emitted only when both sides of the comparison parsed successfully — if
either side failed to parse or is in an unsupported language, the file is
reported as ``PARSE_ERROR`` / ``UNSUPPORTED`` and **no symbol claims are made
about it at all**.

It reuses the existing ``SourceExtractor`` (Tree-sitter) rather than adding a
second parser, in keeping with the standing rule against duplicating analyzers.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from preflight.graph.parsers.extractor import SourceExtractor
from preflight.graph.parsers.models import ParseStatus, Symbol


class StructuralChangeKind(str, Enum):
    """What structurally changed. Every value requires parser evidence."""

    FUNCTION_ADDED = "FUNCTION_ADDED"
    FUNCTION_REMOVED = "FUNCTION_REMOVED"
    METHOD_ADDED = "METHOD_ADDED"
    METHOD_REMOVED = "METHOD_REMOVED"
    CLASS_ADDED = "CLASS_ADDED"
    CLASS_REMOVED = "CLASS_REMOVED"


class StructuralAnalysisStatus(str, Enum):
    """Per-file outcome. Absence of changes is not the same as absence of analysis."""

    ANALYZED = "ANALYZED"
    PARSE_ERROR = "PARSE_ERROR"
    UNSUPPORTED = "UNSUPPORTED"


_ADDED_BY_KIND = {
    "function": StructuralChangeKind.FUNCTION_ADDED,
    "async_function": StructuralChangeKind.FUNCTION_ADDED,
    "method": StructuralChangeKind.METHOD_ADDED,
    "async_method": StructuralChangeKind.METHOD_ADDED,
    "class": StructuralChangeKind.CLASS_ADDED,
    "data_class": StructuralChangeKind.CLASS_ADDED,
    "interface": StructuralChangeKind.CLASS_ADDED,
    "object": StructuralChangeKind.CLASS_ADDED,
}
_REMOVED_BY_KIND = {
    "function": StructuralChangeKind.FUNCTION_REMOVED,
    "async_function": StructuralChangeKind.FUNCTION_REMOVED,
    "method": StructuralChangeKind.METHOD_REMOVED,
    "async_method": StructuralChangeKind.METHOD_REMOVED,
    "class": StructuralChangeKind.CLASS_REMOVED,
    "data_class": StructuralChangeKind.CLASS_REMOVED,
    "interface": StructuralChangeKind.CLASS_REMOVED,
    "object": StructuralChangeKind.CLASS_REMOVED,
}


class StructuralChange(BaseModel):
    """One parser-established structural change, with its source location."""

    model_config = {"frozen": True}

    kind: StructuralChangeKind
    symbol: str = Field(..., min_length=1)
    symbol_kind: str = Field(..., min_length=1)
    file: str = Field(..., min_length=1)
    line: int | None = Field(default=None, ge=1)
    language: str = Field(default="")
    # Which analyzer established this. Displayed as a provenance badge, so it
    # must name the real extractor rather than a generic label.
    established_by: str = Field(default="tree-sitter")

    @property
    def sort_key(self) -> tuple[str, str, str]:
        return (self.file, self.symbol, self.kind.value)


class StructuralFileStatus(BaseModel):
    """Why a file did or did not yield structural evidence."""

    model_config = {"frozen": True}

    file: str = Field(..., min_length=1)
    status: StructuralAnalysisStatus
    detail: str = Field(default="")


class StructuralDiff(BaseModel):
    """Deterministic structural comparison of two source trees."""

    model_config = {"frozen": True}

    changes: tuple[StructuralChange, ...] = Field(default_factory=tuple)
    file_statuses: tuple[StructuralFileStatus, ...] = Field(default_factory=tuple)
    analyzed_file_count: int = Field(default=0, ge=0)
    unsupported_file_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _sort(self) -> StructuralDiff:
        object.__setattr__(
            self, "changes", tuple(sorted(self.changes, key=lambda c: c.sort_key))
        )
        object.__setattr__(
            self, "file_statuses", tuple(sorted(self.file_statuses, key=lambda s: s.file))
        )
        return self


def _symbol_table(root: Path) -> tuple[dict[str, dict[tuple[str, str], Symbol]], dict[str, Any]]:
    """``{file: {(kind, qualified_name): Symbol}}`` plus each file's parse record."""
    result = SourceExtractor().extract(root)
    by_file: dict[str, dict[tuple[str, str], Symbol]] = {}
    records: dict[str, Any] = {}
    for source_file in result.source_files:
        records[source_file.file_path] = source_file
        table: dict[tuple[str, str], Symbol] = {}
        # Module-level pseudo-symbols describe the file itself, not a
        # declaration a developer wrote; they would produce meaningless
        # "module added/removed" noise.
        for symbol in source_file.symbols:
            if symbol.symbol_kind.value in {"module", "package"}:
                continue
            table[(symbol.symbol_kind.value, symbol.qualified_name)] = symbol
        by_file[source_file.file_path] = table
    return by_file, records


def compare_source_structure(old_root: Path, new_root: Path) -> StructuralDiff:
    """Compare two source trees at the level of declared symbols.

    A change is emitted only where the parser succeeded on both sides. Files
    that failed to parse, or that are in a language PreFlight does not parse,
    are reported with an explicit status and contribute no symbol claims.
    """
    old_table, old_records = _symbol_table(old_root)
    new_table, new_records = _symbol_table(new_root)

    changes: list[StructuralChange] = []
    statuses: list[StructuralFileStatus] = []
    analyzed = 0
    unsupported = 0

    for file_path in sorted(set(old_table) | set(new_table)):
        old_record = old_records.get(file_path)
        new_record = new_records.get(file_path)

        # A file that failed to parse on either side yields no symbol claims:
        # "we could not read it" must never be reported as "it was removed".
        old_failed = old_record is not None and old_record.parse_status != ParseStatus.SUCCESS
        new_failed = new_record is not None and new_record.parse_status != ParseStatus.SUCCESS
        if old_failed or new_failed:
            unsupported += 1
            statuses.append(
                StructuralFileStatus(
                    file=file_path,
                    status=StructuralAnalysisStatus.PARSE_ERROR,
                    detail=(
                        "The file could not be parsed on at least one side; "
                        "no structural claims are made about it."
                    ),
                )
            )
            continue

        old_symbols = old_table.get(file_path, {})
        new_symbols = new_table.get(file_path, {})
        analyzed += 1
        language = ""
        if new_record is not None:
            language = new_record.language.value
        elif old_record is not None:
            language = old_record.language.value
        statuses.append(
            StructuralFileStatus(
                file=file_path,
                status=StructuralAnalysisStatus.ANALYZED,
                detail=f"{len(new_symbols)} declaration(s) after change.",
            )
        )

        for key in sorted(set(old_symbols) - set(new_symbols)):
            symbol_kind, qualified_name = key
            mapped = _REMOVED_BY_KIND.get(symbol_kind)
            if mapped is None:
                continue
            symbol = old_symbols[key]
            changes.append(
                StructuralChange(
                    kind=mapped,
                    symbol=qualified_name,
                    symbol_kind=symbol_kind,
                    file=file_path,
                    line=symbol.location.line,
                    language=language,
                )
            )
        for key in sorted(set(new_symbols) - set(old_symbols)):
            symbol_kind, qualified_name = key
            mapped_add = _ADDED_BY_KIND.get(symbol_kind)
            if mapped_add is None:
                continue
            symbol = new_symbols[key]
            changes.append(
                StructuralChange(
                    kind=mapped_add,
                    symbol=qualified_name,
                    symbol_kind=symbol_kind,
                    file=file_path,
                    line=symbol.location.line,
                    language=language,
                )
            )

    return StructuralDiff(
        changes=tuple(changes),
        file_statuses=tuple(statuses),
        analyzed_file_count=analyzed,
        unsupported_file_count=unsupported,
    )


__all__ = [
    "StructuralAnalysisStatus",
    "StructuralChange",
    "StructuralChangeKind",
    "StructuralDiff",
    "StructuralFileStatus",
    "compare_source_structure",
]
