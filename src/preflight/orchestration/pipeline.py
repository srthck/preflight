"""The real PreFlight orchestration pipeline.

``run_analysis`` (built-in fixture scenarios) and ``run_project_analysis``
(an arbitrary uploaded/extracted project) are the two entry points. Both
resolve their real input files differently and then call the same private
``_execute_pipeline`` — there is exactly one analysis pipeline, not two. It
composes the existing, independently-tested analyzers; it does not
reimplement any of their logic:

    SemanticAnalyzer -> BlastRadiusEngine -> DeploymentAnalyzer
        -> analyze_api_contract -> analyze_rollback -> decide -> explain

A scenario name selects which real fixture *files* are read
(:class:`~preflight.orchestration.models.ScenarioConfig`); for an uploaded
project, :mod:`preflight.ingestion.discovery` locates those same kinds of
files by inspecting the real extracted tree. Either way, every value in the
returned :class:`~preflight.orchestration.models.AnalysisRunResult` is
computed by an analyzer from those files, never hand-encoded here.

Missing or malformed evidence does not raise: it is threaded through as an
``unavailable_components`` entry or handled by the analyzer's own graceful
path (e.g. ``DeploymentAnalyzer`` already returns a structured
``PARSE_ERROR`` finding for malformed SQL), so ``decide()`` — the single
authority on risk and verdict — can correctly resolve it to ``UNKNOWN``. The
only exceptions this module raises are for requests that cannot be analyzed
at all: an unregistered scenario, or a fixture root missing from disk.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from preflight.api_contract import APIContractFinding, analyze_api_contract, parse_openapi_document
from preflight.blast_radius import BlastRadiusEngine
from preflight.decision import DecisionRequest, decide
from preflight.domain.blast_radius import (
    BlastRadiusReport,
    BlastRadiusRequest,
    ImpactCategory,
    ImpactSummary,
)
from preflight.domain.enums import EdgeKind
from preflight.explanation import explain
from preflight.graph.builder import PreFlightGraph
from preflight.ingestion.models import ProjectManifest
from preflight.orchestration.errors import FixtureUnavailableError, UnknownScenarioError
from preflight.orchestration.models import AnalysisInput, AnalysisRunResult, ScenarioConfig
from preflight.rollback_truth import (
    ApplicationSnapshot,
    RollbackRequest,
    RollbackWindow,
    analyze_rollback,
)
from preflight.schema import (
    DeploymentAnalyzer,
    DeploymentFinding,
    SchemaChange,
    SchemaModel,
    apply_schema_migration,
    parse_migration_sql,
    parse_schema_sql,
)
from preflight.semantic import SemanticAnalysisResult, SemanticAnalyzer

_REPO_ROOT = Path(__file__).resolve().parents[3]

SCENARIOS: dict[str, ScenarioConfig] = {
    "demo-commerce-phone-number-removal": ScenarioConfig(
        name="demo-commerce-phone-number-removal",
        fixture_root=Path("fixtures/demo-commerce"),
        migration_path=Path("fixtures/demo-commerce/database/migration.sql"),
        schema_path=Path("fixtures/demo-commerce/database/schema.sql"),
        api_contract_path=Path("fixtures/demo-commerce/profile-api/openapi.yaml"),
    ),
    "demo-commerce-phone-verified-addition": ScenarioConfig(
        name="demo-commerce-phone-verified-addition",
        fixture_root=Path("fixtures/demo-commerce"),
        migration_path=Path("fixtures/demo-commerce/database/migration_safe.sql"),
        schema_path=Path("fixtures/demo-commerce/database/schema.sql"),
        api_contract_path=Path("fixtures/demo-commerce/profile-api/openapi.yaml"),
    ),
}


def run_analysis(
    request: AnalysisInput,
    *,
    repo_root: Path | None = None,
    scenarios: dict[str, ScenarioConfig] | None = None,
) -> AnalysisRunResult:
    """Run the real end-to-end analysis for one registered fixture scenario."""

    root = repo_root or _REPO_ROOT
    registry = scenarios if scenarios is not None else SCENARIOS
    config = registry.get(request.scenario)
    if config is None:
        raise UnknownScenarioError(request.scenario)

    fixture_root = root / config.fixture_root
    if not fixture_root.exists():
        raise FixtureUnavailableError(str(fixture_root))

    return _execute_pipeline(
        case_id=request.case_id,
        scenario=request.scenario,
        project_root=fixture_root,
        display_root=config.fixture_root.as_posix(),
        migration_path=root / config.migration_path,
        schema_path=root / config.schema_path,
        api_contract_path=root / config.api_contract_path,
        semantic_files=None,
        version_label="fixture-current",
    )


def run_project_analysis(
    project_root: Path,
    *,
    case_id: str,
    scenario_label: str = "uploaded-project",
) -> AnalysisRunResult:
    """Run the same real pipeline against an arbitrary, already-extracted project.

    This is the uploaded-project entry point. It performs zero analysis of
    its own: :mod:`preflight.ingestion.discovery` locates the real schema,
    migration, API contract, and semantic source files inside
    ``project_root``, and everything downstream is the identical
    ``_execute_pipeline`` call :func:`run_analysis` uses for the built-in
    fixture scenarios. Nothing branches on ``scenario_label`` — it is
    carried through only as response metadata.
    """
    from preflight.ingestion import discovery
    from preflight.ingestion.manifest import build_manifest

    # SemanticAnalyzer's explicit-file-list mode treats non-absolute entries
    # as relative to its root argument; resolving here keeps root and the
    # discovered file list unambiguously absolute regardless of the caller's
    # cwd or how project_root was constructed.
    project_root = project_root.resolve()
    manifest = build_manifest(project_root)
    schema_path, migration_path, discovery_notes = discovery.find_schema_and_migration(project_root)
    api_contract_path = discovery.find_api_contract(project_root)
    semantic_files = discovery.find_semantic_files(project_root)

    return _execute_pipeline(
        case_id=case_id,
        scenario=scenario_label,
        project_root=project_root,
        display_root="the uploaded project",
        migration_path=migration_path,
        schema_path=schema_path,
        api_contract_path=api_contract_path,
        semantic_files=semantic_files,
        version_label="uploaded-project",
        extra_notes=discovery_notes,
        manifest=manifest,
    )


def run_snapshot_comparison(
    old_root: Path,
    new_root: Path,
    *,
    case_id: str,
    old_label: str = "OLD",
    new_label: str = "NEW",
) -> AnalysisRunResult:
    """Compare two extracted repository snapshots and analyze what changed.

    This is the ``ChangeSet``/``SNAPSHOT_PAIR`` entry point: "here is what
    is currently deployed, here is what is proposed." It reuses the exact
    same analyzers as :func:`run_project_analysis` (``SemanticAnalyzer``,
    ``DeploymentAnalyzer``, ``BlastRadiusEngine``, ``analyze_api_contract``,
    ``analyze_rollback``, ``decide``, ``explain``) — none are reimplemented
    — but the control flow genuinely differs from :func:`_execute_pipeline`,
    because a snapshot pair can produce *multiple* independent blast-radius
    targets (a changed schema object and/or a breaking API route) where a
    single upload only ever has one.

    Blast radius is traversed over ``old_root``'s dependency graph — the
    consumers of the changed entity that are actually running today — not
    ``new_root``'s, so a change that also deletes its own last consumer in
    the new code cannot make its production blast radius disappear.
    """
    from preflight.diffing import build_change_set, compare_repositories
    from preflight.ingestion import discovery
    from preflight.ingestion.manifest import build_manifest
    from preflight.structural_diff import compare_source_structure

    old_root = old_root.resolve()
    new_root = new_root.resolve()

    diff = compare_repositories(old_root, new_root, old_label=old_label, new_label=new_label)
    change_set = build_change_set(diff)
    manifest = build_manifest(new_root)
    # Syntax-aware structural comparison (declared symbols, not text lines).
    # Reuses the existing Tree-sitter extractor; makes no claim about a file
    # it could not parse on both sides.
    structural = compare_source_structure(old_root, new_root)

    unavailable: list[str] = []
    notes: list[str] = [
        f"{len(diff.changed_files)} file(s) changed between {old_label} and {new_label} "
        f"({diff.added_count} added, {diff.removed_count} removed, {diff.modified_count} modified)."
    ]

    old_semantic = SemanticAnalyzer().analyze(
        old_root, files=discovery.find_semantic_files(old_root)
    )
    new_semantic = SemanticAnalyzer().analyze(
        new_root, files=discovery.find_semantic_files(new_root)
    )
    old_graph, new_graph = old_semantic.graph, new_semantic.graph
    if new_graph.node_count == 0:
        unavailable.append("semantic_analysis")
        notes.append(f"No supported source files were discovered in {new_label}.")

    _, new_migration_path, migration_notes = discovery.find_schema_and_migration(new_root)
    notes.extend(migration_notes)
    migration_sql, migration_note = _read_optional(new_migration_path)
    if migration_note:
        notes.append(migration_note)
    if new_migration_path is None:
        unavailable.append("deployment_rehearsal")

    deployment_finding = DeploymentAnalyzer(graph=old_graph).analyze(migration_sql or "")
    changed_entity = deployment_finding.schema_object or "UNKNOWN"
    has_real_schema_target = (
        new_migration_path is not None
        and deployment_finding.change not in {"PARSE_ERROR", "NO_CHANGE"}
        and deployment_finding.schema_object not in (None, "UNKNOWN")
    )

    # The checked-in schema.sql is a baseline snapshot, not a live post-migration
    # state — repositories do not typically rewrite it when a migration is
    # added. The real NEW schema is therefore the OLD schema with the NEW
    # migration applied on top, exactly as the single-repository pipeline
    # already computes it (see ``_schema_snapshots``) — reused here rather
    # than re-diffing two possibly-identical schema.sql files, which would
    # silently miss the destructive change entirely.
    old_schema_path, _, _ = discovery.find_schema_and_migration(old_root)
    new_schema_path, _, _ = discovery.find_schema_and_migration(new_root)
    schema_path = old_schema_path or new_schema_path
    old_schema, new_schema = _schema_snapshots(schema_path, migration_sql)
    if old_schema is None:
        unavailable.append("schema_snapshot")
        notes.append(
            f"No schema.sql was found on either side ({old_label}/{new_label}); "
            "schema evidence is unavailable."
        )

    old_api_path = discovery.find_api_contract(old_root)
    new_api_path = discovery.find_api_contract(new_root)
    api_contract_finding: APIContractFinding | None = None
    api_contract_parse_error = False
    if old_api_path is not None and new_api_path is not None:
        try:
            api_contract_finding = analyze_api_contract(old_api_path, new_api_path)
        except (yaml.YAMLError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
            api_contract_parse_error = True
            unavailable.append("api_contract")
            notes.append(
                f"API contract could not be parsed ({type(exc).__name__}); evidence is unavailable."
            )
    else:
        unavailable.append("api_contract")
        notes.append(
            f"An API contract was not found on both sides ({old_label}/{new_label}); "
            "API-diff evidence is unavailable."
        )

    # Multi-target resolution: EVERY schema object the migration touches (a
    # migration with two DROP COLUMN statements is two independent changes,
    # not one — see parse_migration_sql), plus every breaking API route
    # resolved to its real consuming entity via the OLD side's own route
    # registry. A target with no matching graph entity contributes nothing —
    # it is never invented.
    targets: set[str] = set()
    schema_changes: tuple[SchemaChange, ...] = ()
    if migration_sql:
        parsed_migration = parse_migration_sql(migration_sql)
        if parsed_migration.kind != "error":
            schema_changes = parsed_migration.changes
            for change in schema_changes:
                schema_object = change.schema_object
                if schema_object and schema_object in old_graph.entity_ids:
                    targets.add(schema_object)
    if has_real_schema_target and changed_entity in old_graph.entity_ids:
        targets.add(changed_entity)
    route_lookup = {
        (method, route): entity_id
        for _, method, route, entity_id in old_semantic.route_registry.entries
    }
    if api_contract_finding is not None:
        for api_change in api_contract_finding.breaking_changes:
            entity_id = route_lookup.get((api_change.method, api_change.path))
            if entity_id is not None and entity_id in old_graph.entity_ids:
                targets.add(entity_id)

    blast_radius_analyzed = bool(targets) and old_graph.node_count > 0
    if not blast_radius_analyzed:
        unavailable.append("blast_radius")

    per_target_reports = (
        [
            BlastRadiusEngine().analyze(old_graph, BlastRadiusRequest(target=t))
            for t in sorted(targets)
        ]
        if blast_radius_analyzed
        else []
    )
    fallback_target = changed_entity if changed_entity != "UNKNOWN" else "UNKNOWN"
    blast_radius = (
        _merge_blast_radius(per_target_reports, targets)
        if per_target_reports
        else _empty_blast_radius(fallback_target)
    )
    convergence = _detect_convergence(per_target_reports)

    old_application = _derive_application_snapshot(old_semantic, version=old_label)
    rollback_report = analyze_rollback(
        RollbackRequest(
            old_application=old_application,
            old_schema=old_schema,
            new_schema=new_schema,
            old_api=parse_openapi_document(old_api_path) if old_api_path is not None else None,
            new_api=parse_openapi_document(new_api_path) if new_api_path is not None else None,
            migration_findings=(deployment_finding,),
            graph=new_graph,
            deployment_context=RollbackWindow(enabled=True, rollback_versions=(old_label,)),
        )
    )

    deployment_findings_for_decision = () if new_migration_path is None else (deployment_finding,)
    decision_report = decide(
        DecisionRequest(
            blast_radius=blast_radius,
            deployment_findings=deployment_findings_for_decision,
            api_contract=api_contract_finding,
            rollback=rollback_report,
            unavailable_components=tuple(unavailable),
        )
    )
    explanation_result = explain(decision_report)

    capabilities = _capability_matrix(
        graph=new_graph,
        manifest=manifest,
        migration_path=new_migration_path,
        deployment_finding=deployment_finding,
        blast_radius_analyzed=blast_radius_analyzed,
        has_real_target=bool(targets),
        changed_entity=changed_entity,
        blast_radius_affected=blast_radius.summary.affected_count,
        api_contract_finding=api_contract_finding,
        api_contract_parse_error=api_contract_parse_error,
        rollback_status=rollback_report.status.value,
    )

    return AnalysisRunResult(
        case_id=case_id,
        scenario="snapshot-pair",
        semantic=new_semantic,
        graph=new_graph,
        changed_entity=changed_entity,
        deployment_finding=deployment_finding,
        blast_radius=blast_radius,
        api_contract=api_contract_finding,
        rollback=rollback_report,
        decision=decision_report,
        explanation=explanation_result,
        old_schema=old_schema,
        new_schema=new_schema,
        manifest=manifest,
        capabilities=capabilities,
        unavailable_components=tuple(unavailable),
        notes=tuple(notes),
        change_set=change_set,
        deployment_findings=deployment_findings_for_decision,
        convergent_entities=convergence,
        schema_changes=schema_changes,
        blast_radius_targets=tuple(sorted(targets)),
        structural_diff=structural,
    )


def _merge_blast_radius(reports: list[BlastRadiusReport], targets: set[str]) -> BlastRadiusReport:
    """Combine independent single-target traversals into one report.

    Pure composition over ``BlastRadiusEngine``'s own outputs — no new
    traversal logic. ``affected_count`` is the count of *distinct* affected
    entities across all targets (an entity reached from two targets is one
    affected entity, not two); ``direct_count``/``indirect_count`` are
    per-finding subtotals and may therefore exceed ``affected_count`` when a
    convergent entity is reached at more than one hop distance from
    different targets — this is documented, not hidden.
    """
    all_findings = tuple(finding for report in reports for finding in report.findings)
    affected = {finding.affected_entity for finding in all_findings}
    direct = sum(1 for finding in all_findings if finding.category == ImpactCategory.DIRECT)
    indirect = sum(1 for finding in all_findings if finding.category == ImpactCategory.INDIRECT)
    summary = ImpactSummary(
        direct_count=direct, indirect_count=indirect, affected_count=len(affected)
    )
    return BlastRadiusReport(
        target=", ".join(sorted(targets)),
        max_hops=reports[0].max_hops if reports else 3,
        max_paths=reports[0].max_paths if reports else 100,
        findings=all_findings,
        summary=summary,
    )


def _detect_convergence(reports: list[BlastRadiusReport]) -> tuple[dict[str, Any], ...]:
    """Entities reached from more than one independent changed target.

    Two unrelated-looking changes (a dropped column and a removed API
    route) that both traverse to the same downstream service are more
    dangerous together than either finding alone suggests — this makes that
    convergence an explicit, visible fact rather than two separate findings
    a reader has to notice are related.
    """
    by_entity: dict[str, set[str]] = {}
    for report in reports:
        for finding in report.findings:
            by_entity.setdefault(finding.affected_entity, set()).add(report.target)
    convergent = [
        {"entity": entity, "targets": tuple(sorted(targets))}
        for entity, targets in by_entity.items()
        if len(targets) >= 2
    ]
    return tuple(sorted(convergent, key=lambda item: str(item["entity"])))


def _execute_pipeline(
    *,
    case_id: str,
    scenario: str,
    project_root: Path,
    display_root: str,
    migration_path: Path | None,
    schema_path: Path | None,
    api_contract_path: Path | None,
    semantic_files: list[Path | str] | None,
    version_label: str,
    extra_notes: tuple[str, ...] = (),
    manifest: ProjectManifest | None = None,
) -> AnalysisRunResult:
    """The one real pipeline. Every entry point above resolves inputs and calls this.

    ``display_root`` is a safe, human-readable label used in user-facing
    notes — never the real filesystem path, which for an uploaded project is
    an ephemeral local temp directory that must never reach a response.
    """

    unavailable: list[str] = []
    notes: list[str] = list(extra_notes)

    semantic = SemanticAnalyzer().analyze(project_root, files=semantic_files)
    graph = semantic.graph
    if graph.node_count == 0:
        unavailable.append("semantic_analysis")
        notes.append(f"No supported source files were discovered in {display_root}.")

    migration_sql, migration_note = _read_optional(migration_path)
    if migration_note:
        notes.append(migration_note)
    if migration_path is None:
        unavailable.append("deployment_rehearsal")

    deployment_finding = DeploymentAnalyzer(graph=graph).analyze(migration_sql or "")
    changed_entity = deployment_finding.schema_object or "UNKNOWN"

    # A "real" target exists only if a migration file was actually found and
    # it parsed into an identifiable schema change — never the UNKNOWN
    # placeholder DeploymentAnalyzer uses for PARSE_ERROR/NO_CHANGE. This
    # distinguishes "no change to compute impact for" (NOT_APPLICABLE) from
    # "computed impact, found none" (ANALYZED, 0 affected) — see capabilities.
    has_real_target = (
        migration_path is not None
        and deployment_finding.change not in {"PARSE_ERROR", "NO_CHANGE"}
        and deployment_finding.schema_object not in (None, "UNKNOWN")
    )

    # Mirrors capabilities["blast_radius"]["status"] below exactly: blast
    # radius was genuinely ANALYZED (even if the answer is zero) only when
    # a real target exists AND semantic analysis actually ran. Anything
    # else is unavailable, and — critically — must be threaded into
    # unavailable_components so decide()/explain() cannot describe a
    # nonexistent "N affected entities" for it (see DAY_P0.2 forensics).
    blast_radius_analyzed = has_real_target and graph.node_count > 0
    if not blast_radius_analyzed:
        unavailable.append("blast_radius")

    # Enumerate every individual schema change so the materialized evidence
    # graph has real change roots on this path too — the same evidence the
    # snapshot-pair path already exposes. Without this a single-repository
    # analysis would render a graph with no causes, understating a verdict
    # that is genuinely reachable from evidence.
    single_schema_changes: tuple[SchemaChange, ...] = ()
    if migration_sql:
        parsed_single = parse_migration_sql(migration_sql)
        if parsed_single.kind != "error":
            single_schema_changes = parsed_single.changes

    if blast_radius_analyzed and changed_entity in graph.entity_ids:
        blast_radius = BlastRadiusEngine().analyze(graph, BlastRadiusRequest(target=changed_entity))
    else:
        blast_radius = _empty_blast_radius(changed_entity)
        if blast_radius_analyzed:
            notes.append(
                f"{changed_entity} has no discovered dependents in the semantic graph; "
                "blast radius is empty by construction, not estimated."
            )

    api_contract_finding: APIContractFinding | None = None
    old_api = None
    api_contract_parse_error = False
    if api_contract_path is not None and api_contract_path.exists():
        try:
            api_contract_finding = analyze_api_contract(api_contract_path, api_contract_path)
            old_api = parse_openapi_document(api_contract_path)
        except (yaml.YAMLError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
            api_contract_parse_error = True
            unavailable.append("api_contract")
            notes.append(
                f"{api_contract_path.name} could not be parsed as OpenAPI/YAML/JSON "
                f"({type(exc).__name__}); API contract evidence is unavailable."
            )
    else:
        unavailable.append("api_contract")
        notes.append(f"No API contract file was found in {display_root}; evidence is unavailable.")

    old_schema, new_schema = _schema_snapshots(schema_path, migration_sql)
    if old_schema is None:
        unavailable.append("schema_snapshot")
        notes.append(f"No schema.sql was found in {display_root}; schema evidence is unavailable.")

    old_application = _derive_application_snapshot(semantic, version=version_label)

    rollback_report = analyze_rollback(
        RollbackRequest(
            old_application=old_application,
            old_schema=old_schema,
            new_schema=new_schema,
            old_api=old_api,
            new_api=old_api,
            migration_findings=(deployment_finding,),
            graph=graph,
            deployment_context=RollbackWindow(enabled=True, rollback_versions=(version_label,)),
        )
    )

    # DeploymentAnalyzer.analyze("") — called above with no migration file at
    # all — returns the same PARSE_ERROR shape (MEDIUM severity, 0.5
    # confidence) it uses for a real, malformed-but-present file. That
    # confuses "absent" with "broken." A genuinely missing migration must
    # contribute nothing to deployment_severity; a present-but-malformed one
    # still should (see DAY_P0.2 forensics). This is an evidence-selection
    # choice made here, in the orchestrator — decide()'s scoring is untouched.
    deployment_findings_for_decision = () if migration_path is None else (deployment_finding,)

    decision_report = decide(
        DecisionRequest(
            blast_radius=blast_radius,
            deployment_findings=deployment_findings_for_decision,
            api_contract=api_contract_finding,
            rollback=rollback_report,
            unavailable_components=tuple(unavailable),
        )
    )
    explanation_result = explain(decision_report)

    capabilities = _capability_matrix(
        graph=graph,
        manifest=manifest,
        migration_path=migration_path,
        deployment_finding=deployment_finding,
        blast_radius_analyzed=blast_radius_analyzed,
        has_real_target=has_real_target,
        changed_entity=changed_entity,
        blast_radius_affected=blast_radius.summary.affected_count,
        api_contract_finding=api_contract_finding,
        api_contract_parse_error=api_contract_parse_error,
        rollback_status=rollback_report.status.value,
    )

    return AnalysisRunResult(
        case_id=case_id,
        scenario=scenario,
        semantic=semantic,
        graph=graph,
        changed_entity=changed_entity,
        deployment_finding=deployment_finding,
        blast_radius=blast_radius,
        api_contract=api_contract_finding,
        rollback=rollback_report,
        decision=decision_report,
        explanation=explanation_result,
        old_schema=old_schema,
        new_schema=new_schema,
        manifest=manifest,
        capabilities=capabilities,
        unavailable_components=tuple(unavailable),
        notes=tuple(notes),
        schema_changes=single_schema_changes,
        blast_radius_targets=(
            (changed_entity,)
            if blast_radius_analyzed and changed_entity in graph.entity_ids
            else ()
        ),
    )


def _capability_matrix(
    *,
    graph: PreFlightGraph,
    manifest: ProjectManifest | None,
    migration_path: Path | None,
    deployment_finding: DeploymentFinding,
    blast_radius_analyzed: bool,
    has_real_target: bool,
    changed_entity: str,
    blast_radius_affected: int,
    api_contract_finding: APIContractFinding | None,
    api_contract_parse_error: bool,
    rollback_status: str,
) -> dict[str, dict[str, str]]:
    """Classify each analyzer's real outcome into one honest status.

    Pure presentation transform over already-computed results — it decides
    nothing about risk or safety, only which of ANALYZED / UNAVAILABLE /
    NOT_APPLICABLE / UNSUPPORTED / PARSE_ERROR describes what actually
    happened, so "no evidence" can never render identically to "evidence
    found, and there is genuinely nothing there."
    """
    matrix: dict[str, dict[str, str]] = {}

    if graph.node_count > 0:
        matrix["source"] = {
            "status": "ANALYZED",
            "detail": f"{graph.node_count} entities, {graph.edge_count} edges discovered.",
        }
    elif manifest is not None and manifest.unsupported_count > 0:
        matrix["source"] = {
            "status": "UNSUPPORTED",
            "detail": (
                f"{manifest.unsupported_count} file(s) in a language PreFlight does not parse; "
                "0 Python/Kotlin files were found."
            ),
        }
    else:
        matrix["source"] = {
            "status": "UNAVAILABLE",
            "detail": "No source files were discovered.",
        }

    if migration_path is None:
        matrix["database"] = {"status": "UNAVAILABLE", "detail": "No SQL migration file was found."}
    elif deployment_finding.change == "PARSE_ERROR":
        matrix["database"] = {
            "status": "PARSE_ERROR",
            "detail": "A migration file was found but could not be parsed.",
        }
    else:
        matrix["database"] = {
            "status": "ANALYZED",
            "detail": f"{deployment_finding.change} on {deployment_finding.schema_object}.",
        }

    if graph.node_count == 0 and not has_real_target:
        matrix["blast_radius"] = {
            "status": "UNAVAILABLE",
            "detail": (
                "Neither semantic analysis nor a real schema change is available; "
                "no dependency graph exists to traverse."
            ),
        }
    elif graph.node_count == 0:
        matrix["blast_radius"] = {
            "status": "UNAVAILABLE",
            "detail": "Semantic analysis did not run; no dependency graph exists to traverse.",
        }
    elif not has_real_target:
        matrix["blast_radius"] = {
            "status": "NOT_APPLICABLE",
            "detail": "No real schema change was identified to compute downstream impact for.",
        }
    else:
        unit = "entity" if blast_radius_affected == 1 else "entities"
        matrix["blast_radius"] = {
            "status": "ANALYZED",
            "detail": f"{blast_radius_affected} affected {unit} for {changed_entity}.",
        }

    if api_contract_parse_error:
        matrix["api_contract"] = {
            "status": "PARSE_ERROR",
            "detail": "An API contract file was found but could not be parsed.",
        }
    elif api_contract_finding is None:
        matrix["api_contract"] = {
            "status": "UNAVAILABLE",
            "detail": "No OpenAPI/Swagger contract file was found.",
        }
    else:
        change_count = len(api_contract_finding.changes)
        matrix["api_contract"] = {
            "status": "ANALYZED",
            "detail": f"{change_count} change(s); status {api_contract_finding.status.value}.",
        }

    matrix["rollback"] = {
        "status": rollback_status,
        "detail": f"Rollback compatibility resolved to {rollback_status}.",
    }

    return matrix


def _read_optional(path: Path | None) -> tuple[str | None, str | None]:
    if path is None:
        return None, None
    if not path.exists():
        return None, f"{path.name} does not exist; deployment evidence is unavailable."
    try:
        return path.read_text(encoding="utf-8"), None
    except OSError as exc:
        return None, f"failed to read {path.name}: {exc}"


def _schema_snapshots(
    schema_path: Path | None, migration_sql: str | None
) -> tuple[SchemaModel | None, SchemaModel | None]:
    if schema_path is None or not schema_path.exists():
        return None, None
    old_schema = parse_schema_sql(schema_path.read_text(encoding="utf-8"))
    if not migration_sql:
        return old_schema, old_schema
    parsed = parse_migration_sql(migration_sql)
    if parsed.kind == "error":
        return old_schema, old_schema
    return old_schema, apply_schema_migration(old_schema, parsed)


def _empty_blast_radius(target: str) -> BlastRadiusReport:
    return BlastRadiusReport(
        target=target,
        max_hops=3,
        max_paths=100,
        findings=(),
        summary=ImpactSummary(direct_count=0, indirect_count=0, affected_count=0),
    )


def _derive_application_snapshot(
    semantic: SemanticAnalysisResult, *, version: str
) -> ApplicationSnapshot:
    """Build the OLD application's dependency snapshot from real semantic evidence.

    A schema dependency is any database entity the graph shows application code
    actually reading (a ``DB_READ`` edge). An API dependency is any route the
    graph shows one service consuming from another (an ``API_CONSUMES`` edge).
    Every dependency carries the edge's own source-location evidence as
    provenance — nothing here is scenario-specific or hand-picked.
    """

    route_methods: dict[str, str] = {
        entity_id: method for _, method, _route, entity_id in semantic.route_registry.entries
    }
    route_paths: dict[str, str] = {
        entity_id: route for _, _method, route, entity_id in semantic.route_registry.entries
    }

    schema_dependencies: set[str] = set()
    api_dependencies: set[str] = set()
    provenance: list[dict[str, Any]] = []

    for edge in semantic.edges:
        if edge.kind == EdgeKind.DB_READ:
            schema_dependencies.add(edge.source)
            for item in edge.metadata.get("evidence", []):
                provenance.append(_provenance_entry(edge.source, item, version))
        elif edge.kind == EdgeKind.API_CONSUMES:
            method = route_methods.get(edge.source, "GET")
            route = route_paths.get(edge.source)
            dependency = f"{method} {route}" if route else edge.source
            api_dependencies.add(dependency)
            for item in edge.metadata.get("evidence", []):
                provenance.append(_provenance_entry(dependency, item, version))

    return ApplicationSnapshot(
        version=version,
        schema_dependencies=tuple(sorted(schema_dependencies)),
        api_dependencies=tuple(sorted(api_dependencies)),
        provenance=tuple(provenance),
    )


def _provenance_entry(entity: str, evidence_item: dict[str, Any], version: str) -> dict[str, Any]:
    return {
        "entity": entity,
        "source_file": evidence_item.get("source_file"),
        "line": evidence_item.get("line"),
        "operation": evidence_item.get("matched_pattern"),
        "resolution_rule": evidence_item.get("resolution_rule"),
        "version": version,
    }


__all__ = ["SCENARIOS", "run_analysis", "run_project_analysis", "run_snapshot_comparison"]
