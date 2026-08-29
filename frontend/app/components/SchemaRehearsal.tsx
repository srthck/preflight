"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import styles from "../page.module.css";
import type { AnalysisResult } from "../../lib/api";
import { capabilityTone } from "./format";

const STATUS_ORDER = { REMOVED: 0, CHANGED: 1, ADDED: 2, UNCHANGED: 3 };

export function SchemaRehearsal({ result }: { result: AnalysisResult }) {
  const [showUnchanged, setShowUnchanged] = useState(false);
  const { deployment, schema } = result;
  const capability = result.capabilities.database;
  const wasAnalyzed = capability.status === "ANALYZED";
  const migrationSql = deployment.evidence.find(([label]) => label === "migration.sql")?.[1];
  const rows = [...schema.diff].sort((a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status]);
  const visibleRows = showUnchanged ? rows : rows.filter((r) => r.status !== "UNCHANGED");
  const unchangedCount = rows.length - visibleRows.filter((r) => r.status !== "UNCHANGED").length;

  return (
    <article className={styles.panel}>
      <div className={styles.panelTitle}>
        <span>DATABASE REHEARSAL</span>
        <small>
          {wasAnalyzed ? (
            <>
              {deployment.change} · {deployment.schema_object} ·{" "}
              <b
                className={
                  styles[
                    `textTone_${deployment.deployment_status === "UNSAFE" ? "danger" : deployment.deployment_status === "SAFE" ? "safe" : "unknown"}`
                  ]
                }
              >
                {deployment.deployment_status}
              </b>
            </>
          ) : (
            <b className={styles[`textTone_${capabilityTone(capability.status)}`]}>
              {capability.status.replaceAll("_", " ")}
            </b>
          )}
        </small>
      </div>

      {!wasAnalyzed ? (
        <p className={styles.coverageWarn}>
          <span>{capability.detail}</span>
        </p>
      ) : schema.diff.length === 0 ? (
        <p className={styles.emptyNote}>Schema snapshot unavailable — no before/after diff could be computed.</p>
      ) : (
        <div className={styles.schemaTable}>
          <div className={`${styles.schemaRow} ${styles.schemaHead}`}>
            <span>Column</span>
            <span>Status</span>
            <span>Before</span>
            <span>After</span>
          </div>
          {visibleRows.map((row) => (
            <div className={styles.schemaRow} key={`${row.table}.${row.column}`}>
              <span>
                {row.table}.{row.column}
              </span>
              <span className={styles[`chip_${row.status.toLowerCase()}`]}>{row.status}</span>
              <span>{row.before ? `${row.before.data_type}${row.before.nullable ? "" : " NOT NULL"}` : "—"}</span>
              <span>{row.after ? `${row.after.data_type}${row.after.nullable ? "" : " NOT NULL"}` : "—"}</span>
            </div>
          ))}
        </div>
      )}
      {unchangedCount > 0 || rows.some((r) => r.status === "UNCHANGED") ? (
        <button className={styles.disclosure} onClick={() => setShowUnchanged((v) => !v)} aria-expanded={showUnchanged}>
          <ChevronDown size={13} className={showUnchanged ? styles.rot180 : ""} />
          {showUnchanged ? "Hide unchanged columns" : `Show ${rows.filter((r) => r.status === "UNCHANGED").length} unchanged columns`}
        </button>
      ) : null}

      {typeof migrationSql === "string" && (
        <>
          <div className={styles.subKicker}>REAL MIGRATION FILE PARSED BY SQLGlot</div>
          <pre className={styles.sqlBlock}>{migrationSql}</pre>
        </>
      )}

      {deployment.affected_entities.length > 0 && (
        <div className={styles.causalChainSmall}>
          <span>{deployment.schema_object} removed</span>
          <ChevronDown size={13} className={styles.rot270} />
          <span>still referenced by {deployment.affected_entities.length} dependent entit{deployment.affected_entities.length === 1 ? "y" : "ies"}</span>
          <ChevronDown size={13} className={styles.rot270} />
          <span>see Rollback Truth below</span>
        </div>
      )}
    </article>
  );
}
