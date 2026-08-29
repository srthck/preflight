// P0.8 — visual forensics capture.
//
// Drives the REAL running application in Chrome and captures the screens the
// P0.8 matrix requires. This does not assert appearance; it produces artifacts
// for human/agent inspection. Truth assertions live in the contract tests.
//
// Usage: node scripts/visual-qa.mjs <outputDir> [pass-label]

import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const out = process.argv[2];
const label = process.argv[3] ?? "pass1";
mkdirSync(out, { recursive: true });

const APP = "http://127.0.0.1:3000";
const shots = [];

async function shoot(page, name, opts = {}) {
  const file = join(out, `${label}-${name}.png`);
  await page.screenshot({ path: file, fullPage: opts.fullPage ?? false });
  shots.push(name);
  console.log(`  captured ${name}`);
}

const browser = await chromium.launch({ channel: "chrome" });

// ---------------------------------------------------------------- desktop
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const consoleErrors = [];
page.on("console", (m) => {
  if (m.type() === "error") consoleErrors.push(m.text());
});
page.on("pageerror", (e) => consoleErrors.push(`pageerror: ${e.message}`));

await page.goto(APP, { waitUntil: "networkidle" });
await page.waitForTimeout(400);
await shoot(page, "01-landing");
await shoot(page, "01b-landing-full", { fullPage: true });

// --- destructive canonical scenario ---------------------------------------
await page.getByRole("button", { name: /canonical scenario/i }).click();
await page.waitForSelector("text=/DETERMINISTIC VERDICT/i", { timeout: 20000 });
await page.waitForTimeout(2200); // let the causal reveal finish
await shoot(page, "03-destructive-verdict");
await shoot(page, "03b-destructive-full", { fullPage: true });

// --- evidence graph -------------------------------------------------------
const graphSvg = page.locator("svg[aria-label*='Causal evidence graph']");
await graphSvg.scrollIntoViewIfNeeded();
await page.waitForTimeout(600);
await shoot(page, "04-evidence-graph");

// hover a node
const nodes = page.locator("svg[aria-label*='Causal evidence graph'] g[role='button']");
const nodeCount = await nodes.count();
console.log(`  graph node count: ${nodeCount}`);
if (nodeCount > 2) {
  await nodes.nth(2).hover();
  await page.waitForTimeout(350);
  await shoot(page, "05-graph-hover");

  await nodes.nth(2).click();
  await page.waitForTimeout(450);
  await shoot(page, "06-graph-inspector");
  await shoot(page, "06b-graph-inspector-full", { fullPage: true });
}

// --- why this decision ----------------------------------------------------
const why = page.getByRole("button", { name: /why this decision/i });
if (await why.count()) {
  await why.first().click();
  await page.waitForTimeout(700);
  await shoot(page, "07-why-this-decision");
}

// --- risk interaction -----------------------------------------------------
const riskRow = page.locator("text=Blast severity").first();
if (await riskRow.count()) {
  await riskRow.scrollIntoViewIfNeeded();
  await riskRow.hover();
  await page.waitForTimeout(400);
  await shoot(page, "08-risk-hover");
}

// --- manifest / decision trace / rollback --------------------------------
for (const [name, selector] of [
  ["14-rollback", "text=/Rollback truth/i"],
  ["15-counterfactual", "text=/What if/i"],
  ["17-decision-trace", "text=/Decision trace/i"],
]) {
  const el = page.locator(selector).first();
  if (await el.count()) {
    await el.scrollIntoViewIfNeeded();
    await page.waitForTimeout(350);
    await shoot(page, name);
  }
}

// --- safe scenario --------------------------------------------------------
const safeBtn = page.getByRole("button", { name: /Safe: ADD COLUMN/i });
if (await safeBtn.count()) {
  await safeBtn.first().scrollIntoViewIfNeeded();
  await safeBtn.first().click();
  await page.waitForTimeout(2500);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(300);
  await shoot(page, "02-safe-verdict");
  await shoot(page, "02b-safe-full", { fullPage: true });
}

// ---------------------------------------------------------------- uploads
async function uploadZip(p, zipPath, shotName) {
  await p.evaluate(() => window.scrollTo(0, 0));
  const input = p.locator("input[type=file]").first();
  await input.setInputFiles(zipPath);
  const analyze = p.getByRole("button", { name: /Analyze project/i });
  await analyze.first().click();
  // Do NOT scroll to top here: the app scrolls to the verdict on completion,
  // and forcing the viewport back would hide the state under test.
  await p.waitForTimeout(3500);
  await shoot(p, shotName);
  await shoot(p, `${shotName}-full`, { fullPage: true });
}

const SCRATCH = process.env.PF_SCRATCH;
if (SCRATCH) {
  await page.goto(APP, { waitUntil: "networkidle" });
  await page.waitForTimeout(300);
  try {
    await uploadZip(page, join(SCRATCH, "unsup.zip"), "11-unsupported");
  } catch (e) {
    console.log(`  unsupported upload skipped: ${e.message}`);
  }
  await page.goto(APP, { waitUntil: "networkidle" });
  await page.waitForTimeout(300);
  try {
    await uploadZip(page, join(SCRATCH, "noev.zip"), "10-unknown");
  } catch (e) {
    console.log(`  unknown upload skipped: ${e.message}`);
  }
}

