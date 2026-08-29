"""Deterministic symbol resolver for the PreFlight parser layer.

The resolver takes a collection of SourceFile objects and attempts to
resolve each Reference to a known Symbol.

Resolution algorithm (documented in docs/DAY_2.md)
---------------------------------------------------
Resolution is attempted in the following priority order for each reference:

1. EXACT      — reference text matches a symbol's qualified_name exactly
                in the same file.
2. IMPORTED   — the file contains an import statement whose target matches
                the reference text (last segment comparison).
3. QUALIFIED  — reference text contains a dot; attempt to match the last
                segment against known symbol names.
4. PROJECT_UNIQUE — the unqualified name is unique across the entire project.
5. UNRESOLVED — no match found.

Ambiguity
---------
If multiple candidates satisfy a resolution level, the reference is marked
AMBIGUOUS with all candidate IDs listed. The resolver does NOT arbitrarily
pick one.

Dynamic references
------------------
References marked DYNAMIC (detected by the parser, e.g. getattr()) are
not passed to the resolver — they already carry a diagnostic and are
left as-is.

Determinism
-----------
- All candidate lists are sorted by symbol_id before comparison.
- Results are deterministic regardless of the order SourceFile objects
  were added to the index.
- No random ID generation, no hash-randomized set iteration.

Security
--------
The resolver works exclusively on the normalized data in SourceFile objects.
It does not access the filesystem, network, or any external service.
"""

from __future__ import annotations

from collections import defaultdict

from preflight.graph.parsers.diagnostics import Diagnostic, DiagnosticCode, make_diagnostic
from preflight.graph.parsers.models import (
    Reference,
    ResolutionStatus,
    SourceFile,
    Symbol,
)


class SymbolIndex:
    """An immutable index over a collection of SourceFile objects.

    Built once from all parsed files. Used by the resolver for O(1)
    lookup during resolution.

    The index is deterministic: given the same set of SourceFile objects,
    the same index is always produced.
    """

    def __init__(self, source_files: list[SourceFile]) -> None:
        # symbol_id → Symbol
        self._by_id: dict[str, Symbol] = {}
        # qualified_name → sorted list of symbol_ids
        self._by_qualified_name: dict[str, list[str]] = defaultdict(list)
        # simple name (last segment) → sorted list of symbol_ids
        self._by_simple_name: dict[str, list[str]] = defaultdict(list)
        # file_path → list of symbol_ids in that file
        self._by_file: dict[str, list[str]] = defaultdict(list)

        for sf in source_files:
            for sym in sf.symbols:
                self._by_id[sym.symbol_id] = sym
                self._by_qualified_name[sym.qualified_name].append(sym.symbol_id)
                simple = _simple_name(sym.qualified_name)
                self._by_simple_name[simple].append(sym.symbol_id)
                self._by_file[sf.file_path].append(sym.symbol_id)

        # Sort all candidate lists for determinism.
        for lst in self._by_qualified_name.values():
            lst.sort()
        for lst in self._by_simple_name.values():
            lst.sort()
        for lst in self._by_file.values():
            lst.sort()

    def get_by_id(self, symbol_id: str) -> Symbol | None:
        return self._by_id.get(symbol_id)

    def candidates_by_qualified_name(self, name: str) -> list[str]:
        return list(self._by_qualified_name.get(name, []))

    def candidates_by_simple_name(self, name: str) -> list[str]:
        return list(self._by_simple_name.get(name, []))

    def symbols_in_file(self, file_path: str) -> list[str]:
        return list(self._by_file.get(file_path, []))

    @property
    def all_symbol_ids(self) -> list[str]:
        return sorted(self._by_id.keys())


def resolve_source_files(source_files: list[SourceFile]) -> list[SourceFile]:
    """Resolve all references in a collection of SourceFiles.

    Returns a new list of SourceFile objects with resolved references
    and additional UNRESOLVED/AMBIGUOUS diagnostics where applicable.

    The input list is not modified.

    Parameters
    ----------
    source_files:
        Parsed SourceFile objects. May include files with syntax errors
        (their references will still be resolved where possible).

    Returns
    -------
    list[SourceFile]
        New SourceFile objects with updated ``references`` and ``diagnostics``.
        The list is sorted by file_path for determinism.
    """
    index = SymbolIndex(source_files)
    resolved_files: list[SourceFile] = []

    for sf in sorted(source_files, key=lambda f: f.file_path):
        resolved_refs, new_diags = _resolve_file_references(sf, index)
        # Merge diagnostics (existing + new), sorted deterministically.
        all_diags = tuple(
            sorted(
                list(sf.diagnostics) + new_diags,
                key=lambda d: (d.line or 0, d.column or 0, d.message),
            )
        )
        # Replace the source file with updated references and diagnostics.
        resolved_files.append(
            SourceFile(
                file_path=sf.file_path,
                language=sf.language,
                parse_status=sf.parse_status,
                content_hash=sf.content_hash,
                syntax_error_count=sf.syntax_error_count,
                symbols=sf.symbols,
                references=tuple(
                    sorted(
                        resolved_refs,
                        key=lambda r: (r.location.line, r.location.column, r.reference_text),
                    )
                ),
                diagnostics=all_diags,
            )
        )

    return resolved_files


