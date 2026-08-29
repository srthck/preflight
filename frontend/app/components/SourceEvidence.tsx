"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import styles from "../page.module.css";
import type { Evidence } from "../../lib/api";

// Renders one provenance record at a time, with navigation when a node has
// several. Every field shown is read straight off the backend's EdgeEvidence;
// nothing here reconstructs a snippet or invents a line number. Uploaded
// source is rendered as text content only, never as markup.
export function SourceEvidence({ provenance }: { provenance: Evidence[] }) {
  const [index, setIndex] = useState(0);

  if (provenance.length === 0) {
    return (
      <>
        <div className={styles.subKicker}>SOURCE EVIDENCE</div>
        <p className={styles.boundaryNote}>
          No source location was recorded for this node.
        </p>
      </>
    );
  }

  const safeIndex = Math.min(index, provenance.length - 1);
  const item = provenance[safeIndex];

  const str = (key: string): string | null => {
    const value = item[key];
    return typeof value === "string" && value.length > 0 ? value : null;
  };
  const num = (key: string): number | null => {
    const value = item[key];
    return typeof value === "number" ? value : null;
  };

  const file = str("source_file");
  const line = num("line");
  const symbol = str("source_symbol") ?? str("symbol");
  const matched = str("matched_pattern");
  const extracted = str("extracted_value");
  const rule = str("resolution_rule");
  const summary = str("evidence_text_summary");
  const sql = str("sql");
  const snippet = sql ?? extracted ?? matched;

  // Provenance badge names the analyzer that actually produced the record.
  const analyzer = sql !== null ? "SQLGlot" : file !== null ? "Tree-sitter" : null;

  return (
    <>
      <div className={styles.evidenceHead}>
        <span className={styles.subKicker}>SOURCE EVIDENCE</span>
        <div className={styles.evidenceNav}>
          {analyzer && <span className={styles.analyzerBadge}>{analyzer}</span>}
          {provenance.length > 1 && (
            <>
              <button
                type="button"
                onClick={() => setIndex((i) => Math.max(0, i - 1))}
                disabled={safeIndex === 0}
                aria-label="Previous evidence item"
              >
                <ChevronLeft size={13} />
              </button>
              <span className={styles.evidenceCount}>
                {safeIndex + 1} / {provenance.length}
              </span>
              <button
                type="button"
                onClick={() => setIndex((i) => Math.min(provenance.length - 1, i + 1))}
                disabled={safeIndex === provenance.length - 1}
                aria-label="Next evidence item"
              >
                <ChevronRight size={13} />
              </button>
            </>
          )}
        </div>
      </div>

      {file && (
        <div className={styles.evidenceFile}>
          {file.split("/").map((part, i, all) => (
            <span key={`${part}-${i}`}>
              <code>{part}</code>
              {i < all.length - 1 && <i className={styles.crumbSep}>/</i>}
            </span>
          ))}
        </div>
      )}

      {snippet && (
        <div className={styles.evidenceCode}>
          <span className={styles.evidenceLineNo}>{line ?? "—"}</span>
          <pre className={styles.evidenceLine}>{snippet}</pre>
        </div>
      )}

      <dl className={styles.evidenceMeta}>
        {line !== null && (
          <>
            <dt>LINE</dt>
            <dd>{line}</dd>
          </>
        )}
        {symbol && (
          <>
            <dt>SYMBOL</dt>
            <dd>{symbol}</dd>
          </>
        )}
        {matched && (
          <>
            <dt>MATCH</dt>
            <dd>{matched}</dd>
          </>
        )}
        {extracted && (
          <>
            <dt>EXTRACTED</dt>
            <dd>{extracted}</dd>
          </>
        )}
        {rule && (
          <>
            <dt>RULE</dt>
            <dd>{rule}</dd>
          </>
        )}
      </dl>

      {summary && <p className={styles.evidenceSummary}>{summary}</p>}
    </>
  );
}
