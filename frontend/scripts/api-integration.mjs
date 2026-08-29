const base = (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

async function analyze(scenario) {
  const response = await fetch(`${base}/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario }),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(`${scenario}: HTTP ${response.status}`);
  return payload;
}

function assertShape(payload, scenario) {
  const report = payload?.decision_report;
  const checks = [
    [typeof payload?.case_id === "string", "case_id"],
    [typeof report?.decision === "string", "decision_report.decision"],
    [typeof report?.risk_score === "number", "decision_report.risk_score"],
    [typeof report?.base_risk === "number", "decision_report.base_risk"],
    [typeof report?.compound_adjustment === "number", "decision_report.compound_adjustment"],
    [typeof report?.deterministic_hash === "string", "decision_report.deterministic_hash"],
    [Array.isArray(report?.findings), "decision_report.findings"],
    [Array.isArray(payload?.graph?.paths), "graph.paths"],
    [Array.isArray(payload?.graph?.entities), "graph.entities"],
    ["response" in (payload?.explanation ?? {}), "explanation.response"],
    [typeof payload?.blast_radius?.summary?.affected_count === "number", "blast_radius.summary.affected_count"],
    [typeof payload?.deployment?.change === "string", "deployment.change"],
    [typeof payload?.rollback?.status === "string", "rollback.status"],
    [Array.isArray(payload?.schema?.diff), "schema.diff"],
    [Array.isArray(payload?.analysis?.unavailable_components), "analysis.unavailable_components"],
    [typeof payload?.ai_available === "boolean", "ai_available"],
  ];
  const failed = checks.filter(([ok]) => !ok).map(([, name]) => name);
  if (failed.length) throw new Error(`${scenario}: missing/invalid fields: ${failed.join(", ")}`);
  return report;
}

const destructive = assertShape(await analyze("demo-commerce-phone-number-removal"), "destructive");
const safe = assertShape(await analyze("demo-commerce-phone-verified-addition"), "safe");

if (destructive.decision === safe.decision && destructive.risk_score === safe.risk_score) {
  throw new Error("Destructive and safe scenarios produced identical decisions — engine is not reacting to real input");
}

console.log(
  `Frontend API integration: PASS\n` +
    `  destructive -> ${destructive.decision} (${destructive.risk_score}/100, ${destructive.deterministic_hash})\n` +
    `  safe        -> ${safe.decision} (${safe.risk_score}/100, ${safe.deterministic_hash})`,
);
