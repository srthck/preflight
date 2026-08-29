"""Analysis report domain model.

AnalysisReport is the top-level output contract for PreFlight.
Day 1 populates the structural fields; risk scoring and AI explanation
fields are intentionally absent and will be added by the risk engine
on Day 9 without breaking this schema.

Schema versioning
-----------------
``schema_version`` uses MAJOR.MINOR semantics:
* Increment MINOR for backward-compatible additions.
* Increment MAJOR for breaking structural changes.
Current: "1.0"
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from preflight.domain.entities import Entity
from preflight.domain.graph_models import DependencyEdge, DependencyPath

# The canonical schema version for Day 1 reports.
SCHEMA_VERSION = "1.0"


class ReportMetadata(BaseModel):
    """Non-analytical metadata attached to an AnalysisReport.

    Intentionally excludes wall-clock timestamps because PreFlight output
    must be deterministic. Callers may attach a timestamp externally if
    they need to record *when* an analysis was run, but it must not be
    part of canonical output.

    See docs/DETERMINISM.md.
    """

    model_config = {"frozen": True}

    source_fixture: str = Field(
        ...,
        description="Identifier of the fixture or repository that was analysed.",
        min_length=1,
    )
    analysis_version: str = Field(
        default="0.1.0",
        description="Version of the PreFlight analysis engine that produced this report.",
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Human-readable notes about this report (limitations, caveats, etc.).",
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Reserved for future structured extension without schema breakage.",
    )


class AnalysisReport(BaseModel):
    """Top-level output of a PreFlight analysis run.

    Day 1 fields
    ------------
    schema_version  — must match SCHEMA_VERSION constant.
    target          — the entity_id under analysis (the changed entity).
    entities        — all entities discovered in the analysis scope.
    edges           — all dependency edges in the analysis scope.
    paths           — downstream dependency paths from ``target``.
    metadata        — non-analytical report metadata.

    Future fields (Day 9+)
    ----------------------
    risk_score, verdict, explanation — added by the risk engine module.
    These will be optional fields so existing consumers remain valid.
    """

    model_config = {"frozen": True}

    schema_version: str = Field(
        default=SCHEMA_VERSION,
        description="Report schema version. See SCHEMA_VERSION constant.",
    )
    target: str = Field(
        ...,
        description="entity_id of the entity under analysis (the changed artifact).",
        min_length=1,
    )
    entities: tuple[Entity, ...] = Field(
        ...,
        description="All entities in the analysis scope, ordered by entity_id.",
    )
    edges: tuple[DependencyEdge, ...] = Field(
        ...,
        description="All dependency edges in the analysis scope.",
    )
    paths: tuple[DependencyPath, ...] = Field(
        ...,
        description="Downstream dependency paths from ``target``.",
    )
    metadata: ReportMetadata = Field(
        ...,
        description="Non-analytical metadata for this report.",
    )
