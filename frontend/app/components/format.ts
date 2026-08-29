// Small, pure presentation helpers. No analysis logic lives here — every
// function only reformats a value the backend already computed.

import type {
  AnalysisResult,
  CapabilityStatus,
  Decision,
  RollbackStatus,
  CompatibilityStatus,
  Severity,
} from "../../lib/api";

export const pct = (value: number) => Math.round(value * 100);

export function decisionTone(decision: Decision): "danger" | "warn" | "safe" | "unknown" {
  if (decision === "DO_NOT_DEPLOY") return "danger";
  if (decision === "CAUTION") return "warn";
  if (decision === "SAFE") return "safe";
  return "unknown";
}

export function rollbackTone(status: RollbackStatus): "danger" | "warn" | "safe" | "unknown" {
  if (status === "UNSAFE") return "danger";
  if (status === "CAUTION") return "warn";
  if (status === "SAFE") return "safe";
  return "unknown";
}

export function compatibilityTone(status: CompatibilityStatus): "danger" | "warn" | "safe" | "unknown" {
  if (status === "BREAKING") return "danger";
  if (status === "CAUTION") return "warn";
  if (status === "SAFE") return "safe";
  return "unknown";
}

export function severityTone(severity: Severity): "danger" | "warn" | "safe" | "unknown" {
  if (severity === "CRITICAL" || severity === "HIGH") return "danger";
  if (severity === "MEDIUM") return "warn";
  if (severity === "LOW") return "safe";
  return "unknown";
}

export const shortHash = (hash: string, len = 16) => (hash ? `${hash.slice(0, len)}...` : "n/a");

export function capabilityTone(status: CapabilityStatus): "danger" | "warn" | "safe" | "unknown" {
  if (status === "ANALYZED" || status === "SAFE") return "safe";
  if (status === "UNSAFE" || status === "PARSE_ERROR") return "danger";
  if (status === "CAUTION" || status === "UNSUPPORTED") return "warn";
  return "unknown"; // UNAVAILABLE, NOT_APPLICABLE, UNKNOWN
}

// One deterministic sentence explaining the verdict, preferring the most
// causally specific real evidence available. Never the AI's paraphrase
// first — that's advisory; this line is the engine's own reasoning.
export function rootCauseText(result: AnalysisResult): string {
  const findings = result.decision_report.findings;
  const rollbackBlocking = findings.find((f) => f.category === "ROLLBACK" && f.blocking);
  if (rollbackBlocking) return rollbackBlocking.description;
  const anyBlocking = findings.find((f) => f.blocking);
  if (anyBlocking) return anyBlocking.description;
  if (result.explanation.response?.executive_summary) return result.explanation.response.executive_summary;
  if (result.decision_report.recommendations[0]) return result.decision_report.recommendations[0];
  return "No blocking evidence was found for this analysis.";
}

export function decisionLabel(decision: Decision): string {
  const words = decision.replaceAll("_", " ");
  return decision === "DO_NOT_DEPLOY" ? `${words}.` : words;
}

export function readableKind(kind: string): string {
  return kind.replaceAll("_", " ");
}

export function evidenceLabel(item: Record<string, unknown>): { key: string; value: string }[] {
  const order = [
    "source_file",
    "line",
    "source_symbol",
    "syntax_kind",
    "matched_pattern",
    "extracted_value",
    "resolution_rule",
    "operation",
    "entity",
    "source",
    "version",
  ];
  const rows: { key: string; value: string }[] = [];
  for (const key of order) {
    if (item[key] === undefined || item[key] === null || item[key] === "") continue;
    rows.push({ key, value: String(item[key]) });
  }
  for (const [key, value] of Object.entries(item)) {
    if (order.includes(key) || value === undefined || value === null || value === "") continue;
    rows.push({ key, value: typeof value === "object" ? JSON.stringify(value) : String(value) });
  }
  return rows;
}
