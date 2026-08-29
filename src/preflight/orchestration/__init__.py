"""Orchestration boundary: composes the real analyzers into one pipeline.

``run_analysis`` (a registered fixture scenario), ``run_project_analysis``
(a single already-extracted uploaded project), and
``run_snapshot_comparison`` (two already-extracted snapshots — the real
``ChangeSet``/OLD-vs-NEW entry point) are the three supported entry points.
All three produce a complete, deterministic
:class:`~preflight.orchestration.models.AnalysisRunResult` composed from the
same underlying analyzers. See ``pipeline.py`` for the full contract.
"""

from __future__ import annotations

from preflight.orchestration.errors import (
    FixtureUnavailableError,
    OrchestrationError,
    UnknownScenarioError,
)
from preflight.orchestration.models import AnalysisInput, AnalysisRunResult, ScenarioConfig
from preflight.orchestration.pipeline import (
    SCENARIOS,
    run_analysis,
    run_project_analysis,
    run_snapshot_comparison,
)

__all__ = [
    "SCENARIOS",
    "AnalysisInput",
    "AnalysisRunResult",
    "FixtureUnavailableError",
    "OrchestrationError",
    "ScenarioConfig",
    "UnknownScenarioError",
    "run_analysis",
    "run_project_analysis",
    "run_snapshot_comparison",
]
