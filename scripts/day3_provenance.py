#!/usr/bin/env python3
"""Print one source-backed Day 3 semantic edge and its provenance."""

from __future__ import annotations

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))

from preflight.semantic import SemanticAnalyzer  # noqa: E402

result = SemanticAnalyzer().analyze(repo_root / "fixtures" / "demo-commerce")
edge = next(
    edge
    for edge in result.edges
    if edge.source == "user-service.UserService"
    and edge.target == "profile-api.ProfileAPI"
)
evidence = edge.evidence[0]
print(f"EDGE: {edge.source} -> {edge.target}")
print(f"KIND: {edge.kind.value}")
print(f"METHOD: {evidence.matched_pattern}")
print(f"ROUTE: {evidence.extracted_value}")
print(f"SOURCE: {evidence.source_file}")
print(f"LINE: {evidence.line}")
print(f"SYNTAX: {evidence.syntax_kind}")
print(f"RESOLUTION: {evidence.resolution_rule}")
