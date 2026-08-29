"use client";

import { useEffect, useRef, useState } from "react";
import { CircleAlert, Database, GitBranch, Presentation, ShieldCheck, X } from "lucide-react";
import styles from "./page.module.css";
import {
  analyzeChangeUpload,
  analyzeProjectUpload,
  analyzeScenario,
  DEFAULT_SCENARIO,
  type AnalysisResult,
  type ScenarioId,
} from "../lib/api";
import { useReducedMotion } from "../hooks/useReducedMotion";
import { CommandCenter } from "./components/CommandCenter";
import { UploadPanel } from "./components/UploadPanel";
import { ProjectManifestPanel } from "./components/ProjectManifestPanel";
import { CapabilityMatrix } from "./components/CapabilityMatrix";
import { RiskBreakdown } from "./components/RiskBreakdown";
import { BlastRadiusGraph } from "./components/BlastRadiusGraph";
import { FindingsPanel } from "./components/FindingsPanel";
import { SchemaRehearsal } from "./components/SchemaRehearsal";
import { RollbackTimeMachine } from "./components/RollbackTimeMachine";
import { ApiContractPanel } from "./components/ApiContractPanel";
import { DecisionTrace } from "./components/DecisionTrace";
import { AiExplanation } from "./components/AiExplanation";
import { CoverageStatus } from "./components/CoverageStatus";
import { Counterfactual } from "./components/Counterfactual";
import { ChangeSetPanel } from "./components/ChangeSetPanel";
import { EvidenceCanvas } from "./components/EvidenceCanvas";
import { StructuralChangesPanel } from "./components/StructuralChangesPanel";
import { VerdictHeader } from "./components/VerdictHeader";
import { ManifestDrawer } from "./components/ManifestDrawer";
import { Section } from "./components/Section";

// The pipeline stages the backend actually executes, in its real call order
// (see DecisionTrace for the full per-stage breakdown once results arrive).
//
// HONESTY CONSTRAINT: the API returns one response at the end — it does not
// stream per-stage progress. These are therefore presented as the *ordered
// stages of the run*, never as confirmed completion, and no percentage is
// ever shown. The final stage stays active until the real response lands,
// so the UI cannot claim a stage finished that the backend never reported.
const UPLOAD_STAGES = [
  "INGEST ARCHIVE",
  "DISCOVER FILES",
  "PARSE SOURCE",
  "BUILD SEMANTIC GRAPH",
  "ANALYZE MIGRATION",
  "TRACE IMPACT",
  "CHECK API CONTRACT",
  "REHEARSE ROLLBACK",
  "APPLY POLICY",
];
const SCENARIO_STAGES = [
  "READING SOURCE",
  "BUILDING DEPENDENCY GRAPH",
  "REHEARSING MIGRATION",
  "CHECKING ROLLBACK",
  "APPLYING POLICY",
];
const STAGE_INTERVAL_MS = 170;

type EngineStatus = "checking" | "ready" | "unreachable";

