"use client";

import { Sparkles } from "lucide-react";
import styles from "../page.module.css";
import type { ExplanationResult } from "../../lib/api";

function aiStatusLabel(quality: ExplanationResult["quality"]): { text: string; tone: string } {
  if (quality === "FULL_AI") return { text: "AI EXPLANATION · ADVISORY ONLY", tone: "safe" };
  if (quality === "AI_UNAVAILABLE") return { text: "AI UNAVAILABLE · DETERMINISTIC FALLBACK", tone: "warn" };
  return { text: "DETERMINISTIC FALLBACK · NO AI PROVIDER CONFIGURED", tone: "unknown" };
}

export function AiExplanation({ explanation }: { explanation: ExplanationResult }) {
  const status = aiStatusLabel(explanation.quality);
  const response = explanation.response;

  return (
    <article className={`${styles.panel} ${styles.explanation}`}>
      <div className={styles.panelTitle}>
        <span>
          <Sparkles size={13} /> AI EXPLANATION
        </span>
        <small className={styles[`textTone_${status.tone}`]}>{status.text}</small>
      </div>
      <p className={styles.boundaryNote}>
        THE ENGINE DECIDES. THE AI EXPLAINS. This panel cannot change the decision, risk score, or
        evidence above it — it can only summarize them.
      </p>
      {response ? (
        <>
          <p className={styles.quote}>{response.verdict_explanation}</p>
          <div className={styles.explainGrid}>
            <div>
              <b>BLAST RADIUS</b>
              <span>{response.blast_radius_summary}</span>
            </div>
            <div>
              <b>ROLLBACK</b>
              <span>{response.rollback_summary}</span>
            </div>
            <div>
              <b>DEPLOYMENT</b>
              <span>{response.deployment_summary}</span>
            </div>
            <div>
              <b>UNCERTAINTY</b>
              <span>{response.uncertainty_summary}</span>
            </div>
          </div>
          {response.top_risks.length > 0 && (
            <div className={styles.claimList}>
              <div className={styles.subKicker}>GROUNDED CLAIMS</div>
              {response.top_risks.map((claim, i) => (
                <div className={styles.claimRow} key={i}>
                  <span className={styles[`chip_${claim.claim_type.toLowerCase()}`]}>{claim.claim_type}</span>
                  <span>{claim.claim}</span>
                </div>
              ))}
            </div>
          )}
          {response.remediation_plan.length > 0 && (
            <div className={styles.remediation}>
              <b>RECOMMENDED REMEDIATION</b>
              {response.remediation_plan.map((step) => (
                <div key={step.step_id}>
                  <span>{step.priority}</span>
                  {step.action}
                </div>
              ))}
            </div>
          )}
          <div className={styles.aiTiming}>
            generated in {explanation.total_ms.toFixed(1)}ms · confidence {Math.round(response.confidence * 100)}%
            · excluded from deterministic_hash
          </div>
        </>
      ) : (
        <p className={styles.emptyNote}>
          AI explanation unavailable ({explanation.error ?? "no provider configured"}). The
          deterministic decision above is unaffected — see Risk Calculation and Decision Trace.
        </p>
      )}
    </article>
  );
}
