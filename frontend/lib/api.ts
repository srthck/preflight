// Typed client for POST /api/analyze. Every field here mirrors a real
// Pydantic model in src/preflight/orchestration/models.py::to_response_payload().
// Nothing in this file is presentation-only data — if a field isn't in the
// backend response, it isn't in this type.

export type Severity = "INFO" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type Decision = "SAFE" | "CAUTION" | "DO_NOT_DEPLOY" | "UNKNOWN";
export type RollbackStatus = "SAFE" | "CAUTION" | "UNSAFE" | "UNKNOWN";
export type CompatibilityStatus = "SAFE" | "CAUTION" | "BREAKING" | "UNKNOWN";
export type ExplanationQuality = "FULL_AI" | "DETERMINISTIC_FALLBACK" | "AI_UNAVAILABLE";

export type Evidence = Record<string, unknown>;

export type NormalizedFinding = {
  finding_id: string;
  category: string;
  severity: Severity;
  confidence: number;
  rule_id: string;
  title: string;
  description: string;
  affected_entities: string[];
  evidence: Evidence[];
  provenance: Evidence[];
  source_module: string;
  blocking: boolean;
  uncertainty: string | null;
  direct: boolean;
};

export type RiskFeatures = {
  blast_severity: number;
  deployment_severity: number;
  rollback_unsafety: number;
  critical_dependency_count: number;
  high_dependency_count: number;
  destructive_change_count: number;
  breaking_api_count: number;
  rollback_violation_count: number;
  unknown_finding_count: number;
  ambiguity_count: number;
  unresolved_reference_count: number;
  affected_entity_count: number;
  max_dependency_hops: number;
  compound_failure_count: number;
};

export type CompoundRisk = {
  id: string;
  rules_triggered: string[];
  affected_entities: string[];
  severity: Severity;
  multiplier: number;
  evidence: Evidence[];
};

export type DecisionEvidence = { source: string; target: string; relation: string; value: string };

export type DecisionReport = {
  schema_version: string;
  decision: Decision;
  risk_score: number;
  base_risk: number;
  compound_adjustment: number;
  compound_multiplier: number;
  risk_features: RiskFeatures;
  findings: NormalizedFinding[];
  compound_risks: CompoundRisk[];
  policy_rules_triggered: string[];
  affected_entities: string[];
  evidence_chain: DecisionEvidence[];
  unknowns: string[];
  recommendations: string[];
  deterministic_hash: string;
};

export type GroundedClaim = { claim: string; claim_type: "PROVEN" | "INFERRED" | "UNKNOWN"; evidence_ids: string[] };
export type RemediationStep = {
  step_id: string;
  priority: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
  action: string;
  rationale: string;
  affected_component: string;
  verification: string;
  provenance_ids: string[];
};
export type ExplanationResponse = {
  schema_version: string;
  executive_summary: string;
  verdict_explanation: string;
  top_risks: GroundedClaim[];
  evidence_summary: GroundedClaim[];
  blast_radius_summary: string;
  rollback_summary: string;
  deployment_summary: string;
  uncertainty_summary: string;
  remediation_plan: RemediationStep[];
  confidence: number;
};
export type ExplanationResult = {
  quality: ExplanationQuality;
  response: ExplanationResponse | null;
  error: string | null;
  preparation_ms: number;
  provider_ms: number;
  validation_ms: number;
  total_ms: number;
};

export type GraphEntity = {
  entity_id: string;
  name: string;
  kind: string;
  service: string;
  file: string | null;
  line: number | null;
  metadata: Record<string, unknown>;
};
export type GraphEdge = { source: string; target: string; kind: string; weight: number; metadata: Record<string, unknown> };
export type GraphPath = { nodes: string[]; edges: string[]; hop_count: number };
export type Graph = { entities: GraphEntity[]; edges: GraphEdge[]; paths: GraphPath[]; graph_hash: string };

export type ImpactCategory = "DIRECT" | "INDIRECT";
export type BlastRadiusFinding = {
  target: string;
  affected_entity: string;
  severity: number;
  hop_distance: number;
  category: ImpactCategory;
  path: { nodes: string[]; edge_types: string[]; evidence: Evidence[] };
  reason: string;
};
export type BlastRadiusReport = {
  target: string;
  max_hops: number;
  max_paths: number;
  findings: BlastRadiusFinding[];
  summary: { direct_count: number; indirect_count: number; affected_count: number };
  confidence_note: string;
};

export type DeploymentFinding = {
  finding_id: string;
  category: string;
  severity: string;
  schema_object: string;
  change: string;
  affected_entities: string[];
  dependency_paths: string[][];
  evidence: [string, unknown][];
  explanation_key: string;
  deployment_status: "SAFE" | "COMPATIBLE" | "UNSAFE" | "UNKNOWN";
};

