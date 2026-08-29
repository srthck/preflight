"use client";

import { useState } from "react";
import { Activity, ArrowLeftRight, Check } from "lucide-react";
import styles from "../page.module.css";
import { analyzeScenario, SCENARIOS, type AnalysisResult, type ScenarioId } from "../../lib/api";
import { decisionLabel, decisionTone } from "./format";

/**
 * Two REAL pipeline runs, side by side, either of which can become the
 * report you are reading.
 *
 * Nothing here is simulated. The alternative is produced by calling the same
 * orchestration endpoint against a different real fixture file; adopting it
 * swaps in that exact returned payload rather than re-deriving anything. The
 * transition between them is presentation only — every value displayed at
 * rest is a value the engine actually returned.
 */
export function Counterfactual({
  current,
  scenario,
  onAdopt,
}: {
  current: AnalysisResult;
  scenario: ScenarioId;
  onAdopt: (result: AnalysisResult, id: ScenarioId) => void;
}) {
  const other = SCENARIOS.find((s) => s.id !== scenario)!;
  const [otherResult, setOtherResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const run = async () => {
    setLoading(true);
    setError("");
    try {
      setOtherResult(await analyzeScenario(other.id));
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Unable to run the counterfactual scenario.",
      );
    } finally {
      setLoading(false);
    }
  };

  const currentLabel = SCENARIOS.find((s) => s.id === scenario)?.label ?? scenario;

  return (
    <article className={styles.panel}>
      <div className={styles.panelTitle}>
        <span>COUNTERFACTUAL — TWO REAL PIPELINE RUNS</span>
        <small>same engine, a different real migration fixture</small>
      </div>
      <p className={styles.emptyNote}>
        This does not simulate a score. It runs the actual orchestration pipeline a second time
        against <code>{other.description}</code> — a different, real fixture file — and shows what
        the deterministic engine actually decides for it.
      </p>

      {!otherResult && !loading && (
        <button className={styles.ghostSmall} onClick={run}>
          <ArrowLeftRight size={13} /> Run {other.label}
        </button>
      )}
      {loading && (
        <div className={styles.ghostSmall}>
          <Activity size={13} className={styles.spin} /> Running real pipeline for {other.label}…
        </div>
      )}
      {error && <p className={styles.errorInline}>{error}</p>}

      {otherResult && (
        <>
          <div className={styles.cfGrid}>
            <CounterfactualCard
              label={currentLabel}
              result={current}
              active
              onSelect={() => onAdopt(current, scenario)}
            />
            <CounterfactualCard
              label={other.label}
              result={otherResult}
              active={false}
              onSelect={() => onAdopt(otherResult, other.id)}
            />
          </div>
          <p className={styles.cfNote}>
            Both results above were produced by the deterministic engine. Selecting one replaces the
            report you are reading with that exact returned analysis — the evidence graph, risk
            breakdown, and verdict all re-render from it. No intermediate value shown during the
            transition is engine output.
          </p>
        </>
      )}
    </article>
  );
}

function CounterfactualCard({
  label,
  result,
  active,
  onSelect,
}: {
  label: string;
  result: AnalysisResult;
  active: boolean;
  onSelect: () => void;
}) {
  const report = result.decision_report;
  const tone = decisionTone(report.decision);
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={active}
      className={`${styles.cfCard} ${styles[`cfTone_${tone}`]} ${active ? styles.cfCardActive : ""}`}
    >
      <span className={styles.cfLabel}>
        {active && <Check size={11} />}
        {label}
      </span>
      <strong className={styles.cfDecision}>{decisionLabel(report.decision)}</strong>
      <span className={styles.cfScore}>{report.risk_score}</span>
      <span className={styles.cfMeta}>
        {report.findings.length} findings · {report.affected_entities.length} affected
      </span>
      <span className={styles.cfAction}>{active ? "Currently shown" : "Show this analysis"}</span>
    </button>
  );
}
