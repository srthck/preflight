"""P0.5 — the materialized evidence graph and its integrity invariants.

The graph is a projection over evidence the analyzers already produced. These
tests assert the projection is faithful (every node traces to a real artifact),
causal (removing a dependency removes the path), deterministic (same evidence,
same graph identity), and honest (missing evidence never becomes a node).

Fixtures used are deliberately not demo-commerce-shaped: ``fleet-ops`` (fleet
compliance, two convergent changes) and synthetic inventory repositories.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from preflight.evidence_graph import EvidenceEdgeKind, EvidenceNodeKind, build_evidence_graph
from preflight.orchestration import run_project_analysis
from preflight.orchestration.models import AnalysisRunResult
from preflight.orchestration.pipeline import run_snapshot_comparison

REPO_ROOT = Path(__file__).resolve().parents[2]
FLEET = REPO_ROOT / "fixtures" / "fleet-ops"
DEMO = REPO_ROOT / "fixtures" / "demo-commerce"

SHARED_API = "entity:compliance-api.ComplianceAPI"


def _pair(tmp_path: Path, *, migration: str | None = None) -> tuple[Path, Path]:
    old_root, new_root = tmp_path / "old", tmp_path / "new"
    shutil.copytree(FLEET, old_root)
    shutil.copytree(FLEET, new_root)
    (old_root / "database" / "migration.sql").unlink()
    if migration is not None:
        (new_root / "database" / "migration.sql").write_text(migration, encoding="utf-8")
    return old_root, new_root


def _analyze(tmp_path: Path, **kwargs: str | None) -> AnalysisRunResult:
    old_root, new_root = _pair(tmp_path, **kwargs)  # type: ignore[arg-type]
    return run_snapshot_comparison(old_root, new_root, case_id="p05")


@pytest.fixture()
def fleet(tmp_path: Path) -> AnalysisRunResult:
    return _analyze(tmp_path)


def _write(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Materialization
# ---------------------------------------------------------------------------


def test_materialized_evidence_graph_is_present_in_the_response(
    fleet: AnalysisRunResult,
) -> None:
    payload = fleet.to_response_payload()
    assert "evidence_graph" in payload
    graph = payload["evidence_graph"]
    assert graph["nodes"] and graph["edges"] and graph["roots"]
    assert graph["graph_hash"]


def test_graph_contains_the_full_change_to_verdict_chain(fleet: AnalysisRunResult) -> None:
    graph = build_evidence_graph(fleet)
    kinds = {node.kind for node in graph.nodes}
    for required in (
        EvidenceNodeKind.CHANGE,
        EvidenceNodeKind.SCHEMA_ENTITY,
        EvidenceNodeKind.SERVICE,
        EvidenceNodeKind.API_ENDPOINT,
        EvidenceNodeKind.FINDING,
        EvidenceNodeKind.RISK_FEATURE,
        EvidenceNodeKind.POLICY_RULE,
        EvidenceNodeKind.VERDICT,
    ):
        assert required in kinds, f"{required} missing from materialized graph"

    edge_kinds = {edge.kind for edge in graph.edges}
    for required_edge in (
        EvidenceEdgeKind.AFFECTS,
        EvidenceEdgeKind.DEPENDS_ON,
        EvidenceEdgeKind.PRODUCES,
        EvidenceEdgeKind.CONTRIBUTES_TO,
        EvidenceEdgeKind.TRIGGERS,
        EvidenceEdgeKind.DETERMINES,
    ):
        assert required_edge in edge_kinds


def test_multiple_changes_create_multiple_change_nodes(fleet: AnalysisRunResult) -> None:
    graph = build_evidence_graph(fleet)
    change_nodes = [n for n in graph.nodes if n.kind == EvidenceNodeKind.CHANGE]
    assert len(change_nodes) == 2
    assert len(graph.roots) == 2
    assert {n.metadata["schema_object"] for n in change_nodes} == {
        "drivers.license_number",
        "drivers.medical_cert",
    }


def test_verdict_is_reachable_through_the_graph(fleet: AnalysisRunResult) -> None:
    graph = build_evidence_graph(fleet)
    assert graph.reachable_verdict is True
    verdict = next(n for n in graph.nodes if n.kind == EvidenceNodeKind.VERDICT)
    assert verdict.label == "DO_NOT_DEPLOY"
    # The verdict must have at least one incoming DETERMINES edge.
    assert any(
        e.target == verdict.id and e.kind == EvidenceEdgeKind.DETERMINES for e in graph.edges
    )


# ---------------------------------------------------------------------------
# Convergence: one node, many preserved paths (P0.5 §3)
# ---------------------------------------------------------------------------


def test_convergence_is_materialized_as_one_node_with_multiple_paths(
    fleet: AnalysisRunResult,
) -> None:
    graph = build_evidence_graph(fleet)

    shared = [n for n in graph.nodes if n.id == SHARED_API]
    assert len(shared) == 1, "the shared entity must appear exactly once"

    incoming = [e for e in graph.edges if e.target == SHARED_API]
    assert len(incoming) == 2, "both causal paths must be preserved"
    assert {e.via_target for e in incoming} == {
        "drivers.license_number",
        "drivers.medical_cert",
    }
    assert graph.convergence and graph.convergence[0]["entity"] == "compliance-api.ComplianceAPI"


def test_removing_one_convergence_path_removes_convergence(tmp_path: Path) -> None:
    old_root, new_root = _pair(tmp_path)
    for root in (old_root, new_root):
        shutil.rmtree(root / "audit-service")
    graph = build_evidence_graph(run_snapshot_comparison(old_root, new_root, case_id="x"))

    assert graph.convergence == ()
    incoming = [e for e in graph.edges if e.target == SHARED_API]
    assert len(incoming) == 1
    assert incoming[0].via_target == "drivers.license_number"


def test_removing_a_dependency_removes_the_path(tmp_path: Path) -> None:
    baseline = build_evidence_graph(_analyze(tmp_path / "base"))
    assert any(e.target == SHARED_API for e in baseline.edges)

    old_root, new_root = _pair(tmp_path / "cut")
    for root in (old_root, new_root):
        for service in ("dispatch-service", "audit-service"):
            source = root / service / "src" / f"{service.replace('-', '_')}.py"
            text = source.read_text(encoding="utf-8")
            source.write_text(
                text.replace("_http_post(", "# removed(").replace(
                    "def # removed(", "def _http_post("
                ),
                encoding="utf-8",
            )
    cut = build_evidence_graph(run_snapshot_comparison(old_root, new_root, case_id="cut"))
    assert not any(e.target == SHARED_API for e in cut.edges)


# ---------------------------------------------------------------------------
# Integrity invariants (P0.5 §7)
# ---------------------------------------------------------------------------


def test_every_entity_node_is_reachable_from_a_change_root(fleet: AnalysisRunResult) -> None:
    """Invariant A: no orphan entity may appear in the causal graph."""
    graph = build_evidence_graph(fleet)
    adjacency: dict[str, list[str]] = {}
    for edge in graph.edges:
        adjacency.setdefault(edge.source, []).append(edge.target)

    reachable: set[str] = set()
    stack = list(graph.roots)
    while stack:
        current = stack.pop()
        if current in reachable:
            continue
        reachable.add(current)
        stack.extend(adjacency.get(current, []))

    entity_kinds = {
        EvidenceNodeKind.SCHEMA_ENTITY,
        EvidenceNodeKind.SERVICE,
        EvidenceNodeKind.API_ENDPOINT,
        EvidenceNodeKind.CLIENT,
    }
    for node in graph.nodes:
        if node.kind in entity_kinds:
            assert node.id in reachable, f"{node.id} has no change ancestor"


def test_dependency_edges_carry_provenance(fleet: AnalysisRunResult) -> None:
    """Invariant C: a drawn dependency must be justified by real evidence."""
    graph = build_evidence_graph(fleet)
    dependency_edges = [e for e in graph.edges if e.kind == EvidenceEdgeKind.DEPENDS_ON]
    assert dependency_edges
    for edge in dependency_edges:
        assert edge.provenance, f"{edge.source} -> {edge.target} has no provenance"
        for item in edge.provenance:
            assert item.get("source_file"), "provenance must name a source file"


def test_unknown_never_becomes_a_graph_entity(tmp_path: Path) -> None:
    """Invariant L: the ``"UNKNOWN"`` sentinel must never be materialized as a
    real repository entity.

    A *policy rule* legitimately named ``REQUIRED_EVIDENCE_UNKNOWN`` and a
    verdict of ``UNKNOWN`` are both genuine facts about the decision — they
    are the system correctly reporting that evidence was missing. What must
    never appear is a schema entity, service, API, or change node conjured
    from the ``"UNKNOWN"`` placeholder that DeploymentAnalyzer uses for
    unparseable migrations (the DAY_P0.2 defect).
    """
    _write(tmp_path, {"site/index.html": "<html></html>", "site/app.js": "console.log(1);"})
    result = run_project_analysis(tmp_path, case_id="c", scenario_label="no-evidence")
    graph = build_evidence_graph(result)

    repository_kinds = {
        EvidenceNodeKind.CHANGE,
        EvidenceNodeKind.SCHEMA_ENTITY,
        EvidenceNodeKind.SERVICE,
        EvidenceNodeKind.API_ENDPOINT,
        EvidenceNodeKind.CLIENT,
        EvidenceNodeKind.SOURCE_SYMBOL,
    }
    for node in graph.nodes:
        if node.kind in repository_kinds:
            assert "UNKNOWN" not in node.id
            assert node.label != "UNKNOWN"


def test_unavailable_analyzer_never_becomes_a_causal_node(tmp_path: Path) -> None:
    """Invariant M/N: absent evidence is not a fact about the repository."""
    _write(tmp_path, {"site/index.html": "<html></html>"})
    result = run_project_analysis(tmp_path, case_id="c", scenario_label="none")
    graph = build_evidence_graph(result)

    assert not any("ANALYZER-UNAVAILABLE" in n.label for n in graph.nodes)
    assert graph.roots == ()
    assert graph.reachable_verdict is False


def test_no_evidence_repository_produces_no_change_roots(tmp_path: Path) -> None:
    _write(tmp_path, {"README.md": "# docs only\n"})
    graph = build_evidence_graph(
        run_project_analysis(tmp_path, case_id="c", scenario_label="docs")
    )
    assert graph.roots == ()
    assert not [n for n in graph.nodes if n.kind == EvidenceNodeKind.CHANGE]
    # ...but the verdict node still exists and is honest about being unproven.
    verdict = next(n for n in graph.nodes if n.kind == EvidenceNodeKind.VERDICT)
    assert verdict.label == "UNKNOWN"
    assert graph.reachable_verdict is False


# ---------------------------------------------------------------------------
# Determinism (P0.5 §6)
# ---------------------------------------------------------------------------


def test_same_content_produces_the_same_graph_hash(tmp_path: Path) -> None:
    a = build_evidence_graph(_analyze(tmp_path / "a"))
    b = build_evidence_graph(_analyze(tmp_path / "deeply" / "nested" / "b"))
    assert a.graph_hash == b.graph_hash


def test_graph_node_and_edge_ordering_is_deterministic(tmp_path: Path) -> None:
    a = build_evidence_graph(_analyze(tmp_path / "a"))
    b = build_evidence_graph(_analyze(tmp_path / "b"))
    assert [n.id for n in a.nodes] == [n.id for n in b.nodes]
    assert [e.key for e in a.edges] == [e.key for e in b.edges]


def test_node_ids_are_content_derived_not_positional(fleet: AnalysisRunResult) -> None:
    graph = build_evidence_graph(fleet)
    for node in graph.nodes:
        assert not node.id.startswith("node-")
        assert node.id.split(":", 1)[0] in {
            "change",
            "entity",
            "finding",
            "risk",
            "policy",
            "verdict",
        }


def test_different_evidence_changes_the_graph_hash(tmp_path: Path) -> None:
    two = build_evidence_graph(_analyze(tmp_path / "two"))
    one = build_evidence_graph(
        _analyze(tmp_path / "one", migration="ALTER TABLE drivers DROP COLUMN license_number;\n")
    )
    assert two.graph_hash != one.graph_hash
    assert len(two.roots) == 2
    assert len(one.roots) == 1


def test_unrelated_readme_does_not_change_the_graph(tmp_path: Path) -> None:
    """Invariant G/H: an unanalyzed file must not perturb the causal graph."""
    baseline = _analyze(tmp_path / "baseline")
    old_root, new_root = _pair(tmp_path / "noisy")
    (new_root / "README.md").write_text("# notes\n", encoding="utf-8")
    noisy = run_snapshot_comparison(old_root, new_root, case_id="noisy")

    assert build_evidence_graph(baseline).graph_hash == build_evidence_graph(noisy).graph_hash
    assert baseline.decision.deterministic_hash == noisy.decision.deterministic_hash


# ---------------------------------------------------------------------------
# Honesty
# ---------------------------------------------------------------------------


def test_graph_contains_no_demo_vocabulary_for_unrelated_repository(
    fleet: AnalysisRunResult,
) -> None:
    """Invariant O."""
    serialized = json.dumps(build_evidence_graph(fleet).model_dump(mode="json"))
    for leaked in ("demo-commerce", "ProfileAPI", "UserService", "ProfileClient", "phone_number"):
        assert leaked not in serialized


def test_safe_change_produces_an_analyzed_graph_with_zero_impact(tmp_path: Path) -> None:
    """P0.5 §19: SAFE must read as 'analyzed, no dependents', not 'nothing ran'."""
    result = _analyze(
        tmp_path, migration="ALTER TABLE drivers ADD COLUMN telematics_id TEXT;\n"
    )
    graph = build_evidence_graph(result)

    # The change is still materialized even though it has no downstream impact.
    change_nodes = [n for n in graph.nodes if n.kind == EvidenceNodeKind.CHANGE]
    assert len(change_nodes) == 1
    assert change_nodes[0].label == "ADD_COLUMN"
    assert change_nodes[0].metadata["resolved_as_blast_target"] is False
    # No dependency edges, because there genuinely are no dependents.
    assert not [e for e in graph.edges if e.kind == EvidenceEdgeKind.DEPENDS_ON]


def test_canonical_demo_graph_still_materializes(tmp_path: Path) -> None:
    """The canonical fixture must project cleanly through the same code path."""
    old_root, new_root = tmp_path / "old", tmp_path / "new"
    shutil.copytree(DEMO, old_root)
    shutil.copytree(DEMO, new_root)
    (old_root / "database" / "migration.sql").unlink()
    (old_root / "database" / "migration_safe.sql").unlink()
    (new_root / "database" / "migration_safe.sql").unlink()

    graph = build_evidence_graph(run_snapshot_comparison(old_root, new_root, case_id="demo"))
    assert graph.reachable_verdict is True
    assert len(graph.roots) == 1
    labels = {n.label for n in graph.nodes}
    assert "DO_NOT_DEPLOY" in labels
    assert "ProfileAPI" in labels  # legitimate here: it is this fixture's real entity
