"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { GitMerge, Route, X } from "lucide-react";
import styles from "../page.module.css";
import type { AnalysisResult, EvidenceNode } from "../../lib/api";
import { useReducedMotion } from "../../hooks/useReducedMotion";
import {
  causalPathFor,
  layoutEvidenceGraph,
  verdictChain,
  NODE_HEIGHT,
  NODE_WIDTH,
} from "./evidenceLayout";
import { EvidenceGapGraph } from "./EvidenceGapGraph";
import { SourceEvidence } from "./SourceEvidence";

// Reveal cadence for the causal animation. This animates the presentation of
// evidence that has ALREADY been returned — it is never presented as analysis
// latency, and real backend timing is reported separately.
const LAYER_REVEAL_MS = 240;

const KIND_LABEL: Record<string, string> = {
  CHANGE: "CHANGE",
  SCHEMA_ENTITY: "DATABASE",
  SOURCE_SYMBOL: "SYMBOL",
  SERVICE: "SERVICE",
  API_ENDPOINT: "API",
  CLIENT: "CLIENT",
  FINDING: "FINDING",
  RISK_FEATURE: "RISK",
  POLICY_RULE: "POLICY",
  VERDICT: "VERDICT",
};

// Which risk feature a node belongs to, for the risk<->graph highlight.
// Derived from the node's own backend-supplied identity, never guessed.
function featureOf(node: EvidenceNode): string | null {
  if (node.kind === "RISK_FEATURE") {
    const feature = node.metadata.feature;
    return typeof feature === "string" ? feature : null;
  }
  return null;
}

function toneFor(node: EvidenceNode, decision: string): string {
  if (node.kind === "VERDICT") {
    if (decision === "SAFE") return "safe";
    if (decision === "DO_NOT_DEPLOY") return "danger";
    if (decision === "CAUTION") return "warn";
    return "unknown";
  }
  if (node.severity === "CRITICAL" || node.severity === "HIGH") return "danger";
  if (node.severity === "MEDIUM") return "warn";
  return "neutral";
}

