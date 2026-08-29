"use client";

import { useState } from "react";
import { ChevronDown, TriangleAlert } from "lucide-react";
import styles from "../page.module.css";
import type { AnalysisResult, DecisionReport } from "../../lib/api";
import { pct } from "./format";

const WEIGHTS = { blast: 0.4, deployment: 0.35, rollback: 0.25 } as const;

function Row({
  label,
  weight,
  value,
  scored,
  feature,
  onHover,
}: {
  label: string;
  weight: number;
  value: number;
  scored: boolean;
  feature: string;
  onHover?: (feature: string | null) => void;
}) {
  const contribution = Math.round(100 * weight * value);
  // Hovering a contribution highlights the evidence that produced it in the
  // graph. The mapping is by backend feature name — the frontend does not
  // decide which findings belong to which feature.
  const hoverProps = {
    onMouseEnter: () => onHover?.(feature),
    onMouseLeave: () => onHover?.(null),
    onFocus: () => onHover?.(feature),
    onBlur: () => onHover?.(null),
    tabIndex: 0,
  };
  if (!scored) {
    return (
      <div className={styles.risk} {...hoverProps}>
        <span>
          {label}
          <small>{Math.round(weight * 100)}% weight · analyzer did not run</small>
        </span>
        <div>
          <i style={{ width: "0%" }} />
        </div>
        <strong className={styles.textTone_unknown}>NOT SCORED</strong>
      </div>
    );
  }
  return (
    <div className={styles.risk} {...hoverProps}>
      <span>
        {label}
        <small>{Math.round(weight * 100)}% weight · severity {value.toFixed(2)}</small>
      </span>
      <div>
        <i style={{ width: `${pct(value)}%` }} />
      </div>
      <strong>+{contribution}</strong>
    </div>
  );
}

export function RiskBreakdown({
  report,
  capabilities,
  onHoverFeature,
}: {
  report: DecisionReport;
  capabilities: AnalysisResult["capabilities"];
  onHoverFeature?: (feature: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const f = report.risk_features;
  const blastScored = capabilities.blast_radius.status === "ANALYZED";
  const deployScored = capabilities.database.status === "ANALYZED";
  const rollbackScored = ["SAFE", "CAUTION", "UNSAFE"].includes(capabilities.rollback.status);
  const anyUnscored = !blastScored || !deployScored || !rollbackScored;
  const blastContribution = Math.round(100 * WEIGHTS.blast * f.blast_severity);
  const deployContribution = Math.round(100 * WEIGHTS.deployment * f.deployment_severity);
  const rollbackContribution = Math.round(100 * WEIGHTS.rollback * f.rollback_unsafety);
  const reconciledBase = blastContribution + deployContribution + rollbackContribution;

  return (
    <article className={styles.panel}>
      <div className={styles.panelTitle}>
        <span>RISK CALCULATION</span>
        <small>WEIGHTED POLICY MODEL — src/preflight/decision.py::decide()</small>
      </div>
      {anyUnscored && (
        <p className={styles.coverageWarn}>
          <TriangleAlert size={14} />
          <span>
            The risk score below reflects only the analyzers that actually ran. A low number here
            does not mean low confidence — it means incomplete evidence. See coverage below.
          </span>
        </p>
      )}
      <Row
        label="Blast severity"
        weight={WEIGHTS.blast}
        value={f.blast_severity}
        scored={blastScored}
        feature="blast_severity"
        onHover={onHoverFeature}
      />
      <Row
        label="Deployment severity"
        weight={WEIGHTS.deployment}
        value={f.deployment_severity}
        scored={deployScored}
        feature="deployment_severity"
        onHover={onHoverFeature}
      />
      <Row
        label="Rollback unsafety"
        weight={WEIGHTS.rollback}
        value={f.rollback_unsafety}
        scored={rollbackScored}
        feature="rollback_unsafety"
        onHover={onHoverFeature}
      />
      <div className={styles.formula}>Risk = 0.40 × Blast + 0.35 × Deployment + 0.25 × Rollback</div>

      <button className={styles.disclosure} onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <ChevronDown size={14} className={open ? styles.rot180 : ""} />
        Why this score?
      </button>
      {open && (
        <div className={styles.calcTrace}>
          <div className={styles.calcRow}>
            <span>Base risk (weighted sum, reconciled)</span>
            <b>{reconciledBase === report.base_risk ? report.base_risk : `${reconciledBase} (backend: ${report.base_risk})`}</b>
          </div>
          {report.compound_risks.length > 0 ? (
            report.compound_risks.map((c) => (
              <div className={styles.calcRow} key={c.id}>
                <span>
                  Compound policy: <code>{c.id}</code> ({c.rules_triggered.join(" + ")})
                </span>
                <b>× {c.multiplier}</b>
              </div>
            ))
          ) : (
            <div className={styles.calcRow}>
              <span>Compound policy adjustments</span>
              <b>none triggered</b>
            </div>
          )}
          <div className={styles.calcRow}>
            <span>Compound multiplier (capped at 1.5×)</span>
            <b>× {report.compound_multiplier}</b>
          </div>
          <div className={`${styles.calcRow} ${styles.calcTotal}`}>
            <span>
              {report.base_risk} × {report.compound_multiplier} = {report.risk_score} (+
              {report.compound_adjustment} over base)
            </span>
            <b>FINAL RISK {report.risk_score}</b>
          </div>
          <div className={styles.chipRow}>
            {report.policy_rules_triggered.map((rule) => (
              <span className={styles.chip} key={rule}>
                {rule}
              </span>
            ))}
          </div>
        </div>
      )}
    </article>
  );
}
