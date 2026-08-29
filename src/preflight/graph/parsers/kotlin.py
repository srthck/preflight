"""Kotlin language parser for PreFlight.

Uses Tree-sitter as the AST engine. Tree-sitter objects never leave this module.

What is extracted
-----------------
Symbols:
  - package declaration (one per file)
  - class declarations (regular, data class, interface)
  - object declarations
  - function/method declarations (fun)

References:
  - import statements (``import com.example.ClassName``)
  - constructor calls (``ClassName()``)
  - method calls (``obj.method()``)

Kotlin-specific notes
---------------------
- ``data class`` is identified via the ``data`` modifier in the AST.
- ``interface`` uses ``interface_declaration`` node type in tree-sitter-kotlin.
- ``object`` uses ``object_declaration`` node type.
- Kotlin does not have async/await at the language level (coroutines are library-level);
  ``suspend fun`` is treated as a regular method.

Security
--------
The parser NEVER executes Kotlin code. It is purely syntactic.
It does not invoke the Kotlin compiler, Gradle, or any JVM.

Determinism
-----------
All collections are sorted by (line, column, text) before freezing.
"""

from __future__ import annotations

import logging
from typing import Any

import tree_sitter_kotlin as tskotlin
from tree_sitter import Language, Node, Parser

from preflight.graph.parsers.base import SourceParser
from preflight.graph.parsers.diagnostics import DiagnosticCode, DiagnosticSeverity, make_diagnostic
from preflight.graph.parsers.models import (
    Language as Lang,
)
from preflight.graph.parsers.models import (
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

_LOG = logging.getLogger(__name__)

_KT_LANGUAGE = Language(tskotlin.language())


class KotlinParser(SourceParser):
    """Tree-sitter-based Kotlin source parser.

    Stateless and re-entrant.
    """

    def __init__(self) -> None:
        self._ts_parser = Parser(_KT_LANGUAGE)

    @property
    def language(self) -> Lang:
        return Lang.KOTLIN

    def parse(
        self,
        source_bytes: bytes,
        file_path: str,
        service_name: str,
    ) -> SourceFile:
        """Parse Kotlin source bytes and return a normalized SourceFile."""
        content_hash = make_content_hash(source_bytes)
        diagnostics = []
        symbols: list[Symbol] = []
        references: list[Reference] = []

        try:
            tree = self._ts_parser.parse(source_bytes)
        except Exception as exc:  # noqa: BLE001
            diag = make_diagnostic(
                DiagnosticCode.PARSER_FAILURE,
                f"Tree-sitter raised an unexpected exception: {exc}",
                file_path,
            )
            return SourceFile(
                file_path=file_path,
                language=Lang.KOTLIN,
                parse_status=ParseStatus.PARSE_FAILURE,
                content_hash=content_hash,
                syntax_error_count=0,
                diagnostics=(diag,),
            )

        root = tree.root_node
        syntax_error_count = _count_error_nodes(root)
        if syntax_error_count > 0:
            diagnostics.append(
                make_diagnostic(
                    DiagnosticCode.SYNTAX_ERROR,
                    f"Source file contains {syntax_error_count} syntax error node(s).",
                    file_path,
                    severity=DiagnosticSeverity.ERROR,
                )
            )
            parse_status = ParseStatus.SYNTAX_ERROR
        else:
            parse_status = ParseStatus.SUCCESS

        # Module-level symbol: one per file.
        module_id = make_symbol_id(service_name, file_path, SymbolKind.MODULE, file_path)
        symbols.append(
            Symbol(
                symbol_id=module_id,
                qualified_name=file_path,
                symbol_kind=SymbolKind.MODULE,
                location=SourceLocation(file_path=file_path, line=1, column=0),
                is_public=True,
            )
        )

        # Walk top-level AST.
        _extract_top_level(
            root, source_bytes, file_path, service_name, symbols, references, diagnostics
        )

        sorted_symbols = tuple(
            sorted(symbols, key=lambda s: (s.location.line, s.location.column, s.qualified_name))
        )
        sorted_references = tuple(
            sorted(
                references,
                key=lambda r: (r.location.line, r.location.column, r.reference_text),
            )
        )
        sorted_diagnostics = tuple(
            sorted(diagnostics, key=lambda d: (d.line or 0, d.column or 0, d.message))
        )

        return SourceFile(
            file_path=file_path,
            language=Lang.KOTLIN,
            parse_status=parse_status,
            content_hash=content_hash,
            syntax_error_count=syntax_error_count,
            symbols=sorted_symbols,
            references=sorted_references,
            diagnostics=sorted_diagnostics,
        )


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


def _extract_top_level(
    node: Node,
    src: bytes,
    file_path: str,
    service_name: str,
    symbols: list[Symbol],
    references: list[Reference],
    diagnostics: list[Any],
) -> None:
    for child in node.named_children:
        ntype = child.type
        if ntype == "package_header":
            _extract_package(child, src, file_path, service_name, symbols)
        elif ntype == "import":
            _extract_import(child, src, file_path, references)
        elif ntype == "class_declaration":
            _extract_class(child, src, file_path, service_name, symbols, references, parent=None)
        elif ntype == "object_declaration":
            _extract_object(child, src, file_path, service_name, symbols, references)
        elif ntype == "function_declaration":
            _extract_function(child, src, file_path, service_name, symbols, references, parent=None)


def _extract_package(
    node: Node,
    src: bytes,
    file_path: str,
    service_name: str,
    symbols: list[Symbol],
) -> None:
    qi = _get_child_by_type(node, "qualified_identifier")
    if qi is None:
        return
    pkg_text = _node_text(qi, src)
    symbol_id = make_symbol_id(service_name, file_path, SymbolKind.PACKAGE, pkg_text)
    symbols.append(
        Symbol(
            symbol_id=symbol_id,
            qualified_name=pkg_text,
            symbol_kind=SymbolKind.PACKAGE,
            location=_loc(qi, file_path),
            is_public=True,
        )
    )


def _extract_import(
    node: Node,
    src: bytes,
    file_path: str,
    references: list[Reference],
) -> None:
    qi = _get_child_by_type(node, "qualified_identifier")
    if qi is None:
        return
    import_text = _node_text(qi, src)
    # The last segment is the imported class/symbol name.
    references.append(
        Reference(
            reference_text=import_text,
            location=_loc(qi, file_path),
            resolution_status=ResolutionStatus.UNRESOLVED,
            metadata={"import_kind": "import", "full_path": import_text},
        )
    )


def _extract_class(
    node: Node,
    src: bytes,
    file_path: str,
    service_name: str,
    symbols: list[Symbol],
    references: list[Reference],
    parent: str | None,
) -> None:
    name_node = _get_child_by_type(node, "identifier")
    if name_node is None:
        return

    class_name = _node_text(name_node, src)
    qualified = f"{parent}.{class_name}" if parent else class_name

    # Check for data class modifier.
    modifiers_node = _get_child_by_type(node, "modifiers")
    is_data = False
    is_interface = False
    if modifiers_node:
        mod_text = _node_text(modifiers_node, src)
        is_data = "data" in mod_text
    # Check node type for interface
    if node.type == "interface_declaration":
        is_interface = True

    kind = (
        SymbolKind.DATA_CLASS
        if is_data
        else (SymbolKind.INTERFACE if is_interface else SymbolKind.CLASS)
    )
    symbol_id = make_symbol_id(service_name, file_path, kind, qualified)
    symbols.append(
        Symbol(
            symbol_id=symbol_id,
            qualified_name=qualified,
            symbol_kind=kind,
            location=_loc(name_node, file_path),
            is_public=True,
        )
    )

    # Extract methods from class body.
    body = _get_child_by_type(node, "class_body")
    if body:
        for child in body.named_children:
            if child.type == "function_declaration":
                _extract_function(
                    child, src, file_path, service_name, symbols, references, parent=qualified
                )
            elif child.type == "class_declaration":
                _extract_class(
                    child, src, file_path, service_name, symbols, references, parent=qualified
                )


def _extract_object(
    node: Node,
    src: bytes,
    file_path: str,
    service_name: str,
    symbols: list[Symbol],
    references: list[Reference],
) -> None:
    name_node = _get_child_by_type(node, "identifier")
    if name_node is None:
        return
    obj_name = _node_text(name_node, src)
    symbol_id = make_symbol_id(service_name, file_path, SymbolKind.OBJECT, obj_name)
    symbols.append(
        Symbol(
            symbol_id=symbol_id,
            qualified_name=obj_name,
            symbol_kind=SymbolKind.OBJECT,
            location=_loc(name_node, file_path),
            is_public=True,
        )
    )
    body = _get_child_by_type(node, "class_body")
    if body:
        for child in body.named_children:
            if child.type == "function_declaration":
                _extract_function(
                    child, src, file_path, service_name, symbols, references, parent=obj_name
                )


def _extract_function(
    node: Node,
    src: bytes,
    file_path: str,
    service_name: str,
    symbols: list[Symbol],
    references: list[Reference],
    parent: str | None,
) -> None:
    name_node = _get_child_by_type(node, "identifier")
    if name_node is None:
        return

    func_name = _node_text(name_node, src)
    qualified = f"{parent}.{func_name}" if parent else func_name
    kind = SymbolKind.METHOD if parent else SymbolKind.FUNCTION
    symbol_id = make_symbol_id(service_name, file_path, kind, qualified)
    symbols.append(
        Symbol(
            symbol_id=symbol_id,
            qualified_name=qualified,
            symbol_kind=kind,
            location=_loc(name_node, file_path),
            is_public=not func_name.startswith("_"),
        )
    )

    # Extract call references from function body.
    body = _get_child_by_type(node, "function_body")
    if body:
        block = _get_child_by_type(body, "block")
        if block:
            _extract_block_refs(block, src, file_path, references)


def _extract_block_refs(
    node: Node,
    src: bytes,
    file_path: str,
    references: list[Reference],
) -> None:
    """Extract call references from a Kotlin block."""
    for child in node.named_children:
        ntype = child.type
        if ntype in ("call_expression", "navigation_expression"):
            _extract_call_ref(child, src, file_path, references)
        elif ntype == "return_expression":
            for sub in child.named_children:
                if sub.type in ("call_expression", "navigation_expression"):
                    _extract_call_ref(sub, src, file_path, references)
        elif ntype in ("property_declaration", "assignment"):
            for sub in child.named_children:
                if sub.type == "call_expression":
                    _extract_call_ref(sub, src, file_path, references)


def _extract_call_ref(
    node: Node,
    src: bytes,
    file_path: str,
    references: list[Reference],
) -> None:
    """Extract a single call or navigation reference."""
    ref_text = _node_text(node, src)
    # For navigation expressions: strip the argument part
    if "(" in ref_text:
        ref_text = ref_text.split("(")[0].strip()
    references.append(
        Reference(
            reference_text=ref_text,
            location=_loc(node, file_path),
            resolution_status=ResolutionStatus.UNRESOLVED,
            metadata={"reference_kind": "call"},
        )
    )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _node_text(node: Node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _loc(node: Node, file_path: str) -> SourceLocation:
    return SourceLocation(
        file_path=file_path,
        line=node.start_point[0] + 1,
        column=node.start_point[1],
    )


def _get_child_by_type(node: Node, type_name: str) -> Node | None:
    for child in node.children:
        if child.type == type_name:
            return child
    return None


def _count_error_nodes(node: Node) -> int:
    count = 1 if node.is_error or node.type == "ERROR" else 0
    for child in node.children:
        count += _count_error_nodes(child)
    return count