export type APIChange = {
  rule_id: string;
  severity: string;
  path: string;
  method: string;
  location: string;
  before: unknown;
  after: unknown;
  reason: string;
  compatibility: CompatibilityStatus;
  evidence: string[];
};
export type APIContractFinding = {
  status: CompatibilityStatus;
  changes: APIChange[];
  breaking_changes: APIChange[];
  warnings: APIChange[];
  compatible_changes: APIChange[];
  unknown_changes: APIChange[];
  provenance: Record<string, unknown>[];
  schema_version: string;
};

export type RollbackFinding = {
  rule_id: string;
  severity: string;
  status: RollbackStatus;
  category: string;
  entity: string;
  old_state: string;
  new_state: string;
  evidence: Evidence[];
  reason: string;
  provenance: Evidence[];
  missing_evidence: string[];
  recommended_next_observation: string | null;
  direction: "ROLLBACK" | "FORWARD";
  application_version: "OLD" | "NEW";
  database_state: "OLD" | "NEW";
  api_state: "OLD" | "NEW";
  direct: boolean;
};
export type RollbackReport = {
  schema_version: string;
  status: RollbackStatus;
  findings: RollbackFinding[];
  unsafe_dependencies: string[];
  compatible_changes: string[];
  unknown_changes: string[];
  evidence: Evidence[];
  affected_entities: string[];
  forward_compatibility: RollbackStatus;
  rollback_compatibility: RollbackStatus;
  deterministic_hash: string;
};

export type ColumnSchema = {
  name: string;
  data_type: string;
  nullable: boolean;
  default: string | null;
  primary_key: boolean;
  unique: boolean;
};
export type TableSchema = { name: string; columns: ColumnSchema[] };
export type SchemaSnapshot = { tables: TableSchema[] } | null;
export type SchemaDiffRow = {
  table: string;
  column: string;
  status: "ADDED" | "REMOVED" | "CHANGED" | "UNCHANGED";
  before: ColumnSchema | null;
  after: ColumnSchema | null;
};

export type AnalysisMeta = {
  changed_entity: string;
  semantic_diagnostics: string[];
  semantic_edge_counts: Record<string, number>;
  unavailable_components: string[];
  notes: string[];
};

export type ManifestFileClassification =
  | "semantic"
  | "migration_candidate"
  | "api_contract"
  | "unsupported"
  | "ignored"
  | "other";
export type ManifestEntry = {
  path: string;
  language: string | null;
  size: number;
  sha256: string;
  classification: ManifestFileClassification;
  ignored_reason: string | null;
};
export type ProjectManifest = {
  files: ManifestEntry[];
  file_count: number;
  ignored_count: number;
  unsupported_count: number;
  language_counts: Record<string, number>;
  framework_signals: string[];
  manifest_hash: string;
};

// One entry per analyzer stage. Distinguishes "ran and found nothing" from
// "did not run" — never collapsed into the same "0" the way a naive UI would.
export type CapabilityStatus =
  | "ANALYZED"
  | "UNAVAILABLE"
  | "NOT_APPLICABLE"
  | "UNSUPPORTED"
  | "PARSE_ERROR"
  | "SAFE"
  | "CAUTION"
  | "UNSAFE"
  | "UNKNOWN";
export type CapabilityEntry = { status: CapabilityStatus; detail: string };
export type CapabilityMatrix = {
  source: CapabilityEntry;
  database: CapabilityEntry;
  blast_radius: CapabilityEntry;
  api_contract: CapabilityEntry;
  rollback: CapabilityEntry;
};

// P0.3: the ChangeSet/RepositoryDiff domain — present only when the result
// came from a two-snapshot comparison (POST /api/analyze-change), null for a
// single-repository upload or fixture scenario.
export type FileChangeStatus = "SAME" | "ADDED" | "REMOVED" | "MODIFIED";
export type ChangeDomain =
  | "SOURCE"
  | "DATABASE"
  | "API"
  | "CONFIG"
  | "DEPLOYMENT"
  | "DEPENDENCY"
  | "UNKNOWN";
export type FileChange = {
  path: string;
  status: FileChangeStatus;
  domains: ChangeDomain[];
  old_sha256: string | null;
  new_sha256: string | null;
  old_size: number | null;
  new_size: number | null;
};
export type RepositoryDiff = {
  old_label: string;
  new_label: string;
  files: FileChange[];
  added_count: number;
  removed_count: number;
  modified_count: number;
  same_count: number;
  diff_hash: string;
};
export type ChangeSet = {
  source: "SNAPSHOT_PAIR" | "GIT_DIFF" | "MIGRATION" | "API_DIFF" | "SOURCE_DIFF";
  repository_diff: RepositoryDiff | null;
  changed_domains: ChangeDomain[];
  change_set_hash: string;
};
export type ConvergentEntity = { entity: string; targets: string[] };

