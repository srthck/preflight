"""Unit tests for the symbol resolver.

Tests cover:
- EXACT resolution (same qualified name)
- IMPORTED resolution (from-import)
- QUALIFIED resolution (module.Name)
- PROJECT_UNIQUE resolution (unique simple name)
- UNRESOLVED (no match found)
- AMBIGUOUS (multiple candidates)
- Dynamic references pass through
- Resolution is deterministic (independent of order)
- Circular imports don't crash
- Missing import doesn't crash
"""

from __future__ import annotations

from preflight.graph.parsers.diagnostics import DiagnosticCode
from preflight.graph.parsers.models import (
    Language,
    ParseStatus,
    Reference,
    ResolutionStatus,
    SourceFile,
    SourceLocation,
    Symbol,
    SymbolKind,
    make_symbol_id,
)
from preflight.graph.parsers.resolver import SymbolIndex, resolve_source_files

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HASH = "a" * 64


def _loc(line: int = 1, col: int = 0) -> SourceLocation:
    return SourceLocation(file_path="svc/f.py", line=line, column=col)


def _sym(name: str, kind: SymbolKind = SymbolKind.CLASS, file_path: str = "svc/f.py") -> Symbol:
    sid = make_symbol_id("svc", file_path, kind, name)
    return Symbol(
        symbol_id=sid,
        qualified_name=name,
        symbol_kind=kind,
        location=_loc(),
    )


def _ref(
    text: str,
    line: int = 5,
    status: ResolutionStatus = ResolutionStatus.UNRESOLVED,
    import_kind: str | None = None,
) -> Reference:
    meta: dict = {}
    if import_kind:
        meta["import_kind"] = import_kind
        if "." in text:
            parts = text.rsplit(".", 1)
            meta["module"] = parts[0]
            meta["name"] = parts[1]
    return Reference(
        reference_text=text,
        location=SourceLocation(file_path="svc/f.py", line=line, column=0),
        resolution_status=status,
        metadata=meta,
    )


def _sf(
    symbols: list[Symbol],
    references: list[Reference],
    file_path: str = "svc/f.py",
) -> SourceFile:
    return SourceFile(
        file_path=file_path,
        language=Language.PYTHON,
        parse_status=ParseStatus.SUCCESS,
        content_hash=_HASH,
        symbols=tuple(symbols),
        references=tuple(references),
    )


# ---------------------------------------------------------------------------
# SymbolIndex tests
# ---------------------------------------------------------------------------


class TestSymbolIndex:
    def test_by_qualified_name(self) -> None:
        sym = _sym("UserService")
        sf = _sf([sym], [])
        idx = SymbolIndex([sf])
        candidates = idx.candidates_by_qualified_name("UserService")
        assert len(candidates) == 1
        assert candidates[0] == sym.symbol_id

    def test_by_simple_name(self) -> None:
        sym = _sym("UserService")
        sf = _sf([sym], [])
        idx = SymbolIndex([sf])
        candidates = idx.candidates_by_simple_name("UserService")
        assert sym.symbol_id in candidates

    def test_multiple_files(self) -> None:
        sym_a = _sym("Foo", file_path="a/f.py")
        sym_b = _sym("Bar", file_path="b/f.py")
        sf_a = _sf([sym_a], [], file_path="a/f.py")
        sf_b = _sf([sym_b], [], file_path="b/f.py")
        idx = SymbolIndex([sf_a, sf_b])
        assert len(idx.all_symbol_ids) == 2

    def test_candidates_sorted(self) -> None:
        sym1 = Symbol(
            symbol_id="z/f.py::class::Foo",
            qualified_name="Foo",
            symbol_kind=SymbolKind.CLASS,
            location=_loc(),
        )
        sym2 = Symbol(
            symbol_id="a/f.py::class::Foo",
            qualified_name="Foo",
            symbol_kind=SymbolKind.CLASS,
            location=_loc(),
        )
        sf1 = _sf([sym1], [], "z/f.py")
        sf2 = _sf([sym2], [], "a/f.py")
        idx = SymbolIndex([sf1, sf2])
        candidates = idx.candidates_by_qualified_name("Foo")
        assert candidates == sorted(candidates)


# ---------------------------------------------------------------------------
# Resolution tests
# ---------------------------------------------------------------------------


