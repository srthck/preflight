"""Orchestration-layer data contracts.

These types describe the *pipeline's* inputs and outputs. They intentionally
do not redefine any analyzer's domain model (``NormalizedFinding``,
``BlastRadiusReport``, ``RollbackReport``, ...); they only compose them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from preflight.api_contract import APIContractFinding
from preflight.decision import DecisionReport
from preflight.domain.blast_radius import BlastRadiusReport
from preflight.domain.change_set import ChangeSet
from preflight.explanation import ExplanationResult
from preflight.graph.builder import PreFlightGraph
from preflight.ingestion.models import ProjectManifest
from preflight.rollback_truth import RollbackReport
from preflight.schema import DeploymentFinding, SchemaChange, SchemaModel
from preflight.semantic import SemanticAnalysisResult
from preflight.structural_diff import StructuralDiff


@dataclass(frozen=True)
class ScenarioConfig:
    """Fixture *inputs* selected by a scenario name.

    A scenario never selects an expected output — only which real files the
    pipeline reads. Paths are relative to the repository root.
    """

    name: str
    fixture_root: Path
    migration_path: Path
    api_contract_path: Path
    schema_path: Path


@dataclass(frozen=True)
class AnalysisInput:
    """One HTTP-level request to the orchestrator."""

    case_id: str
    scenario: str


@dataclass(frozen=True)
class AnalysisRunResult:
    """Everything produced by one real, end-to-end orchestration run."""

    case_id: str
    scenario: str
    semantic: SemanticAnalysisResult
    graph: PreFlightGraph
    changed_entity: str
    deployment_finding: DeploymentFinding
    blast_radius: BlastRadiusReport
    api_contract: APIContractFinding | None
    rollback: RollbackReport
    decision: DecisionReport
    explanation: ExplanationResult
    old_schema: SchemaModel | None = None
    new_schema: SchemaModel | None = None
    manifest: ProjectManifest | None = None
    capabilities: dict[str, dict[str, str]] = field(default_factory=dict)
    unavailable_components: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)
    change_set: ChangeSet | None = None
    deployment_findings: tuple[DeploymentFinding, ...] = field(default_factory=tuple)
    convergent_entities: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    schema_changes: tuple[SchemaChange, ...] = field(default_factory=tuple)
    blast_radius_targets: tuple[str, ...] = field(default_factory=tuple)
    structural_diff: StructuralDiff | None = None

    def to_response_payload(self) -> dict[str, Any]:
        """Serialize into the HTTP response contract served by ``/api/analyze``.

        Field names/shapes under ``decision_report``, ``explanation``, and
        ``graph`` are preserved exactly for the existing frontend contract
        (see ``frontend/lib/api.ts``); the additional top-level keys
        (``analysis``, ``blast_radius``, ``deployment``, ``api_contract``,
        ``rollback``, ``deterministic_hash``, ``ai_available``) are additive.
        """
        from preflight.evidence_graph import build_evidence_graph
        from preflight.graph.serialization import canonical_sha256
        from preflight.graph.traversal import find_downstream_paths

        paths = (
            find_downstream_paths(self.graph, self.changed_entity)
            if self.changed_entity in self.graph.entity_ids
            else []
        )
        graph_payload = {
            "entities": [
                self.graph.get_entity(entity_id).model_dump(mode="json")
                for entity_id in self.graph.entity_ids
            ],
            "edges": [edge.model_dump(mode="json") for edge in self.graph.get_dependencies()],
            "paths": [
                {
                    "nodes": list(path.nodes),
                    "edges": [edge.value for edge in path.edges],
                    "hop_count": path.hop_count,
                }
                for path in paths
            ],
            "graph_hash": canonical_sha256(self.graph),
        }
        return {
            "case_id": self.case_id,
            "scenario": self.scenario,
            "decision_report": self.decision.model_dump(mode="json"),
            "explanation": self.explanation.model_dump(mode="json"),
            "graph": graph_payload,
            "blast_radius": self.blast_radius.model_dump(mode="json"),
            "deployment": self.deployment_finding.model_dump(mode="json"),
            "api_contract": self.api_contract.model_dump(mode="json")
            if self.api_contract is not None
            else None,
            "rollback": self.rollback.model_dump(mode="json"),
            "analysis": {
                "changed_entity": self.changed_entity,
                "semantic_diagnostics": list(self.semantic.diagnostics),
                "semantic_edge_counts": self.semantic.semantic_counts(),
                "unavailable_components": list(self.unavailable_components),
                "notes": list(self.notes),
            },
            "capabilities": self.capabilities,
            "schema": {
                "old": self.old_schema.model_dump(mode="json") if self.old_schema else None,
                "new": self.new_schema.model_dump(mode="json") if self.new_schema else None,
                "diff": _schema_diff(self.old_schema, self.new_schema),
            },
            "ai_available": self.explanation.quality.value == "FULL_AI",
            "deterministic_hash": self.decision.deterministic_hash,
            "project_manifest": (
                self.manifest.model_dump(mode="json") if self.manifest is not None else None
            ),
            "change_set": (
                self.change_set.model_dump(mode="json") if self.change_set is not None else None
            ),
            "deployment_findings": [
                f.model_dump(mode="json") for f in self.deployment_findings
            ],
            "convergence": list(self.convergent_entities),
            # Materialized causal graph: a pure projection of the evidence
            # above, so the frontend never has to reverse-engineer the chain
            # from change to verdict (see preflight/evidence_graph.py).
            "evidence_graph": build_evidence_graph(self).model_dump(mode="json"),
            # Every individual schema change the migration contains, each with
            # its own resolved target — never collapsed to a single "primary"
            # change, so a two-statement migration is visibly two changes.
            "schema_changes": [
                {
                    "kind": change.kind.value,
                    "table": change.table,
                    "object_name": change.object_name,
                    "schema_object": change.schema_object,
                    "category": change.category.value,
                    "severity": change.severity.value,
                    "reason": change.reason,
                    "resolved_as_blast_target": change.schema_object in self.blast_radius_targets,
                }
                for change in self.schema_changes
            ],
            "blast_radius_targets": list(self.blast_radius_targets),
            # Parser-established declaration changes. Null for single-repository
            # analyses, where there is no second snapshot to compare against.
            "structural_diff": (
                self.structural_diff.model_dump(mode="json")
                if self.structural_diff is not None
                else None
            ),
        }


def _schema_diff(
    old_schema: SchemaModel | None, new_schema: SchemaModel | None
) -> list[dict[str, Any]]:
    """Column-level ADDED/REMOVED/CHANGED/UNCHANGED diff between two real schema snapshots.

    Pure presentation transform over already-computed ``SchemaModel`` data —
    it does not classify severity or decide safety; that remains
    ``DeploymentAnalyzer``'s and ``decide()``'s job.
    """
    if old_schema is None or new_schema is None:
        return []
    rows: list[dict[str, Any]] = []
    old_tables = {table.name: table for table in old_schema.tables}
    new_tables = {table.name: table for table in new_schema.tables}
    for table_name in sorted(set(old_tables) | set(new_tables)):
        old_table = old_tables.get(table_name)
        new_table = new_tables.get(table_name)
        old_columns = {c.name: c for c in (old_table.columns if old_table else ())}
        new_columns = {c.name: c for c in (new_table.columns if new_table else ())}
        for column_name in sorted(set(old_columns) | set(new_columns)):
            old_column = old_columns.get(column_name)
            new_column = new_columns.get(column_name)
            if old_column is None:
                status = "ADDED"
            elif new_column is None:
                status = "REMOVED"
            elif old_column.model_dump() != new_column.model_dump():
                status = "CHANGED"
            else:
                status = "UNCHANGED"
            rows.append(
                {
                    "table": table_name,
                    "column": column_name,
                    "status": status,
                    "before": old_column.model_dump(mode="json") if old_column else None,
                    "after": new_column.model_dump(mode="json") if new_column else None,
                }
            )
    return rows


__all__ = ["AnalysisInput", "AnalysisRunResult", "ScenarioConfig"]