// One row per individual schema change in the migration. A migration with two
// statements is two entries here — never collapsed into a single "primary"
// change, so multi-change migrations are visible rather than silently reduced.
export type SchemaChangeRow = {
  kind: string;
  table: string | null;
  object_name: string | null;
  schema_object: string | null;
  category: string;
  severity: string;
  reason: string;
  resolved_as_blast_target: boolean;
};

// ---------------------------------------------------------------------------
// P0.5 — the materialized evidence graph. Every node/edge is projected by the
// backend from evidence the analyzers produced; the frontend renders it and
// never reconstructs, infers, or recomputes any part of this chain.
// ---------------------------------------------------------------------------
export type EvidenceNodeKind =
  | "CHANGE"
  | "SCHEMA_ENTITY"
  | "SOURCE_SYMBOL"
  | "SERVICE"
  | "API_ENDPOINT"
  | "CLIENT"
  | "FINDING"
  | "RISK_FEATURE"
  | "POLICY_RULE"
  | "VERDICT";

export type EvidenceEdgeKind =
  | "AFFECTS"
  | "DEPENDS_ON"
  | "PRODUCES"
  | "CONTRIBUTES_TO"
  | "TRIGGERS"
  | "DETERMINES";

export type EvidenceNode = {
  id: string;
  kind: EvidenceNodeKind;
  label: string;
  layer: number;
  hop_distance: number | null;
  detail: string;
  severity: string | null;
  provenance: Evidence[];
  metadata: Record<string, unknown>;
};

export type EvidenceEdge = {
  source: string;
  target: string;
  kind: EvidenceEdgeKind;
  label: string;
  via_target: string | null;
  provenance: Evidence[];
};

export type EvidenceGraph = {
  nodes: EvidenceNode[];
  edges: EvidenceEdge[];
  roots: string[];
  convergence: ConvergentEntity[];
  evidence_count: number;
  reachable_verdict: boolean;
  graph_hash: string;
};

// Parser-established declaration changes (never text-diff inference).
export type StructuralChange = {
  kind: string;
  symbol: string;
  symbol_kind: string;
  file: string;
  line: number | null;
  language: string;
  established_by: string;
};
export type StructuralFileStatus = {
  file: string;
  status: "ANALYZED" | "PARSE_ERROR" | "UNSUPPORTED";
  detail: string;
};
export type StructuralDiff = {
  changes: StructuralChange[];
  file_statuses: StructuralFileStatus[];
  analyzed_file_count: number;
  unsupported_file_count: number;
};

export type AnalysisResult = {
  case_id: string;
  scenario: string;
  decision_report: DecisionReport;
  explanation: ExplanationResult;
  graph: Graph;
  blast_radius: BlastRadiusReport;
  deployment: DeploymentFinding;
  api_contract: APIContractFinding | null;
  rollback: RollbackReport;
  analysis: AnalysisMeta;
  capabilities: CapabilityMatrix;
  schema: { old: SchemaSnapshot; new: SchemaSnapshot; diff: SchemaDiffRow[] };
  ai_available: boolean;
  deterministic_hash: string;
  project_manifest: ProjectManifest | null;
  change_set: ChangeSet | null;
  deployment_findings: DeploymentFinding[];
  convergence: ConvergentEntity[];
  schema_changes: SchemaChangeRow[];
  blast_radius_targets: string[];
  evidence_graph: EvidenceGraph;
  structural_diff: StructuralDiff | null;
};

export class AnalysisApiError extends Error {}

// The two scenarios currently registered in preflight.orchestration.pipeline.SCENARIOS.
// Selecting a scenario only chooses which real fixture files the pipeline reads
// (fixtures/demo-commerce/database/migration.sql vs. migration_safe.sql) — the
// engine still computes every finding, the risk score, and the verdict itself.
export const SCENARIOS = [
  {
    id: "demo-commerce-phone-number-removal",
    label: "Destructive: DROP COLUMN",
    description: "ALTER TABLE users DROP COLUMN phone_number;",
  },
  {
    id: "demo-commerce-phone-verified-addition",
    label: "Safe: ADD COLUMN",
    description: "ALTER TABLE users ADD COLUMN phone_verified BOOLEAN DEFAULT FALSE;",
  },
] as const;
export type ScenarioId = (typeof SCENARIOS)[number]["id"];
export const DEFAULT_SCENARIO: ScenarioId = SCENARIOS[0].id;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

