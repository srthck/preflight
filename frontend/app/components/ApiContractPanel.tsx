"use client";

import styles from "../page.module.css";
import type { APIContractFinding } from "../../lib/api";
import { compatibilityTone } from "./format";

export function ApiContractPanel({ apiContract }: { apiContract: APIContractFinding | null }) {
  if (!apiContract) {
    return (
      <article className={styles.panel}>
        <div className={styles.panelTitle}>
          <span>API CONTRACT</span>
          <small>UNAVAILABLE</small>
        </div>
        <p className={styles.emptyNote}>
          No API contract fixture was found for this analysis. This is reported as unavailable, not
          treated as safe.
        </p>
      </article>
    );
  }

  const tone = compatibilityTone(apiContract.status);
  const hasChanges = apiContract.changes.length > 0;

  return (
    <article className={styles.panel}>
      <div className={styles.panelTitle}>
        <span>API CONTRACT</span>
        <small className={styles[`textTone_${tone}`]}>{apiContract.status}</small>
      </div>
      {!hasChanges ? (
        <p className={styles.emptyNote}>
          No breaking, cautionary, or compatible changes were detected — this migration does not
          modify the API contract. PreFlight does not manufacture an API finding to look more
          dangerous.
        </p>
      ) : (
        <div className={styles.apiChangeList}>
          {apiContract.changes.map((change, i) => (
            <div className={styles.apiChangeRow} key={`${change.rule_id}:${i}`}>
              <span className={styles[`chip_${change.compatibility.toLowerCase()}`]}>{change.compatibility}</span>
              <div>
                <strong>
                  {change.method} {change.path}
                </strong>
                <span>{change.reason}</span>
                <code>{change.rule_id}</code>
              </div>
            </div>
          ))}
        </div>
      )}
    </article>
  );
}
