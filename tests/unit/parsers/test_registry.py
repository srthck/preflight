"""Unit tests for the language registry."""

from __future__ import annotations

from preflight.graph.parsers.diagnostics import DiagnosticCode
from preflight.graph.parsers.models import Language, ParseStatus
from preflight.graph.parsers.registry import LanguageRegistry, _file_extension


class TestFileExtension:
    def test_py_extension(self) -> None:
        assert _file_extension("svc/f.py") == ".py"

    def test_kt_extension(self) -> None:
        assert _file_extension("svc/f.kt") == ".kt"

    def test_no_extension(self) -> None:
        assert _file_extension("Makefile") == ""

    def test_uppercase_normalized(self) -> None:
        assert _file_extension("F.PY") == ".py"


class TestLanguageRegistry:
    def test_py_returns_python_parser(self) -> None:
        reg = LanguageRegistry()
        p = reg.get_parser(".py")
        assert p is not None
        assert p.language == Language.PYTHON

    def test_pyw_returns_python_parser(self) -> None:
        reg = LanguageRegistry()
        p = reg.get_parser(".pyw")
        assert p is not None
        assert p.language == Language.PYTHON

    def test_kt_returns_kotlin_parser(self) -> None:
        reg = LanguageRegistry()
        p = reg.get_parser(".kt")
        assert p is not None
        assert p.language == Language.KOTLIN

    def test_unknown_extension_returns_none(self) -> None:
        reg = LanguageRegistry()
        assert reg.get_parser(".rb") is None
        assert reg.get_parser(".java") is None
        assert reg.get_parser(".rs") is None

    def test_supported_extensions_contains_py_and_kt(self) -> None:
        reg = LanguageRegistry()
        exts = reg.supported_extensions()
        assert ".py" in exts
        assert ".kt" in exts

    def test_parse_file_py(self) -> None:
        reg = LanguageRegistry()
        sf = reg.parse_file(b"class Foo:\n    pass\n", "svc/f.py", "svc")
        assert sf.language == Language.PYTHON
        assert sf.parse_status == ParseStatus.SUCCESS

    def test_parse_file_kt(self) -> None:
        reg = LanguageRegistry()
        sf = reg.parse_file(b"class Foo {}\n", "svc/f.kt", "svc")
        assert sf.language == Language.KOTLIN

    def test_unsupported_extension_produces_diagnostic(self) -> None:
        reg = LanguageRegistry()
        sf = reg.parse_file(b"# ruby code", "svc/f.rb", "svc")
        assert sf.parse_status == ParseStatus.PARSE_FAILURE
        codes = {d.code for d in sf.diagnostics}
        assert DiagnosticCode.UNSUPPORTED_LANGUAGE in codes

    def test_unsupported_file_has_content_hash(self) -> None:
        reg = LanguageRegistry()
        sf = reg.parse_file(b"content", "svc/f.xml", "svc")
        assert len(sf.content_hash) == 64

    def test_language_for_extension(self) -> None:
        reg = LanguageRegistry()
        assert reg.language_for_extension(".py") == Language.PYTHON
        assert reg.language_for_extension(".kt") == Language.KOTLIN
        assert reg.language_for_extension(".rb") is None
