"""Orchestration-layer errors.

These are the only exceptions ``run_analysis`` raises. Every other failure
mode (a missing migration file, a malformed contract, an analyzer that has
nothing to say) is represented as structured, deterministic output — an
``UNKNOWN``/``ANALYSIS_UNAVAILABLE`` finding feeding the existing decision
engine — rather than an exception. These two exceptions exist only for
requests that cannot be analyzed at all: an unrecognized scenario, or a
fixture root that does not exist on disk.
"""

from __future__ import annotations

from preflight.domain.errors import PreFlightError


class OrchestrationError(PreFlightError):
    """Base class for orchestration-boundary failures."""


class UnknownScenarioError(OrchestrationError):
    """Raised when the requested scenario is not registered."""

    def __init__(self, scenario: str) -> None:
        super().__init__(f"Unsupported scenario: {scenario!r}")
        self.scenario = scenario


class FixtureUnavailableError(OrchestrationError):
    """Raised when the scenario's fixture root does not exist on disk."""

    def __init__(self, path: str) -> None:
        super().__init__(f"Fixture root does not exist: {path}")
        self.path = path


__all__ = ["FixtureUnavailableError", "OrchestrationError", "UnknownScenarioError"]
