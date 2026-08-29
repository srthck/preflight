"use client";

import { useEffect, useRef, useState } from "react";
import { Copy } from "lucide-react";
import styles from "../page.module.css";
import type { AnalysisResult } from "../../lib/api";
import { useReducedMotion } from "../../hooks/useReducedMotion";
import { rootCauseText } from "./format";

const COUNT_MS = 900;

// Moves the displayed number to the risk score the backend already returned.
//
// Presentation only. The number is never computed, refined, or discovered
// here, and the animation never stands in for analysis time. When the report
// is swapped for another completed analysis (the counterfactual), it travels
// from the previous REAL score to the new REAL score — both endpoints are
// engine output; only the frames between them are presentational, and the
// final frame is always exactly the returned value.
function useCountUp(target: number, enabled: boolean): number {
  const [value, setValue] = useState(enabled ? 0 : target);
  const fromRef = useRef(enabled ? 0 : target);

  useEffect(() => {
    if (!enabled) {
      fromRef.current = target;
      setValue(target);
      return;
    }
    const from = fromRef.current;
    if (from === target) {
      setValue(target);
      return;
    }
    let frame = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / COUNT_MS);
      // easeOutExpo — settles rather than ticking every integer
      const eased = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress);
      const next = Math.round(from + (target - from) * eased);
      setValue(next);
      if (progress < 1) {
        frame = requestAnimationFrame(tick);
      } else {
        fromRef.current = target;
      }
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, enabled]);

  return value;
}

const TONE: Record<string, string> = {
  SAFE: "safe",
  CAUTION: "warn",
  DO_NOT_DEPLOY: "danger",
  UNKNOWN: "unknown",
};

const HEADLINE: Record<string, string> = {
  SAFE: "Safe to deploy",
  CAUTION: "Deploy with caution",
  DO_NOT_DEPLOY: "Do not deploy",
  UNKNOWN: "Cannot be proven",
};

export function VerdictHeader({ result }: { result: AnalysisResult }) {
  const report = result.decision_report;
  const reducedMotion = useReducedMotion();
  const risk = useCountUp(report.risk_score, !reducedMotion);
  const tone = TONE[report.decision] ?? "unknown";
  const changeSetHash = result.change_set?.change_set_hash ?? null;

  const copy = (value: string) => {
    void navigator.clipboard?.writeText(value);
  };

  return (
    <section className={`${styles.verdict} ${styles[`verdictTone_${tone}`]}`}>
      <div className={styles.verdictMain}>
        <div className={styles.kicker}>DETERMINISTIC VERDICT</div>
        <h2 className={styles.verdictHeadline}>{HEADLINE[report.decision] ?? report.decision}</h2>
        {/* The deterministic root cause — the "why" a judge needs within
            five seconds, taken from the decision report, not written here. */}
        <p className={styles.verdictSub}>{rootCauseText(result)}</p>
        <p className={styles.verdictCounts}>
          {report.decision === "UNKNOWN"
            ? "Required evidence was unavailable, so PreFlight did not guess."
            : `${report.findings.length} finding${report.findings.length === 1 ? "" : "s"} · ${report.affected_entities.length} affected ${report.affected_entities.length === 1 ? "entity" : "entities"} · ${report.policy_rules_triggered.length} policy rule${report.policy_rules_triggered.length === 1 ? "" : "s"} triggered`}
        </p>
      </div>

      <div className={styles.verdictScore}>
        <div className={styles.riskNumber} aria-label={`Risk score ${report.risk_score} of 100`}>
          {risk}
        </div>
        <div className={styles.riskLabel}>RISK SCORE</div>
      </div>

      <dl className={styles.identityRow}>
        {changeSetHash && (
          <div>
            <dt title="Identifies the analyzed change content.">CHANGESET ID</dt>
            <dd>
              <code>{changeSetHash.slice(0, 12)}</code>
              <button type="button" onClick={() => copy(changeSetHash)} aria-label="Copy changeset id">
                <Copy size={11} />
              </button>
            </dd>
          </div>
        )}
        <div>
          <dt title="Identifies the deterministic decision produced from that evidence.">
            DECISION ID
          </dt>
          <dd>
            <code>{report.deterministic_hash.slice(0, 12)}</code>
            <button
              type="button"
              onClick={() => copy(report.deterministic_hash)}
              aria-label="Copy decision id"
            >
              <Copy size={11} />
            </button>
          </dd>
        </div>
      </dl>
    </section>
  );
}
