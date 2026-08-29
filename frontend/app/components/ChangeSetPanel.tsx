"use client";

import type { ReactNode } from "react";
import { FilePlus, FileMinus, FileDiff, Link2 } from "lucide-react";
import styles from "../page.module.css";
import type {
  ChangeSet,
  ConvergentEntity,
  FileChangeStatus,
  SchemaChangeRow,
} from "../../lib/api";

const STATUS_ICON: Record<FileChangeStatus, ReactNode> = {
  ADDED: <FilePlus size={13} />,
  REMOVED: <FileMinus size={13} />,
  MODIFIED: <FileDiff size={13} />,
  SAME: null,
};

const MAX_ROWS_SHOWN = 30;

export function ChangeSetPanel({
  changeSet,
  convergence,
  schemaChanges,
}: {
  changeSet: ChangeSet;
  convergence: ConvergentEntity[];
  schemaChanges: SchemaChangeRow[];
}) {
  const diff = changeSet.repository_diff;
  if (diff === null) return null;

  const changed = diff.files.filter((f) => f.status !== "SAME");
  const shown = changed.slice(0, MAX_ROWS_SHOWN);
  const hiddenCount = changed.length - shown.length;

  return (
    <article className={styles.panel}>
      <div className={styles.panelTitle}>
        <span>REPOSITORY DIFF</span>
        <small>SHA-256 content identity — src/preflight/diffing.py::compare_repositories()</small>
      </div>
      <p className={styles.boundaryNote}>
        {diff.old_label} → {diff.new_label}: {diff.added_count} added, {diff.removed_count} removed,{" "}
        {diff.modified_count} modified, {diff.same_count} unchanged. Domains touched:{" "}
        {changeSet.changed_domains.length > 0 ? changeSet.changed_domains.join(", ") : "none"}.
      </p>

      {schemaChanges.length > 0 && (
        <>
          <div className={styles.subKicker}>
            SCHEMA CHANGES ({schemaChanges.length}) — each analyzed independently
          </div>
          <div className={styles.evidenceChainScroll}>
            {schemaChanges.map((change, i) => (
              <div className={styles.chainStep} key={`${change.schema_object ?? "?"}-${i}`}>
                <code>{change.kind}</code>
                <span>{change.schema_object ?? change.table ?? "unresolved target"}</span>
                <b>
                  {change.resolved_as_blast_target ? change.severity : "NO GRAPH TARGET"}
                </b>
              </div>
            ))}
          </div>
        </>
      )}

      {convergence.length > 0 && (
        <div className={styles.coverageWarn}>
          <Link2 size={14} />
          <span>
            {convergence.length} {convergence.length === 1 ? "entity" : "entities"} reached from more than
            one independent change — a stronger signal than isolated findings:{" "}
            {convergence.map((c) => `${c.entity} (${c.targets.join(" + ")})`).join("; ")}.
          </span>
        </div>
      )}

      {shown.length > 0 && (
        <div className={styles.evidenceChainScroll}>
          {shown.map((f) => (
            <div className={styles.chainStep} key={f.path}>
              {STATUS_ICON[f.status]}
              <code>{f.path}</code>
              <span>{f.domains.join(", ") || "UNKNOWN"}</span>
              <b>{f.status}</b>
            </div>
          ))}
        </div>
      )}
      {hiddenCount > 0 && (
        <p className={styles.boundaryNote}>
          +{hiddenCount} more changed file(s) not shown (full list in the machine-readable result).
        </p>
      )}
      {changed.length === 0 && (
        <p className={styles.boundaryNote}>No files differ between {diff.old_label} and {diff.new_label}.</p>
      )}
    </article>
  );
}