export function isAnalysisResult(value: unknown): value is AnalysisResult {
  if (!isRecord(value) || typeof value.case_id !== "string") return false;
  const report = value.decision_report;
  const graph = value.graph;
  const explanation = value.explanation;
  if (!isRecord(report) || !isRecord(graph) || !isRecord(explanation)) return false;
  return (
    typeof report.decision === "string" &&
    typeof report.risk_score === "number" &&
    typeof report.base_risk === "number" &&
    typeof report.compound_adjustment === "number" &&
    typeof report.deterministic_hash === "string" &&
    Array.isArray(report.findings) &&
    Array.isArray(graph.paths) &&
    "response" in explanation &&
    isRecord(value.blast_radius) &&
    isRecord(value.deployment) &&
    isRecord(value.rollback) &&
    isRecord(value.analysis) &&
    isRecord(value.capabilities) &&
    typeof value.ai_available === "boolean"
  );
}

export async function analyzeScenario(
  scenario: ScenarioId,
  fetcher: typeof fetch = fetch,
): Promise<AnalysisResult> {
  const baseUrl = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "");
  if (!baseUrl) throw new AnalysisApiError("Analysis API is not configured.");
  let response: Response;
  try {
    response = await fetcher(`${baseUrl}/api/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario }),
    });
  } catch {
    throw new AnalysisApiError("Analysis endpoint unavailable.");
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new AnalysisApiError("Analysis endpoint returned malformed JSON.");
  }
  if (!response.ok) {
    const detail = isRecord(payload) && typeof payload.detail === "string" ? payload.detail : null;
    throw new AnalysisApiError(detail ?? `Analysis endpoint returned ${response.status}.`);
  }
  if (!isAnalysisResult(payload)) {
    throw new AnalysisApiError("Engine returned an invalid analysis report.");
  }
  return payload;
}

// Preserved for the existing default-scenario smoke path.
export async function analyzeDemo(fetcher: typeof fetch = fetch): Promise<AnalysisResult> {
  return analyzeScenario(DEFAULT_SCENARIO, fetcher);
}

// Mirrors preflight.ingestion.limits.MAX_ARCHIVE_BYTES — informational only;
// the server enforces the real limit regardless of what the client checks.
export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

export async function analyzeProjectUpload(
  file: File,
  fetcher: typeof fetch = fetch,
): Promise<AnalysisResult> {
  const baseUrl = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "");
  if (!baseUrl) throw new AnalysisApiError("Analysis API is not configured.");

  const form = new FormData();
  form.append("archive", file, file.name);

  let response: Response;
  try {
    response = await fetcher(`${baseUrl}/api/analyze-project`, { method: "POST", body: form });
  } catch {
    throw new AnalysisApiError("Analysis endpoint unavailable.");
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new AnalysisApiError("Analysis endpoint returned malformed JSON.");
  }
  if (!response.ok) {
    const detail = isRecord(payload) && typeof payload.detail === "string" ? payload.detail : null;
    const code = isRecord(payload) && typeof payload.error === "string" ? payload.error : null;
    throw new AnalysisApiError([code, detail].filter(Boolean).join(": ") || `Upload rejected (${response.status}).`);
  }
  if (!isAnalysisResult(payload)) {
    throw new AnalysisApiError("Engine returned an invalid analysis report.");
  }
  return payload;
}

// The ChangeSet entry point: two real repository snapshots in, one causal
// comparison out. Everything downstream (graph, blast radius, decision,
// explanation) is the same real pipeline as a single upload — only the
// input model differs.
export async function analyzeChangeUpload(
  oldFile: File,
  newFile: File,
  fetcher: typeof fetch = fetch,
): Promise<AnalysisResult> {
  const baseUrl = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "");
  if (!baseUrl) throw new AnalysisApiError("Analysis API is not configured.");

  const form = new FormData();
  form.append("old", oldFile, oldFile.name);
  form.append("new", newFile, newFile.name);

  let response: Response;
  try {
    response = await fetcher(`${baseUrl}/api/analyze-change`, { method: "POST", body: form });
  } catch {
    throw new AnalysisApiError("Analysis endpoint unavailable.");
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new AnalysisApiError("Analysis endpoint returned malformed JSON.");
  }
  if (!response.ok) {
    const detail = isRecord(payload) && typeof payload.detail === "string" ? payload.detail : null;
    const code = isRecord(payload) && typeof payload.error === "string" ? payload.error : null;
    throw new AnalysisApiError([code, detail].filter(Boolean).join(": ") || `Upload rejected (${response.status}).`);
  }
  if (!isAnalysisResult(payload)) {
    throw new AnalysisApiError("Engine returned an invalid analysis report.");
  }
  return payload;
}