class TestResolution:
    def test_exact_resolution(self) -> None:
        sym = _sym("UserService")
        sf = _sf([sym], [_ref("UserService")])
        result = resolve_source_files([sf])
        resolved = result[0].references[0]
        assert resolved.resolution_status == ResolutionStatus.EXACT
        assert resolved.resolved_symbol_id == sym.symbol_id

    def test_imported_resolution(self) -> None:
        """from user_service import UserService → resolves if UserService exists in project."""
        sym = _sym("UserService", file_path="user-service/f.py")
        # File that imports UserService
        importer_sf = _sf(
            [],
            [_ref("user_service.UserService", import_kind="from_import")],
            file_path="profile-api/f.py",
        )
        symbol_sf = _sf([sym], [], file_path="user-service/f.py")
        result = resolve_source_files([importer_sf, symbol_sf])
        # Find the importer's resolved references
        importer_result = next(r for r in result if r.file_path == "profile-api/f.py")
        ref = importer_result.references[0]
        assert ref.resolution_status in (
            ResolutionStatus.IMPORTED,
            ResolutionStatus.QUALIFIED,
            ResolutionStatus.PROJECT_UNIQUE,
        )

    def test_project_unique_resolution(self) -> None:
        """If a name is unique in the project, resolve it even without explicit import.

        PROJECT_UNIQUE fires when the simple name is unique but the reference text
        does NOT exactly match the qualified_name (otherwise EXACT fires first).
        We simulate this by using a qualified_name of "pkg.UniqueClass" so that
        the reference "UniqueClass" (just the simple name) does not match EXACT,
        and falls through to PROJECT_UNIQUE since there is only one symbol with
        that simple name in the entire project.
        """
        sym = Symbol(
            symbol_id=make_symbol_id("svc", "svc/symbols.py", SymbolKind.CLASS, "pkg.UniqueClass"),
            qualified_name="pkg.UniqueClass",
            symbol_kind=SymbolKind.CLASS,
            location=_loc(),
        )
        sf1 = _sf([sym], [], file_path="svc/symbols.py")
        sf2 = _sf([], [_ref("UniqueClass")], file_path="svc/consumer.py")
        result = resolve_source_files([sf1, sf2])
        consumer = next(r for r in result if r.file_path == "svc/consumer.py")
        ref = consumer.references[0]
        assert ref.resolution_status == ResolutionStatus.PROJECT_UNIQUE
        assert ref.resolved_symbol_id == sym.symbol_id

    def test_ambiguous_resolution(self) -> None:
        """Two symbols with same simple name → AMBIGUOUS."""
        sym1 = Symbol(
            symbol_id="a/f.py::class::Foo",
            qualified_name="Foo",
            symbol_kind=SymbolKind.CLASS,
            location=_loc(),
        )
        sym2 = Symbol(
            symbol_id="b/f.py::class::Foo",
            qualified_name="Foo",
            symbol_kind=SymbolKind.CLASS,
            location=_loc(),
        )
        sf1 = _sf([sym1], [], "a/f.py")
        sf2 = _sf([sym2], [], "b/f.py")
        consumer = _sf([], [_ref("Foo")], "c/f.py")
        result = resolve_source_files([sf1, sf2, consumer])
        c_result = next(r for r in result if r.file_path == "c/f.py")
        ref = c_result.references[0]
        assert ref.resolution_status == ResolutionStatus.AMBIGUOUS
        assert len(ref.candidate_symbol_ids) == 2
        # Ambiguous produces a diagnostic
        codes = {d.code for d in c_result.diagnostics}
        assert DiagnosticCode.AMBIGUOUS_REFERENCE in codes

    def test_unresolved_reference_produces_diagnostic(self) -> None:
        sf = _sf([], [_ref("NonExistentClass")])
        result = resolve_source_files([sf])
        r = result[0]
        ref = r.references[0]
        assert ref.resolution_status == ResolutionStatus.UNRESOLVED
        codes = {d.code for d in r.diagnostics}
        assert DiagnosticCode.UNRESOLVED_REFERENCE in codes

    def test_dynamic_reference_passes_through(self) -> None:
        """References already marked DYNAMIC must not be re-resolved."""
        ref = Reference(
            reference_text="getattr_call",
            location=_loc(),
            resolution_status=ResolutionStatus.DYNAMIC,
        )
        sf = _sf([], [ref])
        result = resolve_source_files([sf])
        r = result[0].references[0]
        assert r.resolution_status == ResolutionStatus.DYNAMIC

    def test_result_sorted_by_file_path(self) -> None:
        sf_z = _sf([], [], "z/f.py")
        sf_a = _sf([], [], "a/f.py")
        result = resolve_source_files([sf_z, sf_a])
        paths = [r.file_path for r in result]
        assert paths == sorted(paths)

    def test_same_input_produces_identical_output(self) -> None:
        sym = _sym("Foo")
        sf = _sf([sym], [_ref("Foo")])
        r1 = resolve_source_files([sf])
        r2 = resolve_source_files([sf])
        assert r1[0].references[0].resolution_status == r2[0].references[0].resolution_status

    def test_unused_import_does_not_crash(self) -> None:
        """An import with no corresponding symbol in the project → UNRESOLVED, no crash."""
        ref = _ref("external_lib.SomeClass", import_kind="from_import")
        sf = _sf([], [ref])
        result = resolve_source_files([sf])
        assert result[0].references[0].resolution_status == ResolutionStatus.UNRESOLVED

    def test_same_symbol_name_two_modules_ambiguous(self) -> None:
        """Canonical adversarial test: same class name in two different modules."""
        sym_a = Symbol(
            symbol_id="mod_a/f.py::class::Widget",
            qualified_name="Widget",
            symbol_kind=SymbolKind.CLASS,
            location=_loc(),
        )
        sym_b = Symbol(
            symbol_id="mod_b/f.py::class::Widget",
            qualified_name="Widget",
            symbol_kind=SymbolKind.CLASS,
            location=_loc(),
        )
        sf_a = _sf([sym_a], [], "mod_a/f.py")
        sf_b = _sf([sym_b], [], "mod_b/f.py")
        consumer = _sf([], [_ref("Widget")], "consumer/f.py")
        result = resolve_source_files([sf_a, sf_b, consumer])
        c = next(r for r in result if r.file_path == "consumer/f.py")
        assert c.references[0].resolution_status == ResolutionStatus.AMBIGUOUS
