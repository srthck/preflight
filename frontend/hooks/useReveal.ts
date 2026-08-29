"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Reveal-on-scroll via IntersectionObserver.
 *
 * P0.8 shipped the reveal CSS but never wired an observer, so sections never
 * animated in. This is the wiring, with two deliberate constraints:
 *
 *  - It reveals ONCE and then disconnects. Elements never re-hide on scroll
 *    up, which would make the page feel unstable while reading.
 *  - Under `prefers-reduced-motion` it returns `true` immediately and never
 *    observes anything, so no content depends on motion to become visible.
 */
export function useReveal<T extends HTMLElement = HTMLDivElement>(): {
  ref: React.RefObject<T>;
  revealed: boolean;
} {
  const ref = useRef<T>(null);
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (node === null) return;

    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced || typeof IntersectionObserver === "undefined") {
      setRevealed(true);
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setRevealed(true);
            observer.disconnect();
          }
        }
      },
      // Trigger a little before the element reaches the fold so the motion
      // completes as it arrives rather than after the reader is already there.
      { rootMargin: "0px 0px -12% 0px", threshold: 0.05 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return { ref, revealed };
}
