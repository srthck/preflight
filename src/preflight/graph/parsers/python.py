"""Python language parser for PreFlight.

Uses Tree-sitter as the AST engine. Tree-sitter objects never leave this module.

What is extracted
-----------------
Symbols:
  - module (one per file, at line 1)
  - class definitions (including data classes via @dataclass)
  - function/method definitions (sync and async)

References:
  - import statements (``import x``, ``import x.y``)
  - from-import statements (``from x import y``, ``from x.y import z, w``)
  - direct calls to known symbols (``UserService()``, ``service.get_profile()``)
  - getattr() calls → DYNAMIC diagnostic

Dynamic reference detection
----------------------------
``getattr(obj, name)`` is detected and emitted as a DYNAMIC_REFERENCE
diagnostic. PreFlight does not fabricate certainty for dynamic dispatch.

Comments and string literals
-----------------------------
The parser uses the Tree-sitter AST, not regex over raw text.
Comments (``#``) are non-executable AST nodes that contain no imports or calls.
String literals are string content nodes — they do not produce symbol references
unless they appear as arguments to ``getattr()``.

Security
--------
The parser NEVER:
- imports the analyzed module
- calls eval() or exec() on any source content
- executes shell commands
- accesses the filesystem beyond the bytes provided

Determinism
-----------
All collections (symbols, references, diagnostics) are sorted before being
placed into the SourceFile model. Sort key: (line, column, text).
"""

from __future__ import annotations

import logging
from typing import Any

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

from preflight.graph.parsers.base import SourceParser
from preflight.graph.parsers.diagnostics import (
    DiagnosticCode,
    DiagnosticSeverity,
    make_diagnostic,
)
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

# Built once at module import; Tree-sitter Language objects are safe to share.
_PY_LANGUAGE = Language(tspython.language())


class PythonParser(SourceParser):
    """Tree-sitter-based Python source parser.

    Stateless and re-entrant. A single instance may parse multiple files.
    """

    def __init__(self) -> None:
        self._ts_parser = Parser(_PY_LANGUAGE)

    @property
    def language(self) -> Lang:
        return Lang.PYTHON

    def parse(
        self,
        source_bytes: bytes,
        file_path: str,
        service_name: str,
    ) -> SourceFile:
        """Parse Python source bytes and return a normalized SourceFile."""
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
                language=Lang.PYTHON,
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

        # Extract module-level symbol (one per file).
        module_symbol_id = make_symbol_id(service_name, file_path, SymbolKind.MODULE, file_path)
        symbols.append(
            Symbol(
                symbol_id=module_symbol_id,
                qualified_name=file_path,
                symbol_kind=SymbolKind.MODULE,
                location=SourceLocation(file_path=file_path, line=1, column=0),
                is_public=True,
            )
        )

        # Walk the AST for symbols and references.
        _extract_top_level(
            root, source_bytes, file_path, service_name, symbols, references, diagnostics
        )

        # Sort deterministically before freezing.
        sorted_symbols = _sort_symbols(symbols)
        sorted_references = _sort_references(references)
        sorted_diagnostics = tuple(
            sorted(diagnostics, key=lambda d: (d.line or 0, d.column or 0, d.message))
        )

        return SourceFile(
            file_path=file_path,
            language=Lang.PYTHON,
            parse_status=parse_status,
            content_hash=content_hash,
            syntax_error_count=syntax_error_count,
            symbols=sorted_symbols,
            references=sorted_references,
            diagnostics=sorted_diagnostics,
        )


