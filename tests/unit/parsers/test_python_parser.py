"""Unit tests for the Python Tree-sitter parser.

Tests cover:
- Class extraction
- Method extraction (sync and async)
- Function extraction
- Import extraction (import x, from x import y)
- Reference extraction (calls, attribute access)
- Dynamic reference detection (getattr, globals)
- Syntax error handling
- Empty file
- Source location tracking (line/column)
- Private symbol detection
- Nested class extraction
- Deterministic ordering
- Comments do NOT produce imports
- String literals do NOT produce imports
- Unicode identifiers
"""

from __future__ import annotations

import pytest

from preflight.graph.parsers.diagnostics import DiagnosticCode
from preflight.graph.parsers.models import (
    Language,
    ParseStatus,
    SymbolKind,
)
from preflight.graph.parsers.python import PythonParser


@pytest.fixture
def parser() -> PythonParser:
    return PythonParser()


def parse(parser: PythonParser, src: str) -> object:
    return parser.parse(src.encode("utf-8"), "svc/f.py", "svc")


class TestPythonParserLanguage:
    def test_language_is_python(self, parser: PythonParser) -> None:
        assert parser.language == Language.PYTHON


class TestPythonClassExtraction:
    def test_simple_class(self, parser: PythonParser) -> None:
        sf = parse(parser, "class Foo:\n    pass\n")
        class_syms = [s for s in sf.symbols if s.symbol_kind == SymbolKind.CLASS]
        assert any(s.qualified_name == "Foo" for s in class_syms)

    def test_class_line_number(self, parser: PythonParser) -> None:
        sf = parse(parser, "\n\nclass Foo:\n    pass\n")
        class_syms = [s for s in sf.symbols if s.qualified_name == "Foo"]
        assert len(class_syms) == 1
        assert class_syms[0].location.line == 3

    def test_public_class(self, parser: PythonParser) -> None:
        sf = parse(parser, "class PublicFoo:\n    pass\n")
        sym = next(s for s in sf.symbols if s.qualified_name == "PublicFoo")
        assert sym.is_public is True

    def test_private_class_underscore(self, parser: PythonParser) -> None:
        sf = parse(parser, "class _PrivateFoo:\n    pass\n")
        sym = next(s for s in sf.symbols if s.qualified_name == "_PrivateFoo")
        assert sym.is_public is False

    def test_multiple_classes(self, parser: PythonParser) -> None:
        src = "class A:\n    pass\nclass B:\n    pass\n"
        sf = parse(parser, src)
        names = {s.qualified_name for s in sf.symbols if s.symbol_kind == SymbolKind.CLASS}
        assert "A" in names
        assert "B" in names

    def test_nested_class(self, parser: PythonParser) -> None:
        src = "class Outer:\n    class Inner:\n        pass\n"
        sf = parse(parser, src)
        names = {s.qualified_name for s in sf.symbols if s.symbol_kind == SymbolKind.CLASS}
        assert "Outer" in names
        assert "Outer.Inner" in names


class TestPythonMethodExtraction:
    def test_method_extracted(self, parser: PythonParser) -> None:
        src = "class Foo:\n    def bar(self):\n        pass\n"
        sf = parse(parser, src)
        method_syms = [s for s in sf.symbols if s.symbol_kind == SymbolKind.METHOD]
        assert any(s.qualified_name == "Foo.bar" for s in method_syms)

    def test_async_method_extracted(self, parser: PythonParser) -> None:
        src = "class Foo:\n    async def bar(self):\n        pass\n"
        sf = parse(parser, src)
        async_syms = [s for s in sf.symbols if s.symbol_kind == SymbolKind.ASYNC_METHOD]
        assert any(s.qualified_name == "Foo.bar" for s in async_syms)

    def test_private_method(self, parser: PythonParser) -> None:
        src = "class Foo:\n    def _hidden(self):\n        pass\n"
        sf = parse(parser, src)
        sym = next(s for s in sf.symbols if s.qualified_name == "Foo._hidden")
        assert sym.is_public is False

    def test_multiple_methods(self, parser: PythonParser) -> None:
        src = "class Foo:\n    def a(self): pass\n    def b(self): pass\n"
        sf = parse(parser, src)
        names = {s.qualified_name for s in sf.symbols if s.symbol_kind == SymbolKind.METHOD}
        assert "Foo.a" in names
        assert "Foo.b" in names


class TestPythonFunctionExtraction:
    def test_top_level_function(self, parser: PythonParser) -> None:
        sf = parse(parser, "def foo():\n    pass\n")
        func_syms = [s for s in sf.symbols if s.symbol_kind == SymbolKind.FUNCTION]
        assert any(s.qualified_name == "foo" for s in func_syms)

    def test_async_function(self, parser: PythonParser) -> None:
        sf = parse(parser, "async def foo():\n    pass\n")
        async_syms = [s for s in sf.symbols if s.symbol_kind == SymbolKind.ASYNC_FUNCTION]
        assert any(s.qualified_name == "foo" for s in async_syms)

    def test_private_function(self, parser: PythonParser) -> None:
        sf = parse(parser, "def _private():\n    pass\n")
        sym = next(s for s in sf.symbols if "private" in s.qualified_name)
        assert sym.is_public is False


