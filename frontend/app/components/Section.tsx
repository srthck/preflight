"use client";

import type { ReactNode } from "react";
import styles from "../page.module.css";
import { useReveal } from "../../hooks/useReveal";

/**
 * One report section: kicker, heading, and body, revealed on scroll.
 *
 * Replaces the repeated `sectionHead` + panel pairs that were duplicated
 * throughout page.tsx, so heading rhythm and reveal behaviour are defined
 * once instead of per-section.
 */
export function Section({
  kicker,
  title,
  id,
  children,
  aside,
}: {
  kicker: string;
  title: string;
  id?: string;
  children: ReactNode;
  aside?: ReactNode;
}) {
  const { ref, revealed } = useReveal<HTMLDivElement>();

  return (
    <div
      ref={ref}
      id={id}
      className={`${styles.section} ${styles.reveal} ${revealed ? styles.revealed : ""}`}
    >
      <div className={styles.sectionHead}>
        <div>
          <div className={styles.kicker}>{kicker}</div>
          <h2>{title}</h2>
        </div>
        {aside}
      </div>
      {children}
    </div>
  );
}
