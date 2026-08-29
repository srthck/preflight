"use client";

import { useState } from "react";
import { X } from "lucide-react";
import styles from "../page.module.css";
import type { ProjectManifest } from "../../lib/api";

type Filter = "ALL" | "ANALYZED" | "UNSUPPORTED" | "IGNORED";

// Compact summary plus an on-demand drawer. The full manifest stays available
// for scrutiny without flooding the report — every row is backend data
// (classification, sha256, ignore reason), none of it recomputed here.
export function ManifestDrawer({ manifest }: { manifest: ProjectManifest }) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState<Filter>("ALL");

  const analyzed = manifest.files.filter(
    (f) => f.classification === "semantic" || f.classification === "migration_candidate" || f.classification === "api_contract",
  );
  const unsupported = manifest.files.filter((f) => f.classification === "unsupported");
  const ignored = manifest.files.filter((f) => f.classification === "ignored");

  const rows =
    filter === "ANALYZED"
      ? analyzed
      : filter === "UNSUPPORTED"
        ? unsupported
        : filter === "IGNORED"
          ? ignored
          : manifest.files;

  return (
    <section className={styles.manifestBar}>
      <div className={styles.manifestStats}>
        <div>
          <b>{manifest.file_count}</b>
          <span>FILES</span>
        </div>
        <div>
          <b>{analyzed.length}</b>
          <span>ANALYZED</span>
        </div>
        <div>
          <b>{unsupported.length}</b>
          <span>UNSUPPORTED</span>
        </div>
        <div>
          <b>{ignored.length}</b>
          <span>IGNORED</span>
        </div>
      </div>
      <button type="button" className={styles.pillButton} onClick={() => setOpen(true)}>
        View project
      </button>

      {open && (
        <div className={styles.drawerScrim} onClick={() => setOpen(false)} role="presentation">
          <aside
            className={styles.drawer}
            role="dialog"
            aria-label="Project manifest"
            onClick={(event) => event.stopPropagation()}
          >
            <div className={styles.drawerHead}>
              <div>
                <div className={styles.kicker}>PROJECT MANIFEST</div>
                <strong>{manifest.file_count} files</strong>
              </div>
              <button type="button" onClick={() => setOpen(false)} aria-label="Close manifest">
                <X size={16} />
              </button>
            </div>

            <div className={styles.drawerFilters}>
              {(["ALL", "ANALYZED", "UNSUPPORTED", "IGNORED"] as Filter[]).map((option) => (
                <button
                  key={option}
                  type="button"
                  className={`${styles.pillButton} ${filter === option ? styles.pillButtonActive : ""}`}
                  onClick={() => setFilter(option)}
                  aria-pressed={filter === option}
                >
                  {option}
                </button>
              ))}
            </div>

            <div className={styles.drawerList}>
              {rows.map((file) => (
                <div key={file.path} className={styles.manifestRow}>
                  <code className={styles.manifestPath}>{file.path}</code>
                  <div className={styles.manifestMeta}>
                    <span>{file.classification}</span>
                    {file.language && <span>{file.language}</span>}
                    <code>{file.sha256.slice(0, 10)}</code>
                  </div>
                  {file.ignored_reason && (
                    <p className={styles.manifestReason}>{file.ignored_reason}</p>
                  )}
                </div>
              ))}
              {rows.length === 0 && (
                <p className={styles.boundaryNote}>No files in this category.</p>
              )}
            </div>
          </aside>
        </div>
      )}
    </section>
  );
}