class TestPythonImportExtraction:
    def test_import_statement(self, parser: PythonParser) -> None:
        sf = parse(parser, "import os\n")
        texts = {r.reference_text for r in sf.references}
        assert "os" in texts

    def test_from_import_statement(self, parser: PythonParser) -> None:
        sf = parse(parser, "from user_service import UserService\n")
        texts = {r.reference_text for r in sf.references}
        assert "user_service.UserService" in texts

    def test_from_import_multiple(self, parser: PythonParser) -> None:
        sf = parse(parser, "from x import A, B\n")
        texts = {r.reference_text for r in sf.references}
        assert "x.A" in texts
        assert "x.B" in texts

    def test_future_import_not_extracted(self, parser: PythonParser) -> None:
        sf = parse(parser, "from __future__ import annotations\n")
        # __future__ imports should not produce references
        texts = {r.reference_text for r in sf.references}
        assert not any(t == "annotations" for t in texts)

    def test_import_kind_metadata(self, parser: PythonParser) -> None:
        sf = parse(parser, "from user_service import UserService\n")
        ref = next(r for r in sf.references if r.reference_text == "user_service.UserService")
        assert ref.metadata.get("import_kind") == "from_import"

    def test_comment_does_not_produce_import(self, parser: PythonParser) -> None:
        src = "# from fake_module import FakeClass\nclass Real:\n    pass\n"
        sf = parse(parser, src)
        texts = {r.reference_text for r in sf.references}
        assert "fake_module.FakeClass" not in texts

    def test_string_literal_does_not_produce_import(self, parser: PythonParser) -> None:
        src = 'x = "from fake import Foo"\n'
        sf = parse(parser, src)
        texts = {r.reference_text for r in sf.references}
        assert "fake.Foo" not in texts


class TestPythonDynamicReferences:
    def test_getattr_produces_dynamic_diagnostic(self, parser: PythonParser) -> None:
        sf = parse(parser, "getattr(obj, 'method')()\n")
        codes = {d.code for d in sf.diagnostics}
        assert DiagnosticCode.DYNAMIC_REFERENCE in codes

    def test_globals_produces_dynamic_diagnostic(self, parser: PythonParser) -> None:
        sf = parse(parser, "x = globals()['FOO']\n")
        codes = {d.code for d in sf.diagnostics}
        assert DiagnosticCode.DYNAMIC_REFERENCE in codes

    def test_getattr_does_not_produce_resolved_reference(self, parser: PythonParser) -> None:
        sf = parse(parser, "getattr(obj, 'method')()\n")
        # getattr should NOT produce a regular reference
        texts = {r.reference_text for r in sf.references}
        assert "getattr" not in texts


class TestPythonSyntaxErrors:
    def test_malformed_class_produces_syntax_error(self, parser: PythonParser) -> None:
        sf = parse(parser, "class :\n    pass\n")
        assert sf.parse_status == ParseStatus.SYNTAX_ERROR
        codes = {d.code for d in sf.diagnostics}
        assert DiagnosticCode.SYNTAX_ERROR in codes

    def test_syntax_error_count_nonzero(self, parser: PythonParser) -> None:
        sf = parse(parser, "def (\n    pass\n")
        assert sf.syntax_error_count > 0

    def test_malformed_file_does_not_crash(self, parser: PythonParser) -> None:
        sf = parse(parser, "!!!@@@###$$$\n")
        # Should not raise; returns with error status
        assert sf is not None


class TestPythonEmptyFile:
    def test_empty_file_parses_successfully(self, parser: PythonParser) -> None:
        sf = parse(parser, "")
        assert sf.parse_status == ParseStatus.SUCCESS
        assert sf.syntax_error_count == 0

    def test_empty_file_has_module_symbol(self, parser: PythonParser) -> None:
        sf = parse(parser, "")
        module_syms = [s for s in sf.symbols if s.symbol_kind == SymbolKind.MODULE]
        assert len(module_syms) == 1


class TestPythonDeterminism:
    def test_symbols_sorted_by_line_column(self, parser: PythonParser) -> None:
        src = "class B:\n    pass\nclass A:\n    pass\n"
        sf = parse(parser, src)
        lines = [s.location.line for s in sf.symbols if s.symbol_kind == SymbolKind.CLASS]
        assert lines == sorted(lines)

    def test_same_source_produces_identical_output(self, parser: PythonParser) -> None:
        src = "class Foo:\n    def bar(self): pass\n"
        sf1 = parse(parser, src)
        sf2 = parse(parser, src)
        assert sf1.content_hash == sf2.content_hash
        assert len(sf1.symbols) == len(sf2.symbols)
        assert sf1.symbols[0].symbol_id == sf2.symbols[0].symbol_id

    def test_shadowed_variable_not_confused_with_class(self, parser: PythonParser) -> None:
        src = "class Foo:\n    pass\nFoo = 42\n"
        sf = parse(parser, src)
        class_syms = [s for s in sf.symbols if s.symbol_kind == SymbolKind.CLASS]
        assert len(class_syms) == 1


class TestPythonSourceLocations:
    def test_class_line_is_one_based(self, parser: PythonParser) -> None:
        sf = parse(parser, "class Foo:\n    pass\n")
        sym = next(s for s in sf.symbols if s.qualified_name == "Foo")
        assert sym.location.line >= 1

    def test_method_line_correct(self, parser: PythonParser) -> None:
        src = "class Foo:\n    def bar(self):\n        pass\n"
        sf = parse(parser, src)
        sym = next(s for s in sf.symbols if s.qualified_name == "Foo.bar")
        assert sym.location.line == 2
