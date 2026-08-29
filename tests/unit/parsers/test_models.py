"""Unit tests for parser extraction models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from preflight.graph.parsers.diagnostics import DiagnosticCode, make_diagnostic
from preflight.graph.parsers.models import (
    Language,
    ParseStatus,
    Reference,
    ResolutionStatus,
    SourceFile,
    SourceLocation,
    Symbol,
    SymbolKind,
    make_content_hash,
    make_symbol_id,
)


class TestSourceLocation:
    def test_valid_location(self) -> None:
        loc = SourceLocation(file_path="svc/f.py", line=5, column=0)
        assert loc.line == 5
        assert loc.column == 0

    def test_line_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            SourceLocation(file_path="f.py", line=0, column=0)

    def test_column_can_be_zero(self) -> None:
        loc = SourceLocation(file_path="f.py", line=1, column=0)
        assert loc.column == 0

    def test_location_is_immutable(self) -> None:
        loc = SourceLocation(file_path="f.py", line=1, column=0)
        with pytest.raises((TypeError, ValidationError)):
            loc.line = 2  # type: ignore[misc]


class TestMakeSymbolId:
    def test_basic_symbol_id(self) -> None:
        sid = make_symbol_id("user-service", "user-service/src/user_service.py", SymbolKind.CLASS, "UserService")
        assert sid == "user-service/user-service/src/user_service.py::class::UserService"

    def test_symbol_id_is_deterministic(self) -> None:
        a = make_symbol_id("svc", "svc/f.py", SymbolKind.FUNCTION, "foo")
        b = make_symbol_id("svc", "svc/f.py", SymbolKind.FUNCTION, "foo")
        assert a == b

    def test_different_kinds_produce_different_ids(self) -> None:
        a = make_symbol_id("svc", "f.py", SymbolKind.CLASS, "Foo")
        b = make_symbol_id("svc", "f.py", SymbolKind.FUNCTION, "Foo")
        assert a != b

    def test_forward_slashes_normalized(self) -> None:
        # Windows backslash paths should be normalized.
        sid = make_symbol_id("svc", "svc\\src\\f.py", SymbolKind.CLASS, "Foo")
        assert "\\" not in sid


class TestMakeContentHash:
    def test_hash_is_64_chars(self) -> None:
        h = make_content_hash(b"class Foo: pass")
        assert len(h) == 64

    def test_same_content_same_hash(self) -> None:
        assert make_content_hash(b"abc") == make_content_hash(b"abc")

    def test_different_content_different_hash(self) -> None:
        assert make_content_hash(b"abc") != make_content_hash(b"def")

    def test_empty_bytes_hash(self) -> None:
        h = make_content_hash(b"")
        assert len(h) == 64


class TestSymbol:
    def _loc(self) -> SourceLocation:
        return SourceLocation(file_path="svc/f.py", line=1, column=0)

    def test_valid_symbol(self) -> None:
        sid = make_symbol_id("svc", "svc/f.py", SymbolKind.CLASS, "Foo")
        sym = Symbol(
            symbol_id=sid,
            qualified_name="Foo",
            symbol_kind=SymbolKind.CLASS,
            location=self._loc(),
        )
        assert sym.is_public is True
        assert sym.metadata == {}

    def test_private_symbol(self) -> None:
        sid = make_symbol_id("svc", "f.py", SymbolKind.FUNCTION, "_private")
        sym = Symbol(
            symbol_id=sid,
            qualified_name="_private",
            symbol_kind=SymbolKind.FUNCTION,
            location=self._loc(),
            is_public=False,
        )
        assert sym.is_public is False

    def test_symbol_is_immutable(self) -> None:
        sid = make_symbol_id("svc", "f.py", SymbolKind.CLASS, "Foo")
        sym = Symbol(
            symbol_id=sid,
            qualified_name="Foo",
            symbol_kind=SymbolKind.CLASS,
            location=self._loc(),
        )
        with pytest.raises((TypeError, ValidationError)):
            sym.qualified_name = "Bar"  # type: ignore[misc]


class TestReference:
    def _loc(self) -> SourceLocation:
        return SourceLocation(file_path="svc/f.py", line=5, column=0)

    def test_unresolved_reference(self) -> None:
        ref = Reference(
            reference_text="UserService",
            location=self._loc(),
        )
        assert ref.resolution_status == ResolutionStatus.UNRESOLVED
        assert ref.resolved_symbol_id is None
        assert ref.candidate_symbol_ids == ()

    def test_resolved_reference(self) -> None:
        ref = Reference(
            reference_text="UserService",
            location=self._loc(),
            resolution_status=ResolutionStatus.EXACT,
            resolved_symbol_id="svc/f.py::class::UserService",
        )
        assert ref.resolved_symbol_id == "svc/f.py::class::UserService"

    def test_ambiguous_reference(self) -> None:
        ref = Reference(
            reference_text="Foo",
            location=self._loc(),
            resolution_status=ResolutionStatus.AMBIGUOUS,
            candidate_symbol_ids=("a/f.py::class::Foo", "b/f.py::class::Foo"),
        )
        assert len(ref.candidate_symbol_ids) == 2


class TestSourceFile:
    def test_minimal_source_file(self) -> None:
        sf = SourceFile(
            file_path="svc/f.py",
            language=Language.PYTHON,
            parse_status=ParseStatus.SUCCESS,
            content_hash="a" * 64,
        )
        assert sf.symbols == ()
        assert sf.references == ()
        assert sf.diagnostics == ()

    def test_source_file_with_syntax_error(self) -> None:
        diag = make_diagnostic(DiagnosticCode.SYNTAX_ERROR, "err", "f.py")
        sf = SourceFile(
            file_path="f.py",
            language=Language.PYTHON,
            parse_status=ParseStatus.SYNTAX_ERROR,
            content_hash="b" * 64,
            syntax_error_count=1,
            diagnostics=(diag,),
        )
        assert sf.parse_status == ParseStatus.SYNTAX_ERROR
        assert sf.syntax_error_count == 1
        assert len(sf.diagnostics) == 1

    def test_content_hash_must_be_64_chars(self) -> None:
        with pytest.raises(ValidationError):
            SourceFile(
                file_path="f.py",
                language=Language.PYTHON,
                parse_status=ParseStatus.SUCCESS,
                content_hash="short",
            )
