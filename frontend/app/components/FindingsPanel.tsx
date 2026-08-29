"use client";

import { useState } from "react";
import { ChevronDown, ShieldAlert } from "lucide-react";
import styles from "../page.module.css";
import type { NormalizedFinding } from "../../lib/api";
import { evidenceLabel, severityTone } from "./format";

const GROUPS: { key: string; title: string; categories: string[] }[] = [
  { key: "primary", title: "PRIMARY FAILURE", categories: ["DATABASE", "SCHEMA"] },
  { key: "blast", title: "BLAST IMPACT", categories: ["BLAST_RADIUS"] },
  { key: "rollback", title: "ROLLBACK IMPACT", categories: ["ROLLBACK"] },
  { key: "api", title: "API CONTRACT IMPACT", categories: ["API_CONTRACT"] },
  {
    key: "other",
    title: "OTHER EVIDENCE",
    categories: ["CONFIGURATION", "SEMANTIC", "DYNAMIC_REFERENCE", "AMBIGUITY"],
  },
];

function FindingRow({ finding }: { finding: NormalizedFinding }) {
  const [open, setOpen] = useState(false);
  const tone = severityTone(finding.severity);
  return (
    <div className={styles.finding}>
      <span className={`${styles.severity} ${styles[`sevTone_${tone}`]}`}>{finding.severity}</span>
      <div className={styles.findingBody}>
        <div className={styles.findingHead}>
          <strong>{finding.title}</strong>
          {finding.blocking && (
            <span className={styles.blockingTag}>
              <ShieldAlert size={11} /> BLOCKING
            </span>
          )}
          {finding.uncertainty && <span className={styles.unknownTag}>UNCERTAIN</span>}
        </div>
        <span>{finding.description}</span>
        <div className={styles.findingMeta}>
          <code>{finding.rule_id}</code>
          <span>{finding.source_module}</span>
          <span>confidence {Math.round(finding.confidence * 100)}%</span>
          {finding.affected_entities.length > 0 && <span>{finding.affected_entities.join(", ")}</span>}
        </div>
        {(finding.evidence.length > 0 || finding.provenance.length > 0) && (
          <>
            <button className={styles.disclosure} onClick={() => setOpen((v) => !v)} aria-expanded={open}>
              <ChevronDown size={13} className={open ? styles.rot180 : ""} />
              {open ? "Hide evidence" : `Show evidence (${finding.evidence.length + finding.provenance.length})`}
            </button>
            {open && (
              <div className={styles.evidenceList}>
                {[...finding.evidence, ...finding.provenance].map((item, i) => (
                  <div className={styles.evidenceCard} key={i}>
                    {evidenceLabel(item).map((row) => (
                      <div key={row.key} className={styles.evidenceRow}>
                        <span>{row.key.replaceAll("_", " ")}</span>
                        <code>{row.value}</code>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export function FindingsPanel({ findings }: { findings: NormalizedFinding[] }) {
  return (
    <article className={styles.panel}>
      <div className={styles.panelTitle}>
        <span>DEPLOYMENT FINDINGS</span>
        <small>{findings.length} RECORDED — grouped by causal role, not insertion order</small>
      </div>
      {findings.length === 0 && <p className={styles.emptyNote}>No findings were recorded for this analysis.</p>}
      {GROUPS.map((group) => {
        const items = findings.filter((f) => group.categories.includes(f.category));
        if (items.length === 0) return null;
        return (
          <div className={styles.findingGroup} key={group.key}>
            <div className={styles.findingGroupTitle}>
              {group.title} <small>{items.length}</small>
            </div>
            {items.map((finding) => (
              <FindingRow finding={finding} key={finding.finding_id} />
            ))}
          </div>
        );
      })}
    </article>
  );
}
