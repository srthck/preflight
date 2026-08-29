"use client";

import { FileCode2, TriangleAlert } from "lucide-react";
import styles from "../page.module.css";
import type { StructuralDiff } from "../../lib/api";

// Renders declaration-level changes the parser established. Files that could
// not be parsed are shown as such — never silently omitted and never reported
// as if their symbols were removed.
export function StructuralChangesPanel({ diff }: { diff: StructuralDiff }) {
  const unparseable = diff.file_statuses.filter((s) => s.status !== "ANALYZED");

  return (
    <article className={styles.panel}>
      <div className={styles.panelTitle}>
        <span>
          <FileCode2 size={13} /> STRUCTURAL SOURCE CHANGES
        </span>
        <small>TREE-SITTER SYMBOL COMPARISON — src/preflight/structural_diff.py</small>
      </div>
      <p className={styles.boundaryNote}>
        {diff.analyzed_file_count} file(s) compared at the level of declared symbols. A change is
        listed only where the parser established it — never inferred from a text difference.
      </p>

      <div className={styles.evidenceChainScroll}>
        {diff.changes.map((change) => (
          <div className={styles.chainStep} key={`${change.file}-${change.symbol}-${change.kind}`}>
            <code>{change.kind}</code>
            <span>{change.symbol}</span>
            <b>
              {change.file}
              {change.line !== null ? `:${change.line}` : ""}
            </b>
          </div>
        ))}
      </div>

      {unparseable.length > 0 && (
        <p className={styles.coverageWarn}>
          <TriangleAlert size={14} />
          <span>
            {unparseable.length} file(s) could not be parsed on both sides; no structural claims are
            made about them: {unparseable.map((s) => s.file).join(", ")}.
          </span>
        </p>
      )}
    </article>
  );
}