export function EvidenceCanvas({
  result,
  highlightFeature,
  focusRequest,
}: {
  result: AnalysisResult;
  /** Risk feature hovered in the risk panel — highlights its contributing evidence. */
  highlightFeature?: string | null;
  /** Node-kind family requested by the coverage panel, e.g. "SCHEMA_ENTITY". */
  focusRequest?: string | null;
}) {
  const graph = result.evidence_graph;
  const decision = result.decision_report.decision;
  const reducedMotion = useReducedMotion();

  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [whyMode, setWhyMode] = useState(false);
  const [activeRoot, setActiveRoot] = useState<string | null>(null);
  const [showConvergence, setShowConvergence] = useState(false);
  const [revealedColumns, setRevealedColumns] = useState(0);

  const layout = useMemo(() => layoutEvidenceGraph(graph), [graph]);
  const chain = useMemo(() => verdictChain(graph), [graph]);
  const columnCount = layout.columns.length;

  // Morph bookkeeping: when the report is swapped for another completed
  // analysis, nodes present in both graphs keep their identity (and their
  // position, since layout is deterministic), while nodes unique to the new
  // graph are marked as entering. Both graphs are real engine output; only
  // the transition between them is presentational.
  const previousIds = useRef<Set<string>>(new Set());
  const previousHash = useRef<string>("");
  const [enteringIds, setEnteringIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (previousHash.current === graph.graph_hash) return;
    const currentIds = new Set(graph.nodes.map((n) => n.id));
    const isFirstRender = previousHash.current === "";
    const entering = isFirstRender
      ? new Set<string>()
      : new Set(Array.from(currentIds).filter((id) => !previousIds.current.has(id)));
    setEnteringIds(entering);
    previousIds.current = currentIds;
    previousHash.current = graph.graph_hash;
    if (entering.size === 0) return;
    const timer = setTimeout(() => setEnteringIds(new Set()), 700);
    return () => clearTimeout(timer);
  }, [graph.graph_hash, graph.nodes]);

  // Edges carry the changed target they were reached from, so filtering by a
  // change root is a backend-data filter, not a frontend re-derivation.
  const rootFilteredIds = useMemo(() => {
    if (activeRoot === null) return null;
    const rootNode = graph.nodes.find((n) => n.id === activeRoot);
    const target =
      rootNode && typeof rootNode.metadata.schema_object === "string"
        ? rootNode.metadata.schema_object
        : null;
    if (target === null) return null;
    const keep = new Set<string>([activeRoot]);
    for (const edge of graph.edges) {
      if (edge.via_target === target) {
        keep.add(edge.source);
        keep.add(edge.target);
      }
    }
    return keep;
  }, [activeRoot, graph]);

  useEffect(() => {
    if (reducedMotion) {
      setRevealedColumns(columnCount);
      return;
    }
    setRevealedColumns(0);
    let current = 0;
    const timer = setInterval(() => {
      current += 1;
      setRevealedColumns(current);
      if (current >= columnCount) clearInterval(timer);
    }, LAYER_REVEAL_MS);
    return () => clearInterval(timer);
  }, [graph.graph_hash, columnCount, reducedMotion]);

  useEffect(() => {
    if (!focusRequest) return;
    const match = graph.nodes.find((n) => n.kind === focusRequest);
    if (match) setSelected(match.id);
  }, [focusRequest, graph.nodes]);

  const changeRoots = graph.nodes.filter((n) => n.kind === "CHANGE");
  const selectedNode = selected ? layout.nodes.find((n) => n.id === selected) : null;
  const path = selectedNode ? causalPathFor(graph, selectedNode.id) : [];

  // Neighbours of the hovered node, so hover can illuminate its own edges.
  const hoverNeighbours = useMemo(() => {
    if (hovered === null) return null;
    const near = new Set<string>([hovered]);
    for (const edge of graph.edges) {
      if (edge.source === hovered) near.add(edge.target);
      if (edge.target === hovered) near.add(edge.source);
    }
    return near;
  }, [hovered, graph.edges]);

  // A graph with no causal roots is an evidence gap, not an empty diagram.
  if (graph.roots.length === 0) {
    return <EvidenceGapGraph result={result} />;
  }

  const columnVisible = (column: number) =>
    layout.columns.findIndex((c) => c.index === column) < revealedColumns;

  // Hover should EMPHASIZE a neighbourhood, not erase the rest of the graph.
  // At the full dim level a casual mouse-over made most of the diagram
  // disappear, which read as broken rather than focused.
  const nodeSoftDimmed = (node: EvidenceNode): boolean =>
    hoverNeighbours !== null && !hoverNeighbours.has(node.id) && !nodeDimmed(node);

  const nodeDimmed = (node: EvidenceNode): boolean => {
    if (whyMode && !chain.has(node.id)) return true;
    if (rootFilteredIds !== null && !rootFilteredIds.has(node.id)) return true;
    if (highlightFeature) {
      // Highlight the risk feature itself, every finding that contributes to
      // it, and every entity that produced one of those findings — i.e. the
      // real evidence behind that contribution, walked over backend edges.
      const contributingFindings = new Set(
        graph.edges
          .filter(
            (e) => e.kind === "CONTRIBUTES_TO" && e.target === `risk:${highlightFeature}`,
          )
          .map((e) => e.source),
      );
      const producesContributor = graph.edges.some(
        (e) => e.source === node.id && e.kind === "PRODUCES" && contributingFindings.has(e.target),
      );
      const isFeature = featureOf(node) === highlightFeature;
      if (!isFeature && !contributingFindings.has(node.id) && !producesContributor) return true;
    }
    return false;
  };

  return (
    <article className={styles.graphPanel}>
      <div className={styles.graphHead}>
        <div>
          <div className={styles.kicker}>CAUSAL PROOF</div>
          <h3 className={styles.graphTitle}>
            {graph.nodes.length} nodes · {graph.edges.length} edges ·{" "}
            {graph.reachable_verdict ? (
              <span className={styles.textTone_safe}>verdict reachable from evidence</span>
            ) : (
              <span className={styles.textTone_unknown}>verdict not reachable from evidence</span>
            )}
          </h3>
        </div>
        <div className={styles.graphActions}>
          <button
            type="button"
            className={`${styles.pillButton} ${whyMode ? styles.pillButtonActive : ""}`}
            onClick={() => setWhyMode((v) => !v)}
            aria-pressed={whyMode}
            disabled={!graph.reachable_verdict}
          >
            <Route size={13} /> Why this decision?
          </button>
        </div>
      </div>

      {/* The ordered causal chain. Dimming alone cannot carry this: on a
          typical graph every node is part of the verdict's ancestry, so
          nothing visibly recedes (measured: 0 of 17 nodes dimmed). The
          explicit ordered steps are the actual explanation, built from the
          same backend chain the dimming uses. */}
      {whyMode && graph.reachable_verdict && (
        <div className={styles.whyPanel}>
          <div className={styles.kicker}>WHY PREFLIGHT REACHED THIS VERDICT</div>
          <h4>Every step below is a node in the evidence graph.</h4>
          <ol className={styles.whySteps}>
            {graph.nodes
              .filter((n) => chain.has(n.id))
              .slice()
              .sort((a, b) => a.layer - b.layer || a.id.localeCompare(b.id))
              .map((node, index) => (
                <li key={node.id} className={styles.whyStep}>
                  <span className={styles.whyIndex}>{String(index + 1).padStart(2, "0")}</span>
                  <div>
                    <div className={styles.whyKind}>{KIND_LABEL[node.kind] ?? node.kind}</div>
                    <div className={styles.whyLabel}>{node.label}</div>
                    {node.detail && <div className={styles.whyDetail}>{node.detail}</div>}
                  </div>
                </li>
              ))}
          </ol>
        </div>
      )}

      {/* Change-root filter: only rendered when the migration really did
          contain more than one change. */}
      {changeRoots.length > 1 && (
        <div className={styles.graphFilterRow}>
          <span className={styles.graphFilterLabel}>{changeRoots.length} CHANGE ROOTS</span>
          <button
            type="button"
            className={`${styles.pillButton} ${activeRoot === null ? styles.pillButtonActive : ""}`}
            onClick={() => setActiveRoot(null)}
          >
            All changes
          </button>
          {changeRoots.map((root) => (
            <button
              key={root.id}
              type="button"
              className={`${styles.pillButton} ${activeRoot === root.id ? styles.pillButtonActive : ""}`}
              onClick={() => setActiveRoot(activeRoot === root.id ? null : root.id)}
            >
              {typeof root.metadata.schema_object === "string"
                ? root.metadata.schema_object
                : root.label}
            </button>
          ))}
        </div>
      )}

      {graph.convergence.length > 0 && (
        <button
          type="button"
          className={styles.convergenceBanner}
          onClick={() => setShowConvergence((v) => !v)}
          aria-expanded={showConvergence}
        >
          <GitMerge size={14} />
          <span>
            <b>CONVERGENCE</b> — {graph.convergence.length} shared downstream{" "}
            {graph.convergence.length === 1 ? "entity" : "entities"} reached by independent changes
          </span>
        </button>
      )}
      {showConvergence && (
        <div className={styles.convergenceDetail}>
          <div className={styles.subKicker}>WHY THIS MATTERS</div>
          <p>
            Independent changes reach the same downstream system. Each cause alone would be a
            separate finding; together they concentrate risk on one entity.
          </p>
          {graph.convergence.map((c) => (
            <div key={c.entity} className={styles.convergenceItem}>
              <div className={styles.convergenceShared}>
                <span className={styles.kicker}>SHARED ENTITY</span>
                <code>{c.entity}</code>
              </div>
              <div className={styles.convergenceCauses}>
                {c.targets.map((t, i) => (
                  <div key={t}>
                    <span className={styles.kicker}>CAUSE {String.fromCharCode(65 + i)}</span>
                    <code>{t}</code>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className={styles.graphScroll}>
        <svg
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          width={layout.width}
          height={layout.height}
          preserveAspectRatio="xMinYMin meet"
          role="img"
          aria-label="Causal evidence graph from change to verdict"
          className={styles.graphSvg}
        >
          <defs>
            <marker
              id="pf-arrow"
              viewBox="0 0 8 8"
              refX="7"
              refY="4"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 1 L 7 4 L 0 7" fill="none" stroke="currentColor" strokeWidth="1" />
            </marker>
          </defs>

          {layout.bands.map((band) => (
            <text key={band.label} x={0} y={band.y + 10} className={styles.graphBandLabel}>
              {band.label}
            </text>
          ))}
          {layout.columns.map((column) => (
            <text
              key={column.index}
              x={column.x}
              y={column.y}
              className={styles.graphColumnLabel}
              opacity={columnVisible(column.index) ? 1 : 0}
            >
              {column.label}
            </text>
          ))}

          <g>
            {layout.edges.map((edge, index) => {
              const endpointsDim =
                nodeDimmed(
                  layout.nodes.find((n) => n.id === edge.source) ?? layout.nodes[0],
                ) ||
                nodeDimmed(layout.nodes.find((n) => n.id === edge.target) ?? layout.nodes[0]);
              const targetNode = layout.nodes.find((n) => n.id === edge.target);
              const visible = targetNode ? columnVisible(targetNode.column) : false;
              const emphasized =
                hoverNeighbours !== null &&
                (edge.source === hovered || edge.target === hovered);
              return (
                <path
                  key={`${edge.source}-${edge.target}-${edge.kind}-${edge.via_target ?? ""}-${index}`}
                  d={edge.path}
                  className={`${styles.graphEdge} ${emphasized ? styles.graphEdgeLive : ""} ${edge.crossBand ? styles.graphEdgeCross : ""}`}
                  markerEnd="url(#pf-arrow)"
                  opacity={
                    visible
                      ? endpointsDim
                        ? 0.07
                        : emphasized
                          ? 0.9
                          : edge.crossBand
                            ? 0.2
                            : 0.5
                      : 0
                  }
                >
                  <title>
                    {edge.kind}
                    {edge.label ? ` · ${edge.label}` : ""}
                    {edge.via_target ? ` · via ${edge.via_target}` : ""}
                  </title>
                </path>
              );
            })}

            {/* The bundling waypoint, labelled so the aggregation is stated
                rather than implied. decide() does not expose which risk
                feature fired which policy rule, so the graph must not draw
                one-to-one arrows that would assert a mapping it cannot prove. */}
            {layout.policyJunction && (
              <g className={styles.policyJunction}>
                <circle cx={layout.policyJunction.x} cy={layout.policyJunction.y} r={3.5}>
                  <title>
                    All contributing risk features feed policy evaluation collectively. The engine
                    does not report which feature triggered which rule.
                  </title>
                </circle>
                {/* Lifted clear of the node row: at -12 the centred label
                    ran across the first policy node's box and swallowed its
                    kind label. -34 puts it in the gap between rows, and the
                    halo in .policyJunctionLabel covers the remaining cases
                    where a denser graph closes that gap. */}
                <text
                  x={layout.policyJunction.x}
                  y={layout.policyJunction.y - 34}
                  textAnchor="middle"
                  className={styles.policyJunctionLabel}
                >
                  POLICY EVALUATION
                </text>
              </g>
            )}

            {layout.nodes.map((node) => {
              const tone = toneFor(node, decision);
              const dimmed = nodeDimmed(node);
              const isSelected = selected === node.id;
              const visible = columnVisible(node.column);
              const isConvergent = graph.convergence.some(
                (c) => `entity:${c.entity}` === node.id,
              );
              return (
                <g
                  key={node.id}
                  transform={`translate(${node.x}, ${node.y})`}
                  className={`${styles.graphNode} ${dimmed ? styles.graphDimmed : ""} ${
                    nodeSoftDimmed(node) ? styles.graphSoftDimmed : ""
                  } ${enteringIds.has(node.id) ? styles.graphNodeEntering : ""}`}
                  opacity={visible ? 1 : 0}
                  role="button"
                  tabIndex={0}
                  aria-label={`${KIND_LABEL[node.kind] ?? node.kind}: ${node.label}. ${node.detail}`}
                  onClick={() => setSelected(isSelected ? null : node.id)}
                  onMouseEnter={() => setHovered(node.id)}
                  onMouseLeave={() => setHovered(null)}
                  onFocus={() => setHovered(node.id)}
                  onBlur={() => setHovered(null)}
                  onKeyDown={(event) => {
                    // Enter/Space select, Escape closes, arrows move between
                    // nodes in the graph's own deterministic order so the
                    // whole chain is reachable without a pointer.
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setSelected(isSelected ? null : node.id);
                      return;
                    }
                    if (event.key === "Escape") {
                      setSelected(null);
                      return;
                    }
                    const step =
                      event.key === "ArrowRight" || event.key === "ArrowDown"
                        ? 1
                        : event.key === "ArrowLeft" || event.key === "ArrowUp"
                          ? -1
                          : 0;
                    if (step === 0) return;
                    event.preventDefault();
                    const order = layout.nodes;
                    const at = order.findIndex((n) => n.id === node.id);
                    const next = order[(at + step + order.length) % order.length];
                    if (!next) return;
                    const target = event.currentTarget.parentElement?.querySelector<SVGGElement>(
                      `[data-node-id="${CSS.escape(next.id)}"]`,
                    );
                    target?.focus();
                  }}
                  data-node-id={node.id}
                >
                  <rect
                    width={NODE_WIDTH}
                    height={NODE_HEIGHT}
                    rx={9}
                    className={`${styles.graphNodeBox} ${styles[`graphTone_${tone}`]} ${
                      isSelected ? styles.graphNodeSelected : ""
                    }`}
                  />
                  {isConvergent && (
                    <circle
                      cx={NODE_WIDTH - 13}
                      cy={13}
                      r={4}
                      className={styles.convergenceDot}
                    >
                      <title>Convergence point — reached by more than one change</title>
                    </circle>
                  )}
                  <text x={14} y={23} className={styles.graphNodeKind}>
                    {KIND_LABEL[node.kind] ?? node.kind}
                    {node.hop_distance !== null && node.kind !== "CHANGE"
                      ? ` · HOP ${node.hop_distance}`
                      : ""}
                  </text>
                  <text x={14} y={44} className={styles.graphNodeLabel}>
                    {node.label.length > 23 ? `${node.label.slice(0, 22)}…` : node.label}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>
      </div>

      {/* Non-visual equivalent: the evidence must never depend on seeing or
          animating the graph. */}
      <details className={styles.graphTextChain}>
        <summary>Causal chain as text</summary>
        <ol>
          {graph.roots.map((rootId) => {
            const root = graph.nodes.find((n) => n.id === rootId);
            return (
              <li key={rootId}>
                {root?.label ?? rootId}
                {root?.detail ? ` — ${root.detail}` : ""}
              </li>
            );
          })}
        </ol>
        {graph.convergence.map((c) => (
          <p key={c.entity}>
            Convergence: {c.entity} is reached from {c.targets.length} independent changes (
            {c.targets.join(", ")}).
          </p>
        ))}
      </details>

      {selectedNode && (
        <aside className={styles.inspector} aria-label="Evidence inspector">
          <div className={styles.inspectorHead}>
            <div>
              <div className={styles.kicker}>
                {KIND_LABEL[selectedNode.kind] ?? selectedNode.kind}
                {selectedNode.hop_distance !== null && selectedNode.kind !== "CHANGE"
                  ? ` · HOP ${selectedNode.hop_distance}`
                  : ""}
              </div>
              <strong>{selectedNode.label}</strong>
            </div>
            <button type="button" onClick={() => setSelected(null)} aria-label="Close inspector">
              <X size={15} />
            </button>
          </div>

          <p className={styles.inspectorDetail}>{selectedNode.detail}</p>

          {path.length > 1 && (
            <>
              <div className={styles.subKicker}>CAUSAL PATH</div>
              <ol className={styles.causalPath}>
                {path.map((step, index) => (
                  <li key={`${step}-${index}`}>
                    <code>{step}</code>
                  </li>
                ))}
              </ol>
            </>
          )}

          <SourceEvidence provenance={selectedNode.provenance} />
        </aside>
      )}
    </article>
  );
}
