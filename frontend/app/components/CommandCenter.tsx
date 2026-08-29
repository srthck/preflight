"use client";

import { Activity, Copy, ShieldCheck, Terminal } from "lucide-react";
import styles from "../page.module.css";
import type { AnalysisResult, ScenarioId } from "../../lib/api";
import { SCENARIOS } from "../../lib/api";
import { shortHash } from "./format";

export function CommandCenter({
  result,
  scenario,
  loading,
  onScenarioChange,
  onCopyHash,
}: {
  result: AnalysisResult;
  scenario: ScenarioId;
  loading: boolean;
  onScenarioChange: (scenario: ScenarioId) => void;
  onCopyHash: () => void;
}) {
  const report = result.decision_report;
  const activeScenario = SCENARIOS.find((s) => s.id === scenario) ?? SCENARIOS[0];
  const isUpload = result.project_manifest !== null;

  return (
    <div className={styles.commandCenter}>
      {isUpload ? (
        <p className={styles.scenarioFixture}>
          Uploaded project: <code>{result.scenario}</code> —{" "}
          {result.project_manifest?.file_count}{" "}
          {result.project_manifest?.file_count === 1 ? "file" : "files"} discovered, analyzed by the
          same real pipeline as the demo scenarios.
        </p>
      ) : (
        <>
          <div className={styles.scenarioSwitch} role="group" aria-label="Select analysis scenario">
            {SCENARIOS.map((s) => (
              <button
                key={s.id}
                type="button"
                className={`${styles.scenarioButton} ${s.id === scenario ? styles.scenarioButtonActive : ""}`}
                onClick={() => onScenarioChange(s.id)}
                disabled={loading}
                aria-pressed={s.id === scenario}
              >
                {s.id === scenario && (loading ? <Activity className={styles.spin} size={13} /> : <Terminal size={13} />)}
                {s.label}
              </button>
            ))}
          </div>
          <p className={styles.scenarioFixture}>
            Real fixture input: <code>{activeScenario.description}</code> — changing this file changes
            this result; nothing here is scripted per scenario name.
          </p>
        </>
      )}

      {/* The verdict itself is owned by <VerdictHeader>; rendering it here too
          produced two competing verdict blocks on one screen. This component
          now carries only the controls and the provenance strip. */}
      <div className={styles.metaRow}>
        <span>
          DECISION HASH <code>{shortHash(report.deterministic_hash)}</code>
          <button className={styles.copyBtn} onClick={onCopyHash} aria-label="Copy full decision hash">
            <Copy size={12} />
          </button>
        </span>
        <span>
          ENGINE <b className={styles.online}>●</b> DETERMINISTIC
        </span>
        <span>
          AI ROLE <b>EXPLANATION ONLY</b>
        </span>
        <span>
          FINDINGS <b>{report.findings.length}</b>
        </span>
        <span>
          <ShieldCheck size={12} /> SAME INPUT → SAME HASH, EVERY RUN
        </span>
      </div>
    </div>
  );
}
