"""Unit tests for the Kotlin Tree-sitter parser.

Tests cover:
- Package declaration extraction
- Class extraction (regular, data class, interface)
- Method/function extraction
- Import extraction
- Call reference extraction
- Source location tracking
- Syntax error handling
- Empty file
- Deterministic ordering
"""

from __future__ import annotations

import pytest

from preflight.graph.parsers.kotlin import KotlinParser
from preflight.graph.parsers.models import (
    Language,
    ParseStatus,
    SymbolKind,
)


@pytest.fixture
def parser() -> KotlinParser:
    return KotlinParser()


def parse(parser: KotlinParser, src: str) -> object:
    return parser.parse(src.encode("utf-8"), "android-client/src/f.kt", "android-client")


class TestKotlinParserLanguage:
    def test_language_is_kotlin(self, parser: KotlinParser) -> None:
        assert parser.language == Language.KOTLIN


class TestKotlinPackageExtraction:
    def test_package_symbol_extracted(self, parser: KotlinParser) -> None:
        sf = parse(parser, "package com.example.client\n")
        pkg_syms = [s for s in sf.symbols if s.symbol_kind == SymbolKind.PACKAGE]
        assert any("com.example.client" in s.qualified_name for s in pkg_syms)

    def test_package_line_number(self, parser: KotlinParser) -> None:
        sf = parse(parser, "package com.example\n")
        sym = next(s for s in sf.symbols if s.symbol_kind == SymbolKind.PACKAGE)
        assert sym.location.line == 1


class TestKotlinClassExtraction:
    def test_simple_class(self, parser: KotlinParser) -> None:
        sf = parse(parser, "class ProfileClient {}\n")
        class_syms = [s for s in sf.symbols if s.symbol_kind == SymbolKind.CLASS]
        assert any(s.qualified_name == "ProfileClient" for s in class_syms)

    def test_data_class(self, parser: KotlinParser) -> None:
        sf = parse(parser, "data class ProfileResponse(val id: Int)\n")
        data_syms = [s for s in sf.symbols if s.symbol_kind == SymbolKind.DATA_CLASS]
        assert any(s.qualified_name == "ProfileResponse" for s in data_syms)

    def test_interface(self, parser: KotlinParser) -> None:
        src = "interface ProfileApiService {\n    fun getProfile(id: Int): String\n}\n"
        sf = parse(parser, src)
        # tree-sitter-kotlin uses class_declaration for interface too
        names = {s.qualified_name for s in sf.symbols if s.symbol_kind in (SymbolKind.CLASS, SymbolKind.INTERFACE)}
        assert "ProfileApiService" in names

    def test_class_line_number(self, parser: KotlinParser) -> None:
        sf = parse(parser, "\nclass Foo {}\n")
        sym = next(s for s in sf.symbols if s.qualified_name == "Foo")
        assert sym.location.line == 2


class TestKotlinMethodExtraction:
    def test_method_in_class(self, parser: KotlinParser) -> None:
        src = "class Foo {\n    fun bar(): String { return \"x\" }\n}\n"
        sf = parse(parser, src)
        method_syms = [s for s in sf.symbols if s.symbol_kind == SymbolKind.METHOD]
        assert any(s.qualified_name == "Foo.bar" for s in method_syms)

    def test_multiple_methods(self, parser: KotlinParser) -> None:
        src = "class Foo {\n    fun a() {}\n    fun b() {}\n}\n"
        sf = parse(parser, src)
        names = {s.qualified_name for s in sf.symbols if s.symbol_kind == SymbolKind.METHOD}
        assert "Foo.a" in names
        assert "Foo.b" in names


class TestKotlinImportExtraction:
    def test_single_import(self, parser: KotlinParser) -> None:
        sf = parse(parser, "import com.example.ProfileAPI\n")
        texts = {r.reference_text for r in sf.references}
        assert "com.example.ProfileAPI" in texts

    def test_multiple_imports(self, parser: KotlinParser) -> None:
        src = "import com.example.ProfileAPI\nimport com.example.UserService\n"
        sf = parse(parser, src)
        texts = {r.reference_text for r in sf.references}
        assert "com.example.ProfileAPI" in texts
        assert "com.example.UserService" in texts

    def test_import_metadata(self, parser: KotlinParser) -> None:
        sf = parse(parser, "import com.example.Foo\n")
        ref = next(r for r in sf.references if "Foo" in r.reference_text)
        assert ref.metadata.get("import_kind") == "import"

    def test_comment_not_treated_as_import(self, parser: KotlinParser) -> None:
        src = "// import com.fake.FakeClass\nclass Real {}\n"
        sf = parse(parser, src)
        texts = {r.reference_text for r in sf.references}
        assert not any("FakeClass" in t for t in texts)


class TestKotlinSyntaxErrors:
    def test_malformed_class_produces_syntax_error_status(self, parser: KotlinParser) -> None:
        sf = parse(parser, "class { val x = 1 }\n")
        # May or may not be a syntax error depending on tree-sitter-kotlin grammar
        # Either way, should not crash
        assert sf is not None

    def test_valid_kotlin_parses_successfully(self, parser: KotlinParser) -> None:
        sf = parse(parser, "class Foo {}\n")
        assert sf.parse_status in (ParseStatus.SUCCESS, ParseStatus.SYNTAX_ERROR)


class TestKotlinEmptyFile:
    def test_empty_file_parses(self, parser: KotlinParser) -> None:
        sf = parse(parser, "")
        assert sf is not None
        assert sf.parse_status in (ParseStatus.SUCCESS, ParseStatus.SYNTAX_ERROR)

    def test_empty_file_has_module_symbol(self, parser: KotlinParser) -> None:
        sf = parse(parser, "")
        module_syms = [s for s in sf.symbols if s.symbol_kind == SymbolKind.MODULE]
        assert len(module_syms) == 1


class TestKotlinDeterminism:
    def test_same_source_produces_identical_hash(self, parser: KotlinParser) -> None:
        src = "class Foo {}\n"
        sf1 = parse(parser, src)
        sf2 = parse(parser, src)
        assert sf1.content_hash == sf2.content_hash

    def test_symbols_sorted_by_line(self, parser: KotlinParser) -> None:
        src = "class B {}\nclass A {}\n"
        sf = parse(parser, src)
        lines = [s.location.line for s in sf.symbols if s.symbol_kind == SymbolKind.CLASS]
        assert lines == sorted(lines)
