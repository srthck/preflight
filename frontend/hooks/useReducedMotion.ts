"use client";

import { useEffect, useState } from "react";

// True when the user's OS/browser requests reduced motion. Callers use this
// to skip staged reveals and jump straight to the settled state — never to
// hide information, only to remove non-essential motion.
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(query.matches);
    const handler = (event: MediaQueryListEvent) => setReduced(event.matches);
    query.addEventListener("change", handler);
    return () => query.removeEventListener("change", handler);
  }, []);

  return reduced;
}
