"use client";

import { HelpCircle } from "lucide-react";
import styles from "../page.module.css";
import type { AnalysisResult, CapabilityStatus } from "../../lib/api";
import { capabilityTone } from "./format";

// Rendered when the analysis produced no causal roots — i.e. required evidence
// was missing, unsupported, or unavailable.
//
// This is deliberately NOT an empty canvas. It renders the chain PreFlight
// would have traced, with each stage labelled by the REAL backend capability
// status for that analyzer. Every value here comes from `result.capabilities`;
// no entity, edge, or finding is invented to fill the space.
const STAGES: { key: keyof AnalysisResult["capabilities"]; label: string }[] = [
  { key: "source", label: "SEMANTIC GRAPH" },
  { key: "database", label: "DATABASE CHANGE" },
  { key: "blast_radius", label: "DEPENDENCY IMPACT" },
  { key: "api_contract", label: "API CONTRACT" },
  { key: "rollback", label: "ROLLBACK" },
];

const ANALYZED: CapabilityStatus[] = ["ANALYZED", "SAFE"];

export function EvidenceGapGraph({ result }: { result: AnalysisResult }) {
  const capabilities = result.capabilities;
  const decision = result.decision_report.decision;

  return (
    <article className={styles.graphPanel}>
      <div className={styles.graphHead}>
        <div>
          <div className={styles.kicker}>EVIDENCE GAP</div>
          <h3 className={styles.graphTitle}>
            No causal chain could be constructed from this repository
          </h3>
        </div>
      </div>

      <p className={styles.gapLede}>
        PreFlight found the repository but could not establish the evidence required to prove what a
        change would break. It reports <b>{decision}</b> rather than guessing. Each stage below shows
        what the engine actually determined.
      </p>

      <ol className={styles.gapChain}>
        {STAGES.map(({ key, label }) => {
          const entry = capabilities[key];
          const tone = capabilityTone(entry.status);
          const ran = ANALYZED.includes(entry.status);
          return (
            <li key={key} className={styles.gapStage}>
              <span className={`${styles.gapMarker} ${styles[`gapMarker_${tone}`]}`}>
                {ran ? "" : "?"}
              </span>
              <div className={styles.gapBody}>
                <div className={styles.gapLabel}>{label}</div>
                <div className={styles.gapDetail}>{entry.detail}</div>
              </div>
              <em className={styles[`textTone_${tone}`]}>{entry.status.replaceAll("_", " ")}</em>
            </li>
          );
        })}
        <li className={styles.gapStage}>
          <span className={`${styles.gapMarker} ${styles.gapMarker_unknown}`}>
            <HelpCircle size={12} />
          </span>
          <div className={styles.gapBody}>
            <div className={styles.gapLabel}>VERDICT</div>
            <div className={styles.gapDetail}>
              Reached because required evidence was missing — not because the change was shown to be
              safe.
            </div>
          </div>
          <em className={styles.textTone_unknown}>{decision}</em>
        </li>
      </ol>
    </article>
  );
}