# ---------------------------------------------------------------------------
# Extraction helpers — all operate on tree-sitter Node objects.
# These functions must not be called from outside this module.
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
    """Walk the top-level AST children and dispatch to extractors."""
    for child in node.named_children:
        ntype = child.type
        if ntype == "import_statement":
            _extract_import_statement(child, src, file_path, references)
        elif ntype == "import_from_statement":
            _extract_from_import(child, src, file_path, references)
        elif ntype == "future_import_statement":
            pass  # __future__ imports have no runtime dependency semantics
        elif ntype == "class_definition":
            _extract_class(child, src, file_path, service_name, symbols, references, diagnostics)
        elif ntype == "function_definition":
            _extract_function(
                child, src, file_path, service_name, symbols, references, diagnostics,
                parent_class=None,
            )
        elif ntype == "decorated_definition":
            _extract_decorated(
                child, src, file_path, service_name, symbols, references, diagnostics
            )
        elif ntype == "expression_statement":
            _extract_expression_refs(child, src, file_path, references, diagnostics)


def _extract_import_statement(
    node: Node,
    src: bytes,
    file_path: str,
    references: list[Reference],
) -> None:
    """Extract: import x, import x.y"""
    for child in node.named_children:
        if child.type in ("dotted_name", "aliased_import"):
            # Get the root module name (first dotted component)
            name_node = child if child.type == "dotted_name" else _first_named_child(child)
            if name_node is None:
                continue
            ref_text = _node_text(name_node, src)
            references.append(
                Reference(
                    reference_text=ref_text,
                    location=_loc(name_node, file_path),
                    resolution_status=ResolutionStatus.UNRESOLVED,
                    metadata={"import_kind": "import", "full_name": _node_text(name_node, src)},
                )
            )


def _extract_from_import(
    node: Node,
    src: bytes,
    file_path: str,
    references: list[Reference],
) -> None:
    """Extract: from x import y, from x.y import z, w"""
    children = node.named_children
    if not children:
        return

    # First named child is the module path
    module_node = children[0]
    module_text = _node_text(module_node, src)

    # Remaining named children are the imported names
    for name_node in children[1:]:
        if name_node.type in ("dotted_name", "wildcard_import"):
            imported_text = _node_text(name_node, src)
            # Represent as "module.Name" for resolution
            qualified = f"{module_text}.{imported_text}" if imported_text != "*" else module_text
            references.append(
                Reference(
                    reference_text=qualified,
                    location=_loc(name_node, file_path),
                    resolution_status=ResolutionStatus.UNRESOLVED,
                    metadata={
                        "import_kind": "from_import",
                        "module": module_text,
                        "name": imported_text,
                    },
                )
            )
        elif name_node.type == "aliased_import":
            # from x import y as z
            actual = _first_named_child(name_node)
            if actual:
                imported_text = _node_text(actual, src)
                qualified = f"{module_text}.{imported_text}"
                references.append(
                    Reference(
                        reference_text=qualified,
                        location=_loc(actual, file_path),
                        resolution_status=ResolutionStatus.UNRESOLVED,
                        metadata={
                            "import_kind": "from_import_aliased",
                            "module": module_text,
                            "name": imported_text,
                        },
                    )
                )


def _extract_class(
    node: Node,
    src: bytes,
    file_path: str,
    service_name: str,
    symbols: list[Symbol],
    references: list[Reference],
    diagnostics: list[Any],
    parent_class: str | None = None,
) -> None:
    """Extract a class_definition node."""
    name_node = _get_child_by_type(node, "identifier")
    if name_node is None:
        return

    class_name = _node_text(name_node, src)
    qualified = f"{parent_class}.{class_name}" if parent_class else class_name
    symbol_id = make_symbol_id(service_name, file_path, SymbolKind.CLASS, qualified)

    symbols.append(
        Symbol(
            symbol_id=symbol_id,
            qualified_name=qualified,
            symbol_kind=SymbolKind.CLASS,
            location=_loc(name_node, file_path),
            is_public=not class_name.startswith("_"),
        )
    )

    # Walk class body for methods and nested classes.
    body = _get_child_by_type(node, "block")
    if body:
        for child in body.named_children:
            if child.type == "function_definition":
                _extract_function(
                    child, src, file_path, service_name, symbols, references, diagnostics,
                    parent_class=qualified,
                )
            elif child.type == "class_definition":
                _extract_class(
                    child, src, file_path, service_name, symbols, references, diagnostics,
                    parent_class=qualified,
                )
            elif child.type == "decorated_definition":
                _extract_decorated(
                    child, src, file_path, service_name, symbols, references, diagnostics,
                    parent_class=qualified,
                )
            elif child.type == "expression_statement":
                _extract_expression_refs(child, src, file_path, references, diagnostics)


