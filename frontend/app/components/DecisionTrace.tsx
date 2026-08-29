"use client";

import { Check, CircleAlert, HelpCircle } from "lucide-react";
import styles from "../page.module.css";
import type { AnalysisResult } from "../../lib/api";

function stage(label: string, detail: string, completed: boolean) {
  return { label, detail, status: completed ? "COMPLETED" : "UNAVAILABLE" } as const;
}

export function DecisionTrace({ result }: { result: AnalysisResult }) {
  const { capabilities, deployment, api_contract, rollback, decision_report, explanation } = result;

  // Every stage's COMPLETED/UNAVAILABLE flag comes from the same
  // `capabilities` matrix the rest of the UI renders — never re-derived
  // ad hoc per component. Two components independently guessing at "did
  // this analyzer run" is exactly how the DAY_P0.2 contradiction happened.
  const stages = [
    stage(
      "PARSE SOURCE / BUILD SEMANTIC GRAPH",
      `${result.graph.entities.length} entities, ${result.graph.edges.length} edges (Tree-sitter)`,
      capabilities.source.status === "ANALYZED",
    ),
    stage(
      "ANALYZE DATABASE MIGRATION",
      capabilities.database.status === "ANALYZED"
        ? `${deployment.change} on ${deployment.schema_object} → ${deployment.deployment_status} (SQLGlot)`
        : capabilities.database.detail,
      capabilities.database.status === "ANALYZED",
    ),
    stage(
      "CALCULATE BLAST SEVERITY",
      capabilities.blast_radius.status === "ANALYZED"
        ? `${result.blast_radius.summary.affected_count} affected entities, target ${result.blast_radius.target}`
        : capabilities.blast_radius.detail,
      capabilities.blast_radius.status === "ANALYZED",
    ),
    stage(
      "CHECK API CONTRACT",
      capabilities.api_contract.status === "ANALYZED" && api_contract
        ? `${api_contract.changes.length} changes → ${api_contract.status}`
        : capabilities.api_contract.detail,
      capabilities.api_contract.status === "ANALYZED",
    ),
    stage(
      "REHEARSE ROLLBACK",
      `${rollback.findings.length} findings → rollback ${rollback.rollback_compatibility}`,
      capabilities.rollback.status === "SAFE" ||
        capabilities.rollback.status === "UNSAFE" ||
        capabilities.rollback.status === "CAUTION",
    ),
    stage(
      "APPLY POLICY / GENERATE DECISION",
      `${decision_report.policy_rules_triggered.join(", ") || "no policy rule triggered"} → ${decision_report.decision}`,
      true,
    ),
    stage(
      "GENERATE ADVISORY EXPLANATION",
      `${explanation.quality} in ${explanation.total_ms.toFixed(1)}ms (excluded from decision hash)`,
      true,
    ),
  ];

  return (
    <article className={styles.panel}>
      <div className={styles.panelTitle}>
        <span>DECISION TRACE</span>
        <small>ORDERED PIPELINE EXECUTION — src/preflight/orchestration/pipeline.py::run_analysis()</small>
      </div>
      <ol className={styles.traceList}>
        {stages.map((s, i) => (
          <li key={s.label} className={styles.traceStep}>
            <span className={styles.traceIndex}>{String(i + 1).padStart(2, "0")}</span>
            {s.status === "COMPLETED" ? (
              <Check size={14} className={styles.traceOk} />
            ) : (
              <CircleAlert size={14} className={styles.traceWarn} />
            )}
            <div>
              <strong>{s.label}</strong>
              <span>{s.detail}</span>
            </div>
            <em className={s.status === "COMPLETED" ? styles.traceOk : styles.traceWarn}>{s.status}</em>
          </li>
        ))}
      </ol>

      <div className={styles.subKicker}>EVIDENCE CHAIN ({decision_report.evidence_chain.length} steps)</div>
      <div className={styles.evidenceChainScroll}>
        {decision_report.evidence_chain.map((step, i) => (
          <div className={styles.chainStep} key={i}>
            <code>{step.source}</code>
            <span>→ {step.target}</span>
            <b>{step.value}</b>
          </div>
        ))}
      </div>

      {decision_report.unknowns.length > 0 && (
        <div className={styles.unknownBlock}>
          <HelpCircle size={13} />
          <span>{decision_report.unknowns.length} unresolved unknown(s): {decision_report.unknowns.join(", ")}</span>
        </div>
      )}
    </article>
  );
}
