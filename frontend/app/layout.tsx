import type { Metadata } from "next";
import "./globals.css";

// The product's central claim is that the verdict is produced by a
// deterministic engine and that AI is explanation-only. Titling the page
// "PreFlight AI" contradicted that in the browser tab and in search results,
// so the name reflects what actually decides.
export const metadata: Metadata = {
  title: "PreFlight — Deployment Survival Engine",
  description:
    "Deterministic deployment-survivability analysis: trace what a change breaks, prove whether rollback survives.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
