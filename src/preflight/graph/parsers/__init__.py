"""Parser layer — Tree-sitter-based source analysis.

This package wraps Tree-sitter as an implementation detail.
Nothing outside this package should depend on Tree-sitter node objects.
All output is expressed in terms of models defined in ``models.py``.

Public surface
--------------
models      — immutable extraction models (SourceFile, Symbol, Reference, etc.)
registry    — language registry mapping file extensions to parsers
extractor   — SourceExtractor: orchestrates discovery → parse → extract → resolve
diagnostics — DiagnosticCode, Diagnostic, DiagnosticSeverity
"""
