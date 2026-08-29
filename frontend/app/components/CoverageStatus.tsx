"use client";

import { CircleCheck, TriangleAlert } from "lucide-react";
import styles from "../page.module.css";
import type { AnalysisResult } from "../../lib/api";

export function CoverageStatus({ result }: { result: AnalysisResult }) {
  const { analysis, decision_report } = result;
  const clean = analysis.unavailable_components.length === 0 && analysis.semantic_diagnostics.length === 0;

  return (
    <article className={styles.panel}>
      <div className={styles.panelTitle}>
        <span>ANALYSIS COVERAGE</span>
        <small>PRECISION OVER MARKETING — no fabricated confidence score</small>
      </div>

      <div className={styles.statGrid}>
        {Object.entries(analysis.semantic_edge_counts).map(([kind, count]) => (
          <div key={kind} className={styles.statCell}>
            <strong>{count}</strong>
            <span>{kind.replaceAll("_", " ")} edges</span>
          </div>
        ))}
        <div className={styles.statCell}>
          <strong>{decision_report.risk_features.unresolved_reference_count}</strong>
          {/* This counts DYNAMIC_REFERENCE-category findings, which in the
              current pipeline are exactly the "analyzer unavailable"
              markers — not dangling code-symbol references. Labeled to
              match what it actually measures (see DAY_P0.2 forensics). */}
          <span>unavailable analyzer components</span>
        </div>
        <div className={styles.statCell}>
          <strong>{decision_report.risk_features.ambiguity_count}</strong>
          <span>ambiguous matches</span>
        </div>
      </div>

      {clean ? (
        <p className={styles.coverageOk}>
          <CircleCheck size={14} /> No unavailable analyzers, no unresolved semantic diagnostics for
          this run.
        </p>
      ) : (
        <>
          {analysis.unavailable_components.length > 0 && (
            <div className={styles.coverageWarn}>
              <TriangleAlert size={14} />
              <span>Unavailable analyzer components: {analysis.unavailable_components.join(", ")}</span>
            </div>
          )}
          {analysis.semantic_diagnostics.map((d) => (
            <div className={styles.coverageWarn} key={d}>
              <TriangleAlert size={14} />
              <span>{d}</span>
            </div>
          ))}
        </>
      )}

      {analysis.notes.length > 0 && (
        <ul className={styles.notesList}>
          {analysis.notes.map((note, i) => (
            <li key={i}>{note}</li>
          ))}
        </ul>
      )}
    </article>
  );
}
