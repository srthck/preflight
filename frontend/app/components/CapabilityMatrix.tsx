"use client";

import { CheckCircle2, CircleSlash, HelpCircle, TriangleAlert, XCircle } from "lucide-react";
import styles from "../page.module.css";
import type { AnalysisResult, CapabilityEntry, CapabilityStatus } from "../../lib/api";
import { capabilityTone } from "./format";

const LABELS: Record<string, string> = {
  source: "SOURCE / SEMANTIC GRAPH",
  database: "DATABASE MIGRATION",
  blast_radius: "BLAST RADIUS",
  api_contract: "API CONTRACT",
  rollback: "ROLLBACK",
};

function StatusIcon({ status }: { status: CapabilityStatus }) {
  const tone = capabilityTone(status);
  if (tone === "safe") return <CheckCircle2 size={14} />;
  if (tone === "danger") return <XCircle size={14} />;
  if (tone === "warn") return <TriangleAlert size={14} />;
  return <CircleSlash size={14} />;
}

function Row({ id, entry }: { id: string; entry: CapabilityEntry }) {
  const tone = capabilityTone(entry.status);
  return (
    <div className={styles.capabilityRow}>
      <span className={styles[`textTone_${tone}`]}>
        <StatusIcon status={entry.status} />
      </span>
      <div>
        <strong>{LABELS[id] ?? id.toUpperCase()}</strong>
        <span>{entry.detail}</span>
      </div>
      <em className={styles[`textTone_${tone}`]}>{entry.status.replaceAll("_", " ")}</em>
    </div>
  );
}

export function CapabilityMatrix({ result }: { result: AnalysisResult }) {
  const capabilities = result.capabilities;
  const order = ["source", "database", "blast_radius", "api_contract", "rollback"] as const;
  const unavailableCount = order.filter((k) => {
    const tone = capabilityTone(capabilities[k].status);
    return tone === "unknown" || tone === "warn";
  }).length;

  return (
    <article className={styles.panel}>
      <div className={styles.panelTitle}>
        <span>
          <HelpCircle size={13} /> PROJECT UNDERSTANDING
        </span>
        <small>
          what could actually be analyzed — {order.length - unavailableCount}/{order.length} analyzers ran
        </small>
      </div>
      <p className={styles.boundaryNote}>
        Every row below is a real outcome, not a guess. UNAVAILABLE and NOT APPLICABLE never render as
        &ldquo;0&rdquo; — a missing analyzer is never confused with an analyzer that ran and found nothing.
      </p>
      <div className={styles.capabilityGrid}>
        {order.map((key) => (
          <Row id={key} entry={capabilities[key]} key={key} />
        ))}
      </div>
    </article>
  );
}
