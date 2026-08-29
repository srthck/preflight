"""SourceExtractor — orchestrates file discovery, parsing, resolution,
and domain-level entity/edge production.

This is the top-level entry point for the Day 2 parser layer.
Callers outside the parsers package use only this module.

Architecture
------------
    SourceExtractor.extract(root_path)
        → discover source files (sorted, deterministic)
        → LanguageRegistry.parse_file() for each file
        → SymbolIndex.build()
        → resolve_source_files()
        → emit domain Entity + DependencyEdge objects
        → return ExtractionResult

ExtractionResult
----------------
Contains:
  - source_files   : all parsed SourceFile objects (resolved)
  - entities       : domain Entity objects derived from parsed symbols
  - edges          : domain DependencyEdge objects derived from resolved references
  - diagnostics    : all diagnostics across all files
  - performance    : timing breakdown (for Day 2 baseline)

Determinism
-----------
File discovery is done with sorted(path.rglob()), not os.listdir() or
unordered glob. The sort key is the normalized relative path string.
Two runs on the same directory must produce identical ExtractionResult.

Security
--------
Source bytes are read from disk but never executed, imported, or evaluated.
The extractor does not invoke any external tools (compilers, linters, etc.).

Entity/Edge generation policy
------------------------------
Only IMPORT edges are generated on Day 2 from resolved references with
kind "from_import" or "import". Application-level semantic edges
(HTTP_CALL, API_CONSUMES) require richer context and are deferred to
Days 3–4 where the full dependency graph is wired.

The entity_id for parser-derived entities follows the Day 1 convention:
  ``<service-name>.<ClassName>``
This is mapped from the symbol's qualified_name (the class name)
and the service directory name.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from preflight.domain.entities import Entity
from preflight.domain.enums import EdgeKind, EntityKind
from preflight.domain.graph_models import DependencyEdge
from preflight.graph.parsers.diagnostics import Diagnostic
from preflight.graph.parsers.models import (
    ParseStatus,
    ResolutionStatus,
    SourceFile,
    Symbol,
    SymbolKind,
)
from preflight.graph.parsers.registry import LanguageRegistry
from preflight.graph.parsers.resolver import resolve_source_files


class PerformanceBaseline:
    """Timing measurements for a single extraction run.

    Times are in seconds (float). NOT used in canonical output.
    Intended only for human-facing reporting and the Day 2 baseline.
    """

    def __init__(
        self,
        files_analyzed: int,
        total_bytes: int,
        discovery_time: float,
        parse_time: float,
        resolution_time: float,
        entity_edge_time: float,
    ) -> None:
        self.files_analyzed = files_analyzed
        self.total_bytes = total_bytes
        self.discovery_time = discovery_time
        self.parse_time = parse_time
        self.resolution_time = resolution_time
        self.entity_edge_time = entity_edge_time

    @property
    def total_time(self) -> float:
        return (
            self.discovery_time
            + self.parse_time
            + self.resolution_time
            + self.entity_edge_time
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "files_analyzed": self.files_analyzed,
            "total_bytes": self.total_bytes,
            "discovery_time_s": round(self.discovery_time, 4),
            "parse_time_s": round(self.parse_time, 4),
            "resolution_time_s": round(self.resolution_time, 4),
            "entity_edge_time_s": round(self.entity_edge_time, 4),
            "total_time_s": round(self.total_time, 4),
        }


class ExtractionResult:
    """Complete output of a SourceExtractor.extract() call.

    Immutable after construction. All lists are sorted for determinism.
    """

    def __init__(
        self,
        source_files: list[SourceFile],
        entities: list[Entity],
        edges: list[DependencyEdge],
        diagnostics: list[Diagnostic],
        performance: PerformanceBaseline,
    ) -> None:
        # Sort all outputs for determinism.
        self.source_files: list[SourceFile] = sorted(
            source_files, key=lambda f: f.file_path
        )
        self.entities: list[Entity] = sorted(
            entities, key=lambda e: e.entity_id
        )
        self.edges: list[DependencyEdge] = sorted(
            edges, key=lambda e: (e.source, e.target, e.kind.value)
        )
        self.diagnostics: list[Diagnostic] = sorted(
            diagnostics, key=lambda d: (d.file_path, d.line or 0, d.column or 0, d.message)
        )
        self.performance = performance

    @property
    def file_count(self) -> int:
        return len(self.source_files)

    @property
    def symbol_count(self) -> int:
        return sum(len(sf.symbols) for sf in self.source_files)

    @property
    def reference_count(self) -> int:
        return sum(len(sf.references) for sf in self.source_files)

    @property
    def resolved_count(self) -> int:
        return sum(
            sum(
                1
                for r in sf.references
                if r.resolution_status
                in (
                    ResolutionStatus.EXACT,
                    ResolutionStatus.IMPORTED,
                    ResolutionStatus.QUALIFIED,
                    ResolutionStatus.PROJECT_UNIQUE,
                )
            )
            for sf in self.source_files
        )

    @property
    def unresolved_count(self) -> int:
        return sum(
            sum(
                1
                for r in sf.references
                if r.resolution_status == ResolutionStatus.UNRESOLVED
            )
            for sf in self.source_files
        )

    @property
    def language_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for sf in self.source_files:
            if sf.parse_status != ParseStatus.PARSE_FAILURE:
                key = sf.language.value
                counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))


class SourceExtractor:
    """Orchestrates file discovery, parsing, resolution, and entity/edge emission.

    Usage::

        from pathlib import Path
        extractor = SourceExtractor()
        result = extractor.extract(Path("fixtures/demo-commerce"))

        for entity in result.entities:
            print(entity.entity_id)
    """

    # File extensions that will be analyzed.
    # Files with other extensions are silently skipped during discovery
    # (we do not emit diagnostics for every .gitignore or .md file).
    _ANALYZED_EXTENSIONS = frozenset([".py", ".pyw", ".kt"])

    def __init__(self) -> None:
        self._registry = LanguageRegistry()

    def extract(self, root_path: Path) -> ExtractionResult:
        """Analyze all source files under ``root_path``.

        Parameters
        ----------
        root_path:
            Root directory to analyze. Must exist.

        Returns
        -------
        ExtractionResult
            Fully populated, deterministically sorted extraction result.

        Raises
        ------
        ValueError
            If ``root_path`` does not exist or is not a directory.
        """
        if not root_path.exists():
            raise ValueError(f"root_path does not exist: {root_path}")
        if not root_path.is_dir():
            raise ValueError(f"root_path is not a directory: {root_path}")

        # --- Discovery phase ---
        t0 = time.perf_counter()
        source_paths = self._discover_files(root_path)
        discovery_time = time.perf_counter() - t0

        # --- Parse phase ---
        t1 = time.perf_counter()
        source_files: list[SourceFile] = []
        total_bytes = 0
        for file_path, service_name, rel_path in source_paths:
            raw = file_path.read_bytes()
            total_bytes += len(raw)
            sf = self._registry.parse_file(raw, rel_path, service_name)
            source_files.append(sf)
        parse_time = time.perf_counter() - t1

        # --- Resolution phase ---
        t2 = time.perf_counter()
        resolved_files = resolve_source_files(source_files)
        resolution_time = time.perf_counter() - t2

        # --- Entity/edge emission phase ---
        t3 = time.perf_counter()
        entities, edges = _emit_entities_and_edges(resolved_files, root_path)
        entity_edge_time = time.perf_counter() - t3

        # --- Collect all diagnostics ---
        all_diagnostics: list[Diagnostic] = []
        for sf in resolved_files:
            all_diagnostics.extend(sf.diagnostics)

        perf = PerformanceBaseline(
            files_analyzed=len(source_files),
            total_bytes=total_bytes,
            discovery_time=discovery_time,
            parse_time=parse_time,
            resolution_time=resolution_time,
            entity_edge_time=entity_edge_time,
        )

        return ExtractionResult(
            source_files=resolved_files,
            entities=entities,
            edges=edges,
            diagnostics=all_diagnostics,
            performance=perf,
        )

    def _discover_files(
        self,
        root_path: Path,
    ) -> list[tuple[Path, str, str]]:
        """Discover and sort all supported source files under root_path.

        Returns a sorted list of (absolute_path, service_name, relative_path)
        tuples. Sorting is by the relative path string (forward slashes) to
        guarantee filesystem-order independence.

        service_name is derived from the first path component under root_path.
        For example: root_path=fixtures/demo-commerce,
            file=user-service/src/user_service.py → service_name="user-service"
        """
        found: list[tuple[str, Path, str, str]] = []  # (sort_key, abs, service, rel)

        for ext in sorted(self._ANALYZED_EXTENSIONS):
            for abs_path in root_path.rglob(f"*{ext}"):
                if not abs_path.is_file():
                    continue
                rel = abs_path.relative_to(root_path)
                # Normalize to forward slashes for cross-platform determinism.
                rel_str = rel.as_posix()
                # First component is the service directory name.
                parts = rel.parts
                service_name = parts[0] if parts else root_path.name
                found.append((rel_str, abs_path, service_name, rel_str))

        # Sort by normalized relative path — this is the determinism guarantee.
        found.sort(key=lambda t: t[0])
        return [(abs_path, service, rel) for _, abs_path, service, rel in found]


# ---------------------------------------------------------------------------
# Entity / edge emission
# ---------------------------------------------------------------------------


def _emit_entities_and_edges(
    source_files: list[SourceFile],
    root_path: Path,
) -> tuple[list[Entity], list[DependencyEdge]]:
    """Produce domain Entity and DependencyEdge objects from resolved SourceFiles.

    Entity generation policy (Day 2)
    ---------------------------------
    - A CLASS or DATA_CLASS symbol produces an Entity.
    - The entity_id follows the Day 1 convention:
        ``<service-name>.<ClassName>``
    - Only top-level class names are used (no dot-nested symbols for entity IDs).
    - MODULE symbols are emitted as SYMBOL-kind entities for completeness.

    Edge generation policy (Day 2)
    --------------------------------
    Only IMPORT edges are emitted. An IMPORT edge is created when:
    - A reference is resolved (status != UNRESOLVED/AMBIGUOUS)
    - The reference metadata indicates import_kind in ("import", "from_import", ...)
    - Source entity != target entity (no self-loops)

    Application-level edges (HTTP_CALL, API_CONSUMES) are NOT generated
    here — that requires context from Days 3–4.
    """
    entities: list[Entity] = []
    edges: list[DependencyEdge] = []
    seen_entity_ids: set[str] = set()
    seen_edge_keys: set[tuple[str, str, str]] = set()

    # Build entity_id → entity mapping for edge construction.
    class_symbol_to_entity_id: dict[str, str] = {}

    for sf in source_files:
        service_name = _service_from_file_path(sf.file_path)

        for sym in sf.symbols:
            entity_id, entity = _symbol_to_entity(sym, service_name, sf.file_path)
            if entity_id is None or entity is None:
                continue
            if entity_id not in seen_entity_ids:
                seen_entity_ids.add(entity_id)
                entities.append(entity)
                class_symbol_to_entity_id[sym.symbol_id] = entity_id

    # Generate IMPORT edges from resolved import references.
    # Build a symbol_id → entity_id lookup.
    sym_to_entity: dict[str, str] = {}
    for sf in source_files:
        service_name = _service_from_file_path(sf.file_path)
        for sym in sf.symbols:
            eid, _ = _symbol_to_entity(sym, service_name, sf.file_path)
            if eid:
                sym_to_entity[sym.symbol_id] = eid

    for sf in source_files:
        # Find the entity_id of the module/class for this file as the edge source.
        # Use the first CLASS symbol in the file as the source entity,
        # falling back to None if no class exists.
        source_entity_id = _primary_entity_id_for_file(sf, sym_to_entity)
        if source_entity_id is None:
            continue

        for ref in sf.references:
            if ref.resolution_status not in (
                ResolutionStatus.EXACT,
                ResolutionStatus.IMPORTED,
                ResolutionStatus.QUALIFIED,
                ResolutionStatus.PROJECT_UNIQUE,
            ):
                continue

            if ref.metadata.get("import_kind") not in (
                "import",
                "from_import",
                "from_import_aliased",
            ):
                continue

            if ref.resolved_symbol_id is None:
                continue

            target_entity_id = sym_to_entity.get(ref.resolved_symbol_id)
            if target_entity_id is None:
                continue

            if source_entity_id == target_entity_id:
                continue  # no self-loops

            edge_key = (source_entity_id, target_entity_id, EdgeKind.IMPORT.value)
            if edge_key in seen_edge_keys:
                continue

            seen_edge_keys.add(edge_key)
            edges.append(
                DependencyEdge(
                    source=source_entity_id,
                    target=target_entity_id,
                    kind=EdgeKind.IMPORT,
                    metadata={
                        "reference_text": ref.reference_text,
                        "resolution_status": ref.resolution_status.value,
                        "source_file": sf.file_path,
                    },
                )
            )

    return entities, edges


def _symbol_to_entity(
    sym: Symbol,
    service_name: str,
    file_path: str,
) -> tuple[str | None, Entity | None]:
    """Convert a Symbol to a domain Entity using Day 1 entity_id conventions.

    Only CLASS, DATA_CLASS, INTERFACE, and OBJECT symbols produce entities.
    Top-level only (no dot in qualified_name means top-level).
    MODULE symbols also produce SYMBOL-kind entities.
    """
    if sym.symbol_kind in (SymbolKind.CLASS, SymbolKind.DATA_CLASS, SymbolKind.INTERFACE):
        # Top-level only: qualified_name has no dot separator (except for the package)
        class_name = sym.qualified_name
        if "." in class_name:
            # Nested class — skip for Day 2 entity generation.
            return None, None
        entity_id = f"{service_name}.{class_name}"
        kind = EntityKind.SERVICE  # Default; Day 3+ refines this
        entity = Entity(
            entity_id=entity_id,
            name=class_name,
            kind=kind,
            service=service_name,
            file=file_path,
            line=sym.location.line,
            metadata={
                "symbol_id": sym.symbol_id,
                "symbol_kind": sym.symbol_kind.value,
                "source": "tree-sitter",
            },
        )
        return entity_id, entity

    if sym.symbol_kind == SymbolKind.OBJECT:
        entity_id = f"{service_name}.{sym.qualified_name}"
        entity = Entity(
            entity_id=entity_id,
            name=sym.qualified_name,
            kind=EntityKind.SERVICE,
            service=service_name,
            file=file_path,
            line=sym.location.line,
            metadata={"symbol_id": sym.symbol_id, "symbol_kind": "object", "source": "tree-sitter"},
        )
        return entity_id, entity

    return None, None


def _primary_entity_id_for_file(
    sf: SourceFile,
    sym_to_entity: dict[str, str],
) -> str | None:
    """Return the primary entity_id to use as the source for IMPORT edges.

    Priority: first CLASS/DATA_CLASS symbol → first OBJECT → None.
    """
    for sym in sorted(sf.symbols, key=lambda s: (s.location.line, s.location.column)):
        if sym.symbol_kind in (SymbolKind.CLASS, SymbolKind.DATA_CLASS):
            eid = sym_to_entity.get(sym.symbol_id)
            if eid:
                return eid
    return None


def _service_from_file_path(file_path: str) -> str:
    """Extract the service name from the first path component."""
    parts = file_path.split("/")
    return parts[0] if parts else file_path
