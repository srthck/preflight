"use client";

import { ArrowDown, Check, X } from "lucide-react";
import styles from "../page.module.css";
import type { RollbackReport } from "../../lib/api";
import { rollbackTone } from "./format";

function StatusPill({ label, status }: { label: string; status: RollbackReport["status"] }) {
  const tone = rollbackTone(status);
  return (
    <div className={`${styles.rollbackPill} ${styles[`pillTone_${tone}`]}`}>
      {status === "SAFE" ? <Check size={14} /> : status === "UNKNOWN" ? null : <X size={14} />}
      {label} <b>{status}</b>
    </div>
  );
}

export function RollbackTimeMachine({ rollback }: { rollback: RollbackReport }) {
  const rollbackFindings = rollback.findings.filter((f) => f.direction === "ROLLBACK");
  const forwardFindings = rollback.findings.filter((f) => f.direction === "FORWARD");

  return (
    <article className={styles.panel} id="rollback">
      <div className={styles.panelTitle}>
        <span>ROLLBACK TRUTH — DEPLOYMENT TIME MACHINE</span>
        <small>OLD application vs. NEW schema/API, evaluated in both directions</small>
      </div>

      <div className={styles.timeline}>
        <div className={styles.timelineStage}>
          <div className={styles.timelineLabel}>T0 · CURRENT PRODUCTION</div>
          <div className={styles.timelineBox}>OLD APPLICATION + OLD DATABASE SCHEMA</div>
        </div>
        <ArrowDown size={16} className={styles.timelineArrow} />
        <div className={styles.timelineStage}>
          <div className={styles.timelineLabel}>T1 · PROPOSED MIGRATION</div>
          <div className={styles.timelineBox}>NEW DATABASE SCHEMA</div>
        </div>
      </div>

      <div className={styles.rollbackGrid}>
        <StatusPill label="FORWARD (NEW app → NEW schema)" status={rollback.forward_compatibility} />
        <StatusPill label="ROLLBACK (OLD app → NEW schema)" status={rollback.rollback_compatibility} />
      </div>

      {rollback.rollback_compatibility === "UNSAFE" && rollback.unsafe_dependencies.length > 0 && (
        <div className={styles.failurePoint}>
          <div className={styles.kicker}>FAILURE POINT</div>
          {rollback.unsafe_dependencies.map((dep) => (
            <p key={dep}>
              OLD APPLICATION expects <code>{dep}</code>, which the proposed schema no longer contains.
              Rolling back to the previous release after this migration ships will break it.
            </p>
          ))}
        </div>
      )}

      {rollback.forward_compatibility === "UNKNOWN" && (
        <p className={styles.emptyNote}>
          Forward compatibility is UNKNOWN — no next-version application snapshot was supplied to
          rollback analysis. This is reported honestly as unknown rather than assumed safe.
        </p>
      )}

      <div className={styles.rollbackColumns}>
        <div>
          <div className={styles.subKicker}>ROLLBACK-DIRECTION FINDINGS ({rollbackFindings.length})</div>
          {rollbackFindings.length === 0 && <p className={styles.emptyNote}>None.</p>}
          {rollbackFindings.map((f) => (
            <div className={styles.rollbackFinding} key={`${f.rule_id}:${f.entity}`}>
              <span className={`${styles.severity} ${styles[`sevTone_${rollbackTone(f.status)}`]}`}>{f.severity}</span>
              <div>
                <strong>
                  {f.entity}: {f.old_state} → {f.new_state}
                </strong>
                <span>{f.reason}</span>
                <code>{f.rule_id}</code>
              </div>
            </div>
          ))}
        </div>
        <div>
          <div className={styles.subKicker}>FORWARD-DIRECTION FINDINGS ({forwardFindings.length})</div>
          {forwardFindings.length === 0 && <p className={styles.emptyNote}>None.</p>}
          {forwardFindings.map((f) => (
            <div className={styles.rollbackFinding} key={`${f.rule_id}:${f.entity}`}>
              <span className={`${styles.severity} ${styles[`sevTone_${rollbackTone(f.status)}`]}`}>{f.severity}</span>
              <div>
                <strong>
                  {f.entity}: {f.old_state} → {f.new_state}
                </strong>
                <span>{f.reason}</span>
                <code>{f.rule_id}</code>
              </div>
            </div>
          ))}
        </div>
      </div>
    </article>
  );
}
