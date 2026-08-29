import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

// DESIGN.md specifies Aeonik Pro 500 for display and Inter 400/600 for body.
// Aeonik Pro is proprietary; the design system names Inter Display / General
// Sans / Sohne as the sanctioned substitutes, so Inter carries both roles here
// and the -1% display tracking correction is applied in globals.css.
// Self-hosted through next/font: no runtime request to Google, no layout shift.
const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
  weight: ["400", "500", "600", "700"],
});

// The product's central claim is that the verdict is produced by a
// deterministic engine and that AI is explanation-only. Titling the page
// "PreFlight AI" contradicted that in the browser tab and in search results,
// so the name reflects what actually decides.
export const metadata: Metadata = {
  title: "PreFlight — Deployment Survival Engine",
  description:
    "Deterministic deployment-survivability analysis: trace what a change breaks, prove whether rollback survives.",
};

// The canvas is true black; the browser chrome should not disagree with it.
export const viewport: Viewport = {
  themeColor: "#000000",
  colorScheme: "dark",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={inter.variable}>
      <body>{children}</body>
    </html>
  );
}
