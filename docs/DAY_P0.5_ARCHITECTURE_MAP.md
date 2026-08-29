# DAY P0.5 — Forensic Architecture Map

Produced before any P0.5 code was written, by reading source rather than trusting the P0.3/P0.4 reports. Every answer is a file:field citation.

## The fourteen questions

| # | Question | Answer (verified in source) |
|---|---|---|
| 1 | Object containing changed artifacts | `ChangeSet.repository_diff.files` — `tuple[FileChange, ...]`, each with `path`, `status`, `domains`, `old_sha256`, `new_sha256` (`domain/change_set.py`) |
| 2 | Object containing schema_changes | `AnalysisRunResult.schema_changes` — `tuple[SchemaChange, ...]` (`orchestration/models.py`, added P0.4). `SchemaChange` carries `kind`, `table`, `object_name`, `schema_object`, `category`, `severity`, `reason`, `evidence` |
| 3 | Object containing blast_radius_targets | `AnalysisRunResult.blast_radius_targets` — `tuple[str, ...]` of resolved graph entity IDs (added P0.4) |
| 4 | Where convergence is represented | `AnalysisRunResult.convergent_entities` — `tuple[dict, ...]`, each `{"entity": str, "targets": tuple[str, ...]}`, produced by `pipeline.py::_detect_convergence` |
| 5 | Where each blast path is represented | `BlastRadiusReport.findings[].path` — `ImpactPath(nodes, edge_types, evidence)` (`domain/blast_radius.py`). One finding per (target, affected_entity) pair, so convergent entities have one finding per cause |
| 6 | Where EdgeEvidence is represented | `semantic.py::EdgeEvidence` — `source_file`, `line`, `column`, `source_symbol`, `syntax_kind`, `matched_pattern`, `extracted_value`, `resolution_rule`, `evidence_text_summary`. Stored as dicts in `DependencyEdge.metadata["evidence"]` |
| 7 | Where each finding is represented | `DecisionReport.findings` — `tuple[NormalizedFinding, ...]` with `finding_id`, `category`, `severity`, `confidence`, `rule_id`, `affected_entities`, `evidence`, `provenance`, `source_module`, `blocking` |
| 8 | Where risk_features is represented | `DecisionReport.risk_features` — `RiskFeatures`, 14 scalar fields including the three weighted drivers `blast_severity`, `deployment_severity`, `rollback_unsafety` |
| 9 | Where policy_rules_triggered is represented | `DecisionReport.policy_rules_triggered` — `tuple[str, ...]` |
| 10 | Where deterministic_hash is generated | `decision.py::DecisionReport.with_hash()`, SHA-256 over `canonical_decision_json(self)` |
| 11 | Where change_set_hash / diff_hash are generated | `domain/change_set.py::ChangeSet.with_hash()` and `RepositoryDiff.with_hash()` — separate, canonical-JSON SHA-256 |
| 12 | Fields sufficient to construct the graph | `schema_changes` (roots) → `blast_radius.findings[].path.nodes` + `.edge_types` + `.evidence` (dependency chain) → `decision.findings` (findings) → `risk_features` (contributions) → `policy_rules_triggered` → `decision`. Plus `graph.entities` for node kinds and `convergent_entities` for convergence. **All already exist.** |
| 13 | Fields genuinely needing to be added | Only the materialization itself (`evidence_graph`) and structural source changes (`source_changes`). No new analysis. |
| 14 | Must NEVER be reconstructed by UI heuristics | Analyzer status (`capabilities`), risk arithmetic, the verdict, convergence, hop distance, provenance, and "did this analyzer run" — all are backend-authoritative (P0.2 invariant) |

## Conclusion drawn before implementing

The evidence graph is a **projection over data that already exists**, not a new analyzer. It must be built as a pure, deterministic transform in its own module, consuming `AnalysisRunResult` and emitting nodes/edges — exactly the "integration model, not a replacement" constraint. The two genuine gaps are the materialization and structural source diffing (the latter explicitly disclosed as missing in the P0.4 report).
