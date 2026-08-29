"""Fixture loader layer.

Provides programmatic access to the demo fixture definitions.
The fixture definitions are the source of truth for the canonical
Day 1 dependency graph; they are not parsed from the fixture source files.

Day 2 will introduce Tree-sitter parsing that derives entity/edge
definitions directly from fixture source code. The loader interface
is designed to remain stable when that transition happens.
"""
