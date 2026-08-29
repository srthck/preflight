"""Unit tests for parser diagnostics models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from preflight.graph.parsers.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    DiagnosticSeverity,
    make_diagnostic,
)


class TestDiagnosticConstruction:
    def test_valid_minimal_diagnostic(self) -> None:
        d = Diagnostic(
            code=DiagnosticCode.SYNTAX_ERROR,
            severity=DiagnosticSeverity.ERROR,
            message="parse error",
            file_path="svc/file.py",
        )
        assert d.code == DiagnosticCode.SYNTAX_ERROR
        assert d.severity == DiagnosticSeverity.ERROR
        assert d.line is None
        assert d.column is None
        assert d.context == {}

    def test_valid_full_diagnostic(self) -> None:
        d = Diagnostic(
            code=DiagnosticCode.UNRESOLVED_REFERENCE,
            severity=DiagnosticSeverity.WARNING,
            message="not found",
            file_path="svc/file.py",
            line=10,
            column=4,
            context={"ref": "Foo"},
        )
        assert d.line == 10
        assert d.column == 4
        assert d.context["ref"] == "Foo"

    def test_diagnostic_is_immutable(self) -> None:
        d = make_diagnostic(DiagnosticCode.SYNTAX_ERROR, "err", "f.py")
        with pytest.raises((TypeError, ValidationError)):
            d.message = "other"  # type: ignore[misc]

    def test_make_diagnostic_uses_default_severity(self) -> None:
        d = make_diagnostic(DiagnosticCode.SYNTAX_ERROR, "err", "f.py")
        assert d.severity == DiagnosticSeverity.ERROR

    def test_make_diagnostic_unsupported_language_default_severity(self) -> None:
        d = make_diagnostic(DiagnosticCode.UNSUPPORTED_LANGUAGE, "not supported", "f.rb")
        assert d.severity == DiagnosticSeverity.WARNING

    def test_make_diagnostic_dynamic_reference_is_info(self) -> None:
        d = make_diagnostic(DiagnosticCode.DYNAMIC_REFERENCE, "getattr", "f.py")
        assert d.severity == DiagnosticSeverity.INFO

    def test_make_diagnostic_overrides_severity(self) -> None:
        d = make_diagnostic(
            DiagnosticCode.UNRESOLVED_REFERENCE,
            "not found",
            "f.py",
            severity=DiagnosticSeverity.ERROR,
        )
        assert d.severity == DiagnosticSeverity.ERROR

    def test_all_diagnostic_codes_have_default_severity(self) -> None:
        for code in DiagnosticCode:
            d = make_diagnostic(code, "test", "f.py")
            assert d.severity is not None

    def test_line_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            Diagnostic(
                code=DiagnosticCode.SYNTAX_ERROR,
                severity=DiagnosticSeverity.ERROR,
                message="err",
                file_path="f.py",
                line=0,  # must be >= 1
            )

    def test_column_can_be_zero(self) -> None:
        d = make_diagnostic(DiagnosticCode.SYNTAX_ERROR, "err", "f.py", column=0)
        assert d.column == 0