def _extract_function(
    node: Node,
    src: bytes,
    file_path: str,
    service_name: str,
    symbols: list[Symbol],
    references: list[Reference],
    diagnostics: list[Any],
    parent_class: str | None,
) -> None:
    """Extract a function_definition node (sync or async)."""
    name_node = _get_child_by_type(node, "identifier")
    if name_node is None:
        return

    func_name = _node_text(name_node, src)
    qualified = f"{parent_class}.{func_name}" if parent_class else func_name

    # Detect async by checking for an 'async' keyword child token.
    is_async = any(c.type == "async" for c in node.children)

    if parent_class:
        kind = SymbolKind.ASYNC_METHOD if is_async else SymbolKind.METHOD
    else:
        kind = SymbolKind.ASYNC_FUNCTION if is_async else SymbolKind.FUNCTION

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

    # Walk body for nested calls and references.
    body = _get_child_by_type(node, "block")
    if body:
        _extract_block_refs(body, src, file_path, references, diagnostics)


def _extract_decorated(
    node: Node,
    src: bytes,
    file_path: str,
    service_name: str,
    symbols: list[Symbol],
    references: list[Reference],
    diagnostics: list[Any],
    parent_class: str | None = None,
) -> None:
    """Extract a decorated_definition — unwrap decorators and extract the inner def."""
    for child in node.named_children:
        if child.type == "class_definition":
            _extract_class(
                child, src, file_path, service_name, symbols, references, diagnostics,
                parent_class=parent_class,
            )
        elif child.type == "function_definition":
            _extract_function(
                child, src, file_path, service_name, symbols, references, diagnostics,
                parent_class=parent_class,
            )


def _extract_expression_refs(
    node: Node,
    src: bytes,
    file_path: str,
    references: list[Reference],
    diagnostics: list[Any],
) -> None:
    """Extract call references from an expression_statement."""
    for child in node.children:
        if child.type in ("call", "assignment"):
            _extract_call_refs(child, src, file_path, references, diagnostics)


def _extract_block_refs(
    node: Node,
    src: bytes,
    file_path: str,
    references: list[Reference],
    diagnostics: list[Any],
) -> None:
    """Recursively extract references from a block node."""
    for child in node.named_children:
        ntype = child.type
        if ntype == "expression_statement":
            _extract_expression_refs(child, src, file_path, references, diagnostics)
        elif ntype in ("return_statement", "assignment", "augmented_assignment"):
            # Recurse into sub-expressions for calls
            _extract_call_refs(child, src, file_path, references, diagnostics)
        elif ntype in ("if_statement", "for_statement", "while_statement", "with_statement"):
            for sub in child.named_children:
                if sub.type == "block":
                    _extract_block_refs(sub, src, file_path, references, diagnostics)


