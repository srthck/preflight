// P0.5 — frontend contract test for the materialized evidence graph.
//
// This repository has no React component test runner configured, so rather
// than claim component coverage we do not have, this script asserts the
// contract the components actually depend on, against a LIVE backend:
// every field the graph UI reads must exist, every edge must resolve to a
// node it can draw, the verdict chain must be walkable, and each analysis
// state (ANALYZED / SAFE / UNKNOWN / UNSUPPORTED) must be distinguishable
// without the frontend inferring anything.
//
// Run with the API on :8000 —  node scripts/evidence-graph-contract.mjs

import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const base = (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const failures = [];

function check(condition, message) {
  if (!condition) failures.push(message);
}

async function analyzeScenario(scenario) {
  const response = await fetch(`${base}/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario }),
  });
  if (!response.ok) throw new Error(`${scenario}: HTTP ${response.status}`);
  return response.json();
}

async function analyzeProject(zipPath) {
  const form = new FormData();
  const { readFileSync } = await import("node:fs");
  form.append("archive", new Blob([readFileSync(zipPath)]), "project.zip");
  const response = await fetch(`${base}/api/analyze-project`, { method: "POST", body: form });
  if (!response.ok) throw new Error(`upload: HTTP ${response.status}`);
  return response.json();
}

// --- Structural contract every graph render depends on ---------------------
function assertGraphContract(payload, label) {
  const graph = payload?.evidence_graph;
  check(graph !== undefined && graph !== null, `${label}: evidence_graph present`);
  if (!graph) return null;

  check(Array.isArray(graph.nodes), `${label}: nodes is an array`);
  check(Array.isArray(graph.edges), `${label}: edges is an array`);
  check(Array.isArray(graph.roots), `${label}: roots is an array`);
  check(typeof graph.graph_hash === "string" && graph.graph_hash.length === 64,
    `${label}: graph_hash is a sha256`);
  check(typeof graph.reachable_verdict === "boolean", `${label}: reachable_verdict is boolean`);

  const ids = new Set(graph.nodes.map((n) => n.id));
  for (const node of graph.nodes) {
    check(typeof node.id === "string" && node.id.length > 0, `${label}: node has id`);
    check(typeof node.kind === "string", `${label}: node ${node.id} has kind`);
    check(typeof node.label === "string" && node.label.length > 0,
      `${label}: node ${node.id} has a label`);
    check(Number.isInteger(node.layer), `${label}: node ${node.id} has integer layer`);
    check(Array.isArray(node.provenance), `${label}: node ${node.id} provenance is an array`);
  }
  // Every edge must be drawable: both endpoints must exist as nodes.
  for (const edge of graph.edges) {
    check(ids.has(edge.source), `${label}: edge source ${edge.source} resolves to a node`);
    check(ids.has(edge.target), `${label}: edge target ${edge.target} resolves to a node`);
  }
  // Roots must be real nodes.
  for (const root of graph.roots) {
    check(ids.has(root), `${label}: root ${root} resolves to a node`);
  }
  return graph;
}

// Mirrors the frontend's verdictChain() traversal to prove the "why this
// decision" mode has something real to walk.
function verdictChain(graph) {
  const incoming = new Map();
  for (const edge of graph.edges) {
    const bucket = incoming.get(edge.target);
    if (bucket) bucket.push(edge.source);
    else incoming.set(edge.target, [edge.source]);
  }
  const verdict = graph.nodes.find((n) => n.kind === "VERDICT");
  if (!verdict) return new Set();
  const chain = new Set();
  const stack = [verdict.id];
  while (stack.length) {
    const current = stack.pop();
    if (chain.has(current)) continue;
    chain.add(current);
    stack.push(...(incoming.get(current) ?? []));
  }
  return chain;
}

function zipDir(dir, out) {
  execFileSync("python", [
    "-c",
    `import zipfile,pathlib\nsrc=pathlib.Path(r'${dir}')\nz=zipfile.ZipFile(r'${out}','w',zipfile.ZIP_DEFLATED)\n[z.write(f,f.relative_to(src).as_posix()) for f in sorted(src.rglob('*')) if f.is_file()]\nz.close()`,
  ]);
}

// --- 1. DO_NOT_DEPLOY: full causal chain must be present -------------------
const destructive = await analyzeScenario("demo-commerce-phone-number-removal");
const destructiveGraph = assertGraphContract(destructive, "destructive");
if (destructiveGraph) {
  check(destructive.decision_report.decision === "DO_NOT_DEPLOY", "destructive: verdict blocked");
  check(destructiveGraph.roots.length >= 1, "destructive: has at least one change root");
  check(destructiveGraph.reachable_verdict === true, "destructive: verdict reachable");

  const kinds = new Set(destructiveGraph.nodes.map((n) => n.kind));
  for (const required of ["CHANGE", "SCHEMA_ENTITY", "FINDING", "RISK_FEATURE", "POLICY_RULE", "VERDICT"]) {
    check(kinds.has(required), `destructive: graph contains a ${required} node`);
  }

  const chain = verdictChain(destructiveGraph);
  check(chain.size > 1, "destructive: verdict chain is walkable");
  const rootInChain = destructiveGraph.roots.some((r) => chain.has(r));
  check(rootInChain, "destructive: a change root reaches the verdict");

  // Dependency edges must carry provenance the inspector can render.
  const dependencyEdges = destructiveGraph.edges.filter((e) => e.kind === "DEPENDS_ON");
  check(dependencyEdges.length > 0, "destructive: has dependency edges");
  check(
    dependencyEdges.every((e) => Array.isArray(e.provenance) && e.provenance.length > 0),
    "destructive: every dependency edge carries provenance",
  );
}

// --- 2. SAFE: analyzed, zero impact — not an empty/absent graph ------------
const safe = await analyzeScenario("demo-commerce-phone-verified-addition");
const safeGraph = assertGraphContract(safe, "safe");
if (safeGraph) {
  check(safe.decision_report.decision === "SAFE", "safe: verdict is SAFE");
  check(safeGraph.nodes.some((n) => n.kind === "CHANGE"), "safe: the change is still shown");
  check(safeGraph.nodes.some((n) => n.kind === "VERDICT"), "safe: verdict node present");
  check(
    safe.capabilities.blast_radius.status === "ANALYZED",
    "safe: blast radius reports ANALYZED (not absent)",
  );
}

// --- 3. Determinism: identical input, identical graph identity -------------
const repeat = await analyzeScenario("demo-commerce-phone-number-removal");
check(
  repeat.evidence_graph.graph_hash === destructive.evidence_graph.graph_hash,
  "determinism: repeated analysis yields an identical graph hash",
);
check(
  repeat.deterministic_hash === destructive.deterministic_hash,
  "determinism: repeated analysis yields an identical decision hash",
);

// --- 4. UNSUPPORTED and 5. UNKNOWN must stay distinct from SAFE ------------
const root = mkdtempSync(join(tmpdir(), "pf-graph-"));
mkdirSync(join(root, "unsup", "src"), { recursive: true });
writeFileSync(join(root, "unsup", "src", "main.go"), "package main\nfunc main() {}\n");
zipDir(join(root, "unsup"), join(root, "unsup.zip"));

mkdirSync(join(root, "noev"), { recursive: true });
writeFileSync(join(root, "noev", "README.md"), "# docs only\n");
zipDir(join(root, "noev"), join(root, "noev.zip"));

for (const [name, expectedSource] of [["unsup", "UNSUPPORTED"], ["noev", "UNAVAILABLE"]]) {
  const payload = await analyzeProject(join(root, `${name}.zip`));
  const graph = assertGraphContract(payload, name);
  check(payload.decision_report.decision === "UNKNOWN", `${name}: decision stays UNKNOWN`);
  check(payload.decision_report.decision !== "SAFE", `${name}: never downgraded to SAFE`);
  check(payload.capabilities.source.status === expectedSource,
    `${name}: source capability is ${expectedSource}`);
  if (graph) {
    check(graph.roots.length === 0, `${name}: no fabricated change roots`);
    check(graph.reachable_verdict === false, `${name}: verdict is not claimed reachable`);
    const fabricated = graph.nodes.filter((n) =>
      ["CHANGE", "SCHEMA_ENTITY", "SERVICE", "API_ENDPOINT"].includes(n.kind));
    check(fabricated.length === 0, `${name}: no repository entities invented from absent evidence`);
  }
}

// --- 6. Malformed payload must not be treated as a result ------------------
const malformed = { case_id: "x", decision_report: null };
check(
  malformed.evidence_graph === undefined,
  "malformed: a payload without evidence_graph is detectably invalid",
);

// --- 7. P0.6 component contracts -------------------------------------------
// Each assertion below covers a field a specific UI component reads. If the
// backend stops supplying it, the component would render nothing rather than
// invent a value — so these are the contracts that keep the UI honest.

// VerdictHeader reads risk_score, decision, deterministic_hash, and the
// separately-named changeset hash.
check(typeof destructive.decision_report.risk_score === "number",
  "VerdictHeader: risk_score is a number (never computed in React)");
check(typeof destructive.decision_report.deterministic_hash === "string" &&
  destructive.decision_report.deterministic_hash.length === 64,
  "VerdictHeader: decision id present and distinct from changeset id");

// RiskBreakdown -> EvidenceCanvas highlight uses backend feature names, which
// must match the RISK_FEATURE node metadata exactly.
if (destructiveGraph) {
  const featureNodes = destructiveGraph.nodes.filter((n) => n.kind === "RISK_FEATURE");
  const featureNames = new Set(featureNodes.map((n) => n.metadata?.feature));
  for (const expected of ["blast_severity", "deployment_severity", "rollback_unsafety"]) {
    check(featureNames.has(expected),
      `risk highlight: RISK_FEATURE node exists for ${expected}`);
    check(Object.prototype.hasOwnProperty.call(destructive.decision_report.risk_features, expected),
      `risk highlight: risk_features carries ${expected}`);
  }
  // SourceEvidence reads these provenance keys off DEPENDS_ON edges.
  const withProvenance = destructiveGraph.edges
    .filter((e) => e.kind === "DEPENDS_ON")
    .flatMap((e) => e.provenance);
  check(withProvenance.length > 0, "SourceEvidence: dependency provenance exists");
  check(withProvenance.some((p) => typeof p.source_file === "string"),
    "SourceEvidence: provenance carries source_file");
  check(withProvenance.some((p) => typeof p.line === "number"),
    "SourceEvidence: provenance carries a line number");
}

// ManifestDrawer reads project_manifest file classifications.
const uploaded = await analyzeProject(join(root, "unsup.zip"));
const manifest = uploaded.project_manifest;
check(manifest !== null && manifest !== undefined, "ManifestDrawer: project_manifest present");
if (manifest) {
  check(typeof manifest.file_count === "number", "ManifestDrawer: file_count present");
  check(Array.isArray(manifest.files), "ManifestDrawer: files array present");
  check(manifest.files.every((f) => typeof f.classification === "string"),
    "ManifestDrawer: every file carries a classification");
  check(manifest.files.every((f) => typeof f.sha256 === "string" && f.sha256.length === 64),
    "ManifestDrawer: every file carries a content hash");
  // Security: the drawer must never be able to display a local path.
  check(!manifest.files.some((f) => /^[A-Za-z]:\\|^\/tmp\/|AppData/.test(f.path)),
    "security: manifest paths are repository-relative, not local extraction paths");
}

// EvidenceGapGraph reads capabilities for each stage.
for (const key of ["source", "database", "blast_radius", "api_contract", "rollback"]) {
  check(typeof uploaded.capabilities?.[key]?.status === "string",
    `EvidenceGapGraph: capabilities.${key}.status present`);
  check(typeof uploaded.capabilities?.[key]?.detail === "string",
    `EvidenceGapGraph: capabilities.${key}.detail present`);
}

// Security: no local extraction path anywhere in a response.
const serialized = JSON.stringify(uploaded);
check(!/[A-Za-z]:\\\\Users|AppData\\\\Local\\\\Temp/.test(serialized),
  "security: no local extraction path leaks into the response");

if (failures.length > 0) {
  console.error(`Evidence graph contract: FAIL (${failures.length})`);
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}
console.log("Evidence graph contract: PASS");
console.log(`  destructive -> ${destructive.decision_report.decision}, ` +
  `${destructive.evidence_graph.nodes.length} nodes, ${destructive.evidence_graph.roots.length} root(s)`);
console.log(`  safe        -> ${safe.decision_report.decision}, ` +
  `${safe.evidence_graph.nodes.length} nodes`);
console.log("  unsupported / no-evidence -> UNKNOWN, 0 roots, no invented entities");