def _resolve_file_references(
    sf: SourceFile,
    index: SymbolIndex,
) -> tuple[list[Reference], list[Diagnostic]]:
    """Resolve all references in a single SourceFile.

    Returns resolved reference list and any new diagnostics produced.
    """
    # Build a set of imported names visible in this file.
    # These are the last-segment names from from-import references.
    imported_names: dict[str, list[str]] = defaultdict(list)
    for ref in sf.references:
        if ref.metadata.get("import_kind") in ("from_import", "from_import_aliased"):
            name = ref.metadata.get("name", "")
            if name and name != "*":
                imported_names[name].append(ref.reference_text)

    resolved_refs: list[Reference] = []
    new_diags: list[Diagnostic] = []

    for ref in sf.references:
        # Already-resolved or dynamic references pass through unchanged.
        if ref.resolution_status != ResolutionStatus.UNRESOLVED:
            resolved_refs.append(ref)
            continue

        resolved_ref, diag = _resolve_single(ref, sf.file_path, index, imported_names)
        resolved_refs.append(resolved_ref)
        if diag:
            new_diags.append(diag)

    return resolved_refs, new_diags


def _resolve_single(
    ref: Reference,
    file_path: str,
    index: SymbolIndex,
    imported_names: dict[str, list[str]],
) -> tuple[Reference, Diagnostic | None]:
    """Attempt to resolve a single reference. Returns the updated reference
    and an optional diagnostic for UNRESOLVED or AMBIGUOUS cases.
    """
    text = ref.reference_text

    # Step 1: EXACT — exact qualified_name match anywhere in the project.
    candidates = index.candidates_by_qualified_name(text)
    if len(candidates) == 1:
        return _resolved(ref, ResolutionStatus.EXACT, candidates[0]), None
    if len(candidates) > 1:
        return _ambiguous(ref, candidates, file_path)

    # Step 2: IMPORTED — check if text matches a name that was explicitly imported.
    # For "module.ClassName" references, check the ClassName segment.
    simple = _simple_name(text)
    if simple in imported_names:
        # The import tells us the full qualified name; use it for resolution.
        full_names = sorted(set(imported_names[simple]))
        for full_name in full_names:
            import_candidates = index.candidates_by_qualified_name(full_name)
            if import_candidates:
                if len(import_candidates) == 1:
                    return _resolved(ref, ResolutionStatus.IMPORTED, import_candidates[0]), None
                return _ambiguous(ref, import_candidates, file_path)

    # Step 3: QUALIFIED — reference contains a dot; match on the last segment.
    if "." in text:
        last_segment = text.rsplit(".", 1)[-1]
        candidates = index.candidates_by_simple_name(last_segment)
        if len(candidates) == 1:
            return _resolved(ref, ResolutionStatus.QUALIFIED, candidates[0]), None
        if len(candidates) > 1:
            return _ambiguous(ref, candidates, file_path)

    # Step 4: PROJECT_UNIQUE — match simple name uniquely across the project.
    candidates = index.candidates_by_simple_name(simple)
    if len(candidates) == 1:
        return _resolved(ref, ResolutionStatus.PROJECT_UNIQUE, candidates[0]), None
    if len(candidates) > 1:
        return _ambiguous(ref, candidates, file_path)

    # Step 5: UNRESOLVED
    diag = make_diagnostic(
        DiagnosticCode.UNRESOLVED_REFERENCE,
        f"Reference {text!r} could not be resolved to any known symbol.",
        file_path,
        line=ref.location.line,
        column=ref.location.column,
        context={"reference_text": text},
    )
    updated = Reference(
        reference_text=ref.reference_text,
        location=ref.location,
        resolution_status=ResolutionStatus.UNRESOLVED,
        resolved_symbol_id=None,
        candidate_symbol_ids=(),
        metadata=ref.metadata,
    )
    return updated, diag


def _resolved(
    ref: Reference,
    status: ResolutionStatus,
    symbol_id: str,
) -> Reference:
    return Reference(
        reference_text=ref.reference_text,
        location=ref.location,
        resolution_status=status,
        resolved_symbol_id=symbol_id,
        candidate_symbol_ids=(),
        metadata=ref.metadata,
    )


def _ambiguous(
    ref: Reference,
    candidates: list[str],
    file_path: str,
) -> tuple[Reference, Diagnostic]:
    sorted_candidates = tuple(sorted(candidates))
    diag = make_diagnostic(
        DiagnosticCode.AMBIGUOUS_REFERENCE,
        (
            f"Reference {ref.reference_text!r} is ambiguous: "
            f"{len(sorted_candidates)} candidates found."
        ),
        file_path,
        line=ref.location.line,
        column=ref.location.column,
        context={"candidates": list(sorted_candidates)},
    )
    updated = Reference(
        reference_text=ref.reference_text,
        location=ref.location,
        resolution_status=ResolutionStatus.AMBIGUOUS,
        resolved_symbol_id=None,
        candidate_symbol_ids=sorted_candidates,
        metadata=ref.metadata,
    )
    return updated, diag


def _simple_name(qualified_name: str) -> str:
    """Return the last segment of a qualified name."""
    return qualified_name.rsplit(".", 1)[-1]