def _extract_call_refs(
    node: Node,
    src: bytes,
    file_path: str,
    references: list[Reference],
    diagnostics: list[Any],
) -> None:
    """Extract references from a call or assignment node (recursive).

    Handles chained calls: ``getattr(obj, 'x')()`` — the outer call's
    function node is itself a call whose innermost function is 'getattr'.
    We recursively unwrap the function position to find dynamic patterns.
    """
    if node.type == "call":
        func_node = node.children[0] if node.children else None
        if func_node is None:
            return

        # Resolve the innermost callable name for dynamic-dispatch detection.
        # For chained calls like ``getattr(obj,'x')()`` the func_node is
        # itself a ``call`` node; unwrap recursively to get the leaf name.
        leaf_func_text = _resolve_leaf_call_name(func_node, src)

        # Detect getattr() — dynamic reference pattern.
        if leaf_func_text == "getattr":
            diagnostics.append(
                make_diagnostic(
                    DiagnosticCode.DYNAMIC_REFERENCE,
                    (
                        f"getattr() call at line {node.start_point[0] + 1} cannot be "
                        "statically resolved. Dynamic dispatch is not analyzed."
                    ),
                    file_path,
                    line=node.start_point[0] + 1,
                    column=node.start_point[1],
                )
            )
            return

        # Detect globals()/locals()/vars() — dynamic namespace access.
        if leaf_func_text in ("globals", "locals", "vars"):
            diagnostics.append(
                make_diagnostic(
                    DiagnosticCode.DYNAMIC_REFERENCE,
                    (
                        f"{leaf_func_text}() at line {node.start_point[0] + 1} "
                        "is a dynamic namespace access."
                    ),
                    file_path,
                    line=node.start_point[0] + 1,
                    column=node.start_point[1],
                )
            )
            # Still recurse into the inner call's arguments.
            args_node = _get_child_by_type(node, "argument_list")
            if args_node:
                for arg in args_node.named_children:
                    _extract_call_refs(arg, src, file_path, references, diagnostics)
            return

        # If the func_node is itself a call (chained), recurse into it first
        # to catch any inner dynamic patterns before recording the outer call.
        if func_node.type == "call":
            _extract_call_refs(func_node, src, file_path, references, diagnostics)
            return

        func_text = _node_text(func_node, src)

        # Record the call as a reference.
        references.append(
            Reference(
                reference_text=func_text,
                location=_loc(func_node, file_path),
                resolution_status=ResolutionStatus.UNRESOLVED,
                metadata={"reference_kind": "call"},
            )
        )

        # Recurse into arguments.
        args_node = _get_child_by_type(node, "argument_list")
        if args_node:
            for arg in args_node.named_children:
                _extract_call_refs(arg, src, file_path, references, diagnostics)

    elif node.type == "assignment":
        # Recurse into the right-hand side.
        children = node.named_children
        if len(children) >= 2:
            _extract_call_refs(children[-1], src, file_path, references, diagnostics)

    elif node.type == "return_statement":
        for child in node.named_children:
            _extract_call_refs(child, src, file_path, references, diagnostics)

    elif node.type == "subscript":
        # e.g. globals()['KEY'] — recurse into the subscripted expression.
        for child in node.named_children:
            _extract_call_refs(child, src, file_path, references, diagnostics)


def _resolve_leaf_call_name(node: Node, src: bytes) -> str:
    """Recursively unwrap chained call nodes to find the innermost function name.

    For ``getattr(obj, 'x')()``:
      outer call → func_node = call(getattr, args)
      inner call → func_node = identifier 'getattr'

    Returns the text of the innermost callable identifier.
    """
    if node.type == "call":
        inner_func = node.children[0] if node.children else None
        if inner_func is not None:
            return _resolve_leaf_call_name(inner_func, src)
    return _node_text(node, src)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _node_text(node: Node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _loc(node: Node, file_path: str) -> SourceLocation:
    # tree-sitter uses 0-based rows; we use 1-based lines.
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


def _first_named_child(node: Node) -> Node | None:
    for child in node.named_children:
        return child
    return None


def _count_error_nodes(node: Node) -> int:
    count = 1 if node.is_error or node.type == "ERROR" else 0
    for child in node.children:
        count += _count_error_nodes(child)
    return count


def _sort_symbols(symbols: list[Symbol]) -> tuple[Symbol, ...]:
    return tuple(
        sorted(symbols, key=lambda s: (s.location.line, s.location.column, s.qualified_name))
    )


def _sort_references(references: list[Reference]) -> tuple[Reference, ...]:
    return tuple(
        sorted(
            references,
            key=lambda r: (r.location.line, r.location.column, r.reference_text),
        )
    )
