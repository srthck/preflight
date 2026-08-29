"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import styles from "../page.module.css";
import type { ManifestFileClassification, ProjectManifest } from "../../lib/api";

const RELEVANT = new Set(["semantic", "migration_candidate", "api_contract"]);

const CHIP_BY_CLASSIFICATION: Record<ManifestFileClassification, string> = {
  semantic: "chip_added",
  migration_candidate: "chip_added",
  api_contract: "chip_added",
  unsupported: "chip_caution",
  ignored: "chip_unchanged",
  other: "chip_unknown",
};

export function ProjectManifestPanel({ manifest }: { manifest: ProjectManifest }) {
  const [showAll, setShowAll] = useState(false);
  const relevant = manifest.files.filter((f) => RELEVANT.has(f.classification));
  const visible = showAll ? manifest.files : relevant;

  return (
    <article className={styles.panel}>
      <div className={styles.panelTitle}>
        <span>PROJECT MANIFEST</span>
        <small>hash {manifest.manifest_hash.slice(0, 12)}…</small>
      </div>
      <div className={styles.statGrid}>
        <div className={styles.statCell}>
          <strong>{manifest.file_count}</strong>
          <span>files discovered</span>
        </div>
        {Object.entries(manifest.language_counts).map(([lang, count]) => (
          <div className={styles.statCell} key={lang}>
            <strong>{count}</strong>
            <span>{lang}</span>
          </div>
        ))}
        <div className={styles.statCell}>
          <strong>{manifest.unsupported_count}</strong>
          <span>unsupported</span>
        </div>
        <div className={styles.statCell}>
          <strong>{manifest.ignored_count}</strong>
          <span>ignored</span>
        </div>
      </div>

      {manifest.framework_signals.length > 0 && (
        <p className={styles.emptyNote}>
          Project markers found: {manifest.framework_signals.map((s) => <code key={s}>{s}</code>)}
        </p>
      )}

      <div className={styles.manifestTree}>
        {visible.map((entry) => (
          <div className={styles.manifestRow} key={entry.path}>
            <code>{entry.path}</code>
            <span className={styles[CHIP_BY_CLASSIFICATION[entry.classification]]}>
              {entry.classification.replaceAll("_", " ")}
            </span>
            <small>{entry.sha256.slice(0, 10)}…</small>
          </div>
        ))}
      </div>

      {manifest.files.length > relevant.length && (
        <button className={styles.disclosure} onClick={() => setShowAll((v) => !v)} aria-expanded={showAll}>
          <ChevronDown size={13} className={showAll ? styles.rot180 : ""} />
          {showAll ? "Show only analysis inputs" : `Show all ${manifest.files.length} files`}
        </button>
      )}
    </article>
  );
}