export default function Home() {
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [scenario, setScenario] = useState<ScenarioId>(DEFAULT_SCENARIO);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [stageIndex, setStageIndex] = useState(0);
  const [activeStages, setActiveStages] = useState<string[]>(SCENARIO_STAGES);
  const [engineStatus, setEngineStatus] = useState<EngineStatus>("checking");
  // Cross-component focus: the risk panel hovers a feature, the graph
  // highlights the evidence that produced it. Both read backend identifiers.
  const [highlightFeature, setHighlightFeature] = useState<string | null>(null);
  // Judge mode: a focused reading of the same analysis — verdict, causal
  // proof, risk, rollback, coverage. It hides secondary sections; it never
  // hides or alters evidence, and everything remains reachable on exit.
  const [judgeMode, setJudgeMode] = useState(false);
  const reducedMotion = useReducedMotion();
  const liveRegion = useRef<HTMLDivElement>(null);
  const reportAnchor = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const baseUrl = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "");
    if (!baseUrl) {
      setEngineStatus("unreachable");
      return;
    }
    let cancelled = false;
    fetch(`${baseUrl}/health`)
      .then((res) => {
        if (!cancelled) setEngineStatus(res.ok ? "ready" : "unreachable");
      })
      .catch(() => {
        if (!cancelled) setEngineStatus("unreachable");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const runStaged = async (
    fetchResult: () => Promise<AnalysisResult>,
    onSuccess?: (data: AnalysisResult) => void,
    stages: string[] = SCENARIO_STAGES,
  ) => {
    setLoading(true);
    setError("");
    setStageIndex(0);
    setActiveStages(stages);
    if (liveRegion.current) liveRegion.current.textContent = "Running deterministic pipeline.";

    // Advances through the real stage list but stops on the last one and
    // waits there for the actual response. It never runs ahead of the
    // backend to a "complete" state, and it never invents a percentage.
    const stageTimer = reducedMotion
      ? null
      : setInterval(
          () => setStageIndex((i) => Math.min(i + 1, stages.length - 1)),
          STAGE_INTERVAL_MS,
        );

    try {
      const data = await fetchResult();
      setResult(data);
      onSuccess?.(data);
      if (liveRegion.current) {
        liveRegion.current.textContent = `Analysis complete. ${data.decision_report.decision.replaceAll("_", " ")}, risk ${data.decision_report.risk_score} of 100.`;
      }
      // Bring the verdict into view. Without this the hero still fills the
      // viewport after an analysis completes and the result sits below the
      // fold — the judge clicks "analyze" and appears to get nothing.
      requestAnimationFrame(() => {
        reportAnchor.current?.scrollIntoView({
          behavior: reducedMotion ? "auto" : "smooth",
          block: "start",
        });
      });
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "Unable to reach the deterministic engine.";
      setError(message);
      if (liveRegion.current) liveRegion.current.textContent = `Analysis failed: ${message}`;
    } finally {
      if (stageTimer) clearInterval(stageTimer);
      setLoading(false);
    }
  };

  const analyze = (target: ScenarioId = scenario) =>
    runStaged(() => analyzeScenario(target), () => setScenario(target));

  const analyzeUpload = (file: File) =>
    runStaged(() => analyzeProjectUpload(file), undefined, UPLOAD_STAGES);

  const analyzeChange = (oldFile: File, newFile: File) =>
    runStaged(() => analyzeChangeUpload(oldFile, newFile), undefined, UPLOAD_STAGES);

  // Adopt an already-returned analysis as the active report. No refetch and
  // no recomputation: the exact payload the engine returned becomes what the
  // whole page renders, so the graph, risk, and verdict all move together.
  const adoptResult = (data: AnalysisResult, id: ScenarioId) => {
    setResult(data);
    setScenario(id);
    if (liveRegion.current) {
      liveRegion.current.textContent = `Showing ${data.decision_report.decision.replaceAll("_", " ")}, risk ${data.decision_report.risk_score} of 100.`;
    }
    requestAnimationFrame(() => {
      reportAnchor.current?.scrollIntoView({
        behavior: reducedMotion ? "auto" : "smooth",
        block: "start",
      });
    });
  };

  const copyHash = () => {
    if (result) void navigator.clipboard?.writeText(result.decision_report.deterministic_hash);
  };

  return (
    <main className={styles.page}>
      <div ref={liveRegion} role="status" aria-live="polite" className="visuallyHidden" />

      <header className={styles.header}>
        <div className={styles.brand}>
          <span className={styles.mark}>
            <ShieldCheck size={16} />
          </span>
          <span>
            PRE<i>·</i>FLIGHT
          </span>
        </div>
        <nav className={styles.nav}>
          {!judgeMode && (
            <div className={styles.navLinks}>
              <a href="#proof">Analysis</a>
              <a href="#blast-radius">Evidence</a>
              <a href="#decision-trace">Architecture</a>
            </div>
          )}
          <div className={styles.navRight}>
            {result && (
              <button
                type="button"
                className={`${styles.judgeToggle} ${judgeMode ? styles.judgeToggleActive : ""}`}
                onClick={() => {
                  setJudgeMode((v) => !v);
                  requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: "auto" }));
                }}
                aria-pressed={judgeMode}
              >
                <Presentation size={13} />
                {judgeMode ? "Exit judge mode" : "Judge mode"}
              </button>
            )}
            <span className={styles.enginePill}>
              ENGINE{" "}
              <b style={{ color: engineStatus === "unreachable" ? "var(--danger-fg)" : undefined }}>●</b>{" "}
              {engineStatus === "checking" ? "CHECKING" : engineStatus === "ready" ? "READY" : "UNREACHABLE"}
            </span>
            <a href="https://github.com" aria-label="GitHub">
              <GitBranch size={16} />
            </a>
          </div>
        </nav>
      </header>

      {/* Judge mode opens on the verdict. Leaving the hero in place meant
          entering the mode still showed marketing copy above the fold — the
          opposite of a focused reading.
          Rendered conditionally rather than with the `hidden` attribute:
          `.hero` sets `display:flex`, which beats the user-agent
          `[hidden]{display:none}` rule and left the hero fully visible. */}
      {!judgeMode && (
      <section className={styles.hero}>
        <div className={styles.eyebrow}>
          <span className={styles.pulse} /> DEPLOYMENT SURVIVAL ENGINE
        </div>
        <h1>
          Ship with proof.
        </h1>
        <p>
          Know what breaks before production does. PreFlight traces the blast radius of a change,
          rehearses the deployment, checks the API contract, and proves whether rollback survives.
        </p>
        <div className={styles.actions}>
          <button className={styles.primary} onClick={() => analyze()} disabled={loading}>
            {loading ? "Analyzing…" : "Try the canonical scenario →"}
          </button>
        </div>
        <UploadPanel loading={loading} onAnalyze={analyzeUpload} onAnalyzeChange={analyzeChange} />
        <div className={styles.heroRule}>
          <span>TREE-SITTER</span>
          <span>SQLGLOT</span>
          <span>OPENAPI</span>
          <span>DETERMINISTIC ENGINE</span>
        </div>
      </section>
      )}

      <div ref={reportAnchor} className={styles.reportAnchor} />
      <section id="proof" className={styles.workspace}>
        {!result && !loading && !error && (
          <div className={styles.empty}>
            <div className={styles.emptyIcon}>
              <Database size={24} />
            </div>
            <h3>No analysis has run yet.</h3>
            <p>
              Analyzing loads a real fixture — real source, a real migration file, a real API
              contract — and runs it through the actual pipeline. Nothing below is scripted.
            </p>
          </div>
        )}

        {loading && (
          <div className={styles.loadingPanel}>
            <div className={styles.kicker}>DETERMINISTIC PIPELINE — {activeStages.length} STAGES</div>
            <ol className={styles.stagedList} aria-hidden={reducedMotion}>
              {activeStages.map((label, i) => (
                <li
                  key={label}
                  className={`${styles.stagedItem} ${i === stageIndex ? styles.stagedActive : ""} ${i < stageIndex ? styles.stagedDone : ""}`}
                >
                  <span className={styles.stagedIndex}>{String(i + 1).padStart(2, "0")}</span>
                  <span className={styles.stagedDot} />
                  {label}
                </li>
              ))}
            </ol>
            <p className={styles.emptyNote}>
              {reducedMotion
                ? "Running the deterministic pipeline…"
                : "Stages shown in execution order. The engine returns one result when the full run completes — no partial progress is reported or estimated."}
            </p>
          </div>
        )}

        {error && (
          <div className={styles.error}>
            <CircleAlert size={20} />
            <div>
              <strong>ANALYSIS UNAVAILABLE</strong>
              <span>PreFlight could not complete the analysis. No deployment decision was made.</span>
              <small>{error}</small>
            </div>
            <button onClick={() => setError("")} aria-label="Dismiss error">
              <X size={17} />
            </button>
          </div>
        )}

        {result && (
          <div className={`${styles.report} ${judgeMode ? styles.judgeMode : ""}`}>
            {!judgeMode && (
              <CommandCenter
                result={result}
                scenario={scenario}
                loading={loading}
                onScenarioChange={(next) => analyze(next)}
                onCopyHash={copyHash}
              />
            )}

            {result.change_set && (
              <Section kicker="SHA-256 CONTENT DIFF, OLD VS NEW" title="What changed">
                <ChangeSetPanel
                  changeSet={result.change_set}
                  convergence={result.convergence}
                  schemaChanges={result.schema_changes}
                />
              </Section>
            )}

            {/* Hierarchy: verdict first, then the causal proof, then the
                supporting evidence. */}
            <VerdictHeader result={result} />

            {!judgeMode && result.project_manifest && (
              <ManifestDrawer manifest={result.project_manifest} />
            )}

            {/* The evidence graph is the primary proof surface: change ->
                dependency -> finding -> risk -> policy -> verdict, rendered
                entirely from backend-supplied nodes and edges. */}
            <Section
              kicker="CHANGE → DEPENDENCY → FINDING → POLICY → VERDICT"
              title="Evidence graph"
            >
              <EvidenceCanvas result={result} highlightFeature={highlightFeature} />
            </Section>

            {!judgeMode && result.structural_diff && result.structural_diff.changes.length > 0 && (
              <Section kicker="PARSER-ESTABLISHED DECLARATIONS" title="Structural source changes">
                <StructuralChangesPanel diff={result.structural_diff} />
              </Section>
            )}

            <Section kicker="WHAT COULD ACTUALLY BE ANALYZED" title="Project understanding">
              <CapabilityMatrix result={result} />
            </Section>

            {!judgeMode && result.project_manifest && (
              <Section kicker="WHAT WAS UPLOADED" title="Project manifest">
                <ProjectManifestPanel manifest={result.project_manifest} />
              </Section>
            )}

            <Section kicker="WHAT DROVE THE SCORE" title="Risk calculation">
              <RiskBreakdown
                report={result.decision_report}
                capabilities={result.capabilities}
                onHoverFeature={setHighlightFeature}
              />
            </Section>

            {!judgeMode && (
              <Section kicker="CAUSAL DEPENDENCY GRAPH" title="Blast radius">
                <BlastRadiusGraph
                  blastRadius={result.blast_radius}
                  graph={result.graph}
                  capability={result.capabilities.blast_radius}
                />
              </Section>
            )}

            {!judgeMode && (
              <Section kicker="EVIDENCE OVER CLAIMS" title="Deployment findings">
                <FindingsPanel findings={result.decision_report.findings} />
              </Section>
            )}

            {!judgeMode && (
              <Section kicker="SQLGLOT-PARSED" title="Database rehearsal">
                <SchemaRehearsal result={result} />
              </Section>
            )}

            <Section kicker="DEPLOYMENT TIME MACHINE" title="Rollback truth">
              <RollbackTimeMachine rollback={result.rollback} />
            </Section>

            {!judgeMode && (
              <Section kicker="STRUCTURAL CONTRACT DIFF" title="API contract">
                <ApiContractPanel apiContract={result.api_contract} />
              </Section>
            )}

            {!judgeMode && !result.project_manifest && (
              <Section kicker="SAME ENGINE. DIFFERENT REAL CHANGE." title="What if?">
                <Counterfactual
                  current={result}
                  scenario={scenario}
                  onAdopt={adoptResult}
                />
              </Section>
            )}

            {!judgeMode && (
              <Section
                id="decision-trace"
                kicker="ORDERED PIPELINE EXECUTION"
                title="Decision trace"
              >
                <DecisionTrace result={result} />
              </Section>
            )}

            {!judgeMode && (
              <Section kicker="ADVISORY · NON-AUTHORITATIVE" title="Explanation layer">
                <AiExplanation explanation={result.explanation} />
              </Section>
            )}

            {!judgeMode && (
              <Section kicker="PRECISION OVER MARKETING" title="Analysis coverage">
                <CoverageStatus result={result} />
              </Section>
            )}

            {judgeMode && (
              <p className={styles.judgeFootnote}>
                Judge mode hides secondary sections only. No evidence is altered or withheld — exit
                to see findings, database rehearsal, API contract, decision trace, and the full
                manifest.
              </p>
            )}
          </div>
        )}
      </section>

      <footer className={styles.footer}>
        <span>
          <ShieldCheck size={14} /> PRE·FLIGHT
        </span>
        <span>THE ENGINE DECIDES. THE EVIDENCE PROVES IT. AI EXPLAINS IT.</span>
        <span className={styles.footerLinks}>
          TREE-SITTER · SQLGLOT · OPENAPI · DETERMINISTIC POLICY ·{" "}
          <a href="https://github.com">GitHub ↗</a>
        </span>
      </footer>
    </main>
  );
}