// ------------------------------------------------- two-version + convergence
// Drives the real "Compare two versions" flow with the fleet-ops OLD/NEW
// archives, which is the only path that produces a convergence graph.
if (SCRATCH) {
  try {
    await page.goto(APP, { waitUntil: "networkidle" });
    await page.getByRole("button", { name: /Compare two versions/i }).click();
    await page.waitForTimeout(250);
    const inputs = page.locator("input[type=file]");
    await inputs.nth(0).setInputFiles(join(SCRATCH, "fleet", "fleet-old.zip"));
    await inputs.nth(1).setInputFiles(join(SCRATCH, "fleet", "fleet-new.zip"));
    await page.waitForTimeout(250);
    await shoot(page, "13a-compare-selected");
    await page.getByRole("button", { name: /Analyze change/i }).click();
    await page.waitForSelector("text=/DETERMINISTIC VERDICT/i", { timeout: 30000 });
    await page.waitForTimeout(3000);
    await shoot(page, "13-two-version-verdict");
    await shoot(page, "13b-two-version-full", { fullPage: true });

    const conv = page.locator("text=/CONVERGENCE/i").first();
    if (await conv.count()) {
      await conv.scrollIntoViewIfNeeded();
      await page.waitForTimeout(300);
      await shoot(page, "09-convergence");
      await conv.click();
      await page.waitForTimeout(400);
      await shoot(page, "09b-convergence-detail");
    } else {
      console.log("  NOTE: no convergence marker found on the compare result");
    }

    const graph2 = page.locator("svg[aria-label*='Causal evidence graph']").first();
    if (await graph2.count()) {
      await graph2.scrollIntoViewIfNeeded();
      await page.waitForTimeout(500);
      await shoot(page, "09c-convergence-graph");
    }
  } catch (e) {
    console.log(`  two-version/convergence capture failed: ${e.message}`);
  }
}

// ---------------------------------------------------------------- judge mode
try {
  await page.goto(APP, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /canonical scenario/i }).click();
  await page.waitForSelector("text=/DETERMINISTIC VERDICT/i", { timeout: 20000 });
  await page.waitForTimeout(2200);
  const judge = page.getByRole("button", { name: /^Judge mode$/i });
  if (await judge.count()) {
    await judge.first().click();
    await page.waitForTimeout(700);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(400);
    await shoot(page, "15-judge-mode");
    await shoot(page, "15b-judge-mode-full", { fullPage: true });
  } else {
    console.log("  NOTE: judge mode toggle not found");
  }
} catch (e) {
  console.log(`  judge mode capture failed: ${e.message}`);
}

// ------------------------------------------------------------ upload lifecycle
if (SCRATCH) {
  try {
    await page.goto(APP, { waitUntil: "networkidle" });
    const input = page.locator("input[type=file]").first();
    await input.setInputFiles(join(SCRATCH, "inv.zip"));
    await page.waitForTimeout(200);
    await shoot(page, "12a-upload-selected");
    await page.getByRole("button", { name: /Analyze project/i }).first().click();
    await page.waitForTimeout(320); // capture mid-lifecycle
    await shoot(page, "12-upload-lifecycle");
  } catch (e) {
    console.log(`  upload lifecycle capture failed: ${e.message}`);
  }
}

// --------------------------------------------------------- reduced motion
try {
  const rmCtx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    reducedMotion: "reduce",
  });
  const rm = await rmCtx.newPage();
  await rm.goto(APP, { waitUntil: "networkidle" });
  await rm.getByRole("button", { name: /canonical scenario/i }).click();
  await rm.waitForSelector("text=/DETERMINISTIC VERDICT/i", { timeout: 20000 });
  await rm.waitForTimeout(1200);
  await shoot(rm, "17-reduced-motion");
  const rmState = await rm.evaluate(() => {
    const nodes = document.querySelectorAll("svg[aria-label*='Causal evidence'] g[role='button']");
    let hidden = 0;
    nodes.forEach((n) => { if (parseFloat(getComputedStyle(n).opacity) < 0.9) hidden++; });
    const sections = document.querySelectorAll("[class*='reveal']");
    let unrevealed = 0;
    sections.forEach((s) => { if (parseFloat(getComputedStyle(s).opacity) < 0.9) unrevealed++; });
    return { graphNodes: nodes.length, faded: hidden, revealTargets: sections.length, unrevealed };
  });
  console.log(`  reduced-motion: ${JSON.stringify(rmState)}`);
  await shoot(rm, "17b-reduced-motion-full", { fullPage: true });
} catch (e) {
  console.log(`  reduced motion capture failed: ${e.message}`);
}

// ---------------------------------------------------------------- mobile
const mobileCtx = await browser.newContext({ viewport: { width: 390, height: 844 } });
const mobile = await mobileCtx.newPage();
await mobile.goto(APP, { waitUntil: "networkidle" });
await mobile.waitForTimeout(400);
await shoot(mobile, "18-mobile-landing");
await mobile.getByRole("button", { name: /canonical scenario/i }).click();
await mobile.waitForSelector("text=/DETERMINISTIC VERDICT/i", { timeout: 20000 });
await mobile.waitForTimeout(2200);
await shoot(mobile, "18b-mobile-verdict");
await shoot(mobile, "18c-mobile-full", { fullPage: true });

// ---------------------------------------------------------------- tablet
const tabletCtx = await browser.newContext({ viewport: { width: 768, height: 1024 } });
const tablet = await tabletCtx.newPage();
await tablet.goto(APP, { waitUntil: "networkidle" });
await tablet.getByRole("button", { name: /canonical scenario/i }).click();
await tablet.waitForSelector("text=/DETERMINISTIC VERDICT/i", { timeout: 20000 });
await tablet.waitForTimeout(2200);
await shoot(tablet, "19-tablet-verdict");

await browser.close();

console.log(`\ncaptured ${shots.length} screenshots into ${out}`);
if (consoleErrors.length) {
  console.log(`\nCONSOLE ERRORS (${consoleErrors.length}):`);
  for (const e of consoleErrors.slice(0, 20)) console.log(`  - ${e}`);
} else {
  console.log("\nno console errors observed");
}
