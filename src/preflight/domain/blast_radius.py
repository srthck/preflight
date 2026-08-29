"""Immutable domain models for deterministic blast-radius analysis."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from preflight.domain.enums import EdgeKind


class ImpactCategory(str, Enum):
    """Deterministic impact classification."""

    DIRECT = "DIRECT"
    INDIRECT = "INDIRECT"


class BlastRadiusRequest(BaseModel):
    """Parameters for one bounded downstream impact analysis."""

    model_config = {"frozen": True}

    target: str = Field(..., min_length=1)
    max_hops: int = Field(default=3, ge=1)
    max_paths: int = Field(default=100, ge=1)


class ImpactPath(BaseModel):
    """A causal path from the changed entity to one affected entity."""

    model_config = {"frozen": True}

    nodes: tuple[str, ...] = Field(..., min_length=2)
    edge_types: tuple[EdgeKind, ...]
    evidence: tuple[dict[str, Any], ...] = ()

    @model_validator(mode="after")
    def edge_count_matches_path(self) -> ImpactPath:
        if len(self.edge_types) != len(self.nodes) - 1:
            raise ValueError("edge_types must contain one value per path hop")
        return self


class BlastRadiusFinding(BaseModel):
    """One ranked affected-entity finding with its causal explanation."""

    model_config = {"frozen": True}

    target: str
    affected_entity: str
    severity: float = Field(..., ge=0.0, le=1.0)
    hop_distance: int = Field(..., ge=1)
    category: ImpactCategory
    path: ImpactPath
    reason: str = Field(..., min_length=1)


class ImpactSummary(BaseModel):
    """Stable aggregate counts for a blast-radius report."""

    model_config = {"frozen": True}

    direct_count: int = Field(..., ge=0)
    indirect_count: int = Field(..., ge=0)
    affected_count: int = Field(..., ge=0)


class BlastRadiusReport(BaseModel):
    """Complete deterministic blast-radius result."""

    model_config = {"frozen": True}

    target: str
    max_hops: int
    max_paths: int
    findings: tuple[BlastRadiusFinding, ...]
    summary: ImpactSummary
    confidence_note: str = "Confidence not yet modeled."
