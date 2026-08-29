// Deterministic layout for the materialized evidence graph.
//
// Computes *positions only*. It never decides what a node means, whether an
// analyzer ran, or what the verdict is — those are backend facts carried on
// the node. Given the same backend graph it always produces the same
// coordinates, so the visual is as reproducible as the analysis.
//
// Layout is two stacked bands, which is both a readability fix and the
// two-layer model the evidence model calls for:
//
//   BAND A — SYSTEM IMPACT : change -> changed entity -> direct -> downstream
//   BAND B — DECISION PROOF: finding -> risk feature -> policy -> verdict
//
// A single 8-column row measured ~2330px and overflowed the container at
// 1440px, pushing the verdict off-screen entirely. Two bands of four columns
// fit within ~1090px, and the edges that cross from band A into band B are
// exactly the "evidence becomes consequence" link worth seeing.

import type { EvidenceEdge, EvidenceGraph, EvidenceNode } from "../../lib/api";

export type PositionedNode = EvidenceNode & { x: number; y: number; column: number; band: 0 | 1 };
export type PositionedEdge = EvidenceEdge & {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  path: string;
  crossBand: boolean;
};

export type EvidenceLayout = {
  nodes: PositionedNode[];
  edges: PositionedEdge[];
  width: number;
  height: number;
  columns: { index: number; label: string; x: number; y: number }[];
  bands: { label: string; y: number; height: number }[];
  /** Shared waypoint the TRIGGERS edges route through, when bundled. */
  policyJunction: { x: number; y: number } | null;
};

export const NODE_WIDTH = 186;
export const NODE_HEIGHT = 60;
const COLUMN_GAP = 86;
const ROW_GAP = 18;
const PADDING_X = 24;
// Tall enough for the band label to clear the per-column labels beneath it;
// at 26px the two collided ("SYSTEM IMPACT" overlapped "CHANGE").
const BAND_LABEL_H = 44;
const BAND_GAP = 52;

const COLUMN_LABELS = [
  "CHANGE",
  "CHANGED ENTITY",
  "DIRECT IMPACT",
  "DOWNSTREAM",
  "FINDINGS",
  "RISK",
  "POLICY",
  "VERDICT",
];

// Columns 0-3 are the system-impact band; 4-7 are the decision-proof band.
const BAND_OF_COLUMN = (column: number): 0 | 1 => (column <= 3 ? 0 : 1);

function columnFor(node: EvidenceNode): number {
  if (node.kind === "CHANGE") return 0;
  if (node.layer >= 93) return 7;
  if (node.layer === 92) return 6;
  if (node.layer === 91) return 5;
  if (node.layer === 90) return 4;
  return Math.min(1 + node.layer, 3);
}

export function layoutEvidenceGraph(graph: EvidenceGraph): EvidenceLayout {
  const byColumn = new Map<number, EvidenceNode[]>();
  for (const node of graph.nodes) {
    const column = columnFor(node);
    const bucket = byColumn.get(column);
    if (bucket) bucket.push(node);
    else byColumn.set(column, [node]);
  }

  const used = Array.from(byColumn.keys()).sort((a, b) => a - b);
  const bandColumns: number[][] = [
    used.filter((c) => BAND_OF_COLUMN(c) === 0),
    used.filter((c) => BAND_OF_COLUMN(c) === 1),
  ];

  // Each band packs its own columns from the left, so an empty column never
  // leaves a visual hole.
  const columnX = new Map<number, number>();
  for (const columns of bandColumns) {
    columns.forEach((column, index) => {
      columnX.set(column, PADDING_X + index * (NODE_WIDTH + COLUMN_GAP));
    });
  }

  const bandHeight = (columns: number[]): number => {
    const tallest = Math.max(...columns.map((c) => byColumn.get(c)?.length ?? 0), 1);
    return tallest * NODE_HEIGHT + (tallest - 1) * ROW_GAP;
  };
  const heightA = bandColumns[0].length > 0 ? bandHeight(bandColumns[0]) : 0;
  const heightB = bandColumns[1].length > 0 ? bandHeight(bandColumns[1]) : 0;

  const bandY: [number, number] = [
    BAND_LABEL_H,
    BAND_LABEL_H + heightA + BAND_GAP + BAND_LABEL_H,
  ];

  const positioned = new Map<string, PositionedNode>();
  bandColumns.forEach((columns, bandIndex) => {
    const band = bandIndex as 0 | 1;
    const available = band === 0 ? heightA : heightB;
    for (const column of columns) {
      const nodes = byColumn.get(column) ?? [];
      const columnHeight = nodes.length * NODE_HEIGHT + (nodes.length - 1) * ROW_GAP;
      const offset = bandY[band] + (available - columnHeight) / 2;
      nodes.forEach((node, row) => {
        positioned.set(node.id, {
          ...node,
          column,
          band,
          x: columnX.get(column) ?? PADDING_X,
          y: offset + row * (NODE_HEIGHT + ROW_GAP),
        });
      });
    }
  });

  // Every non-zero risk feature is linked to every triggered policy rule,
  // because decide() does not expose which feature fired which rule. Drawing
  // that as N x M individual arrows implies a precise mapping that the data
  // does not support (and rendered as a dense crossing lattice). Routing the
  // TRIGGERS edges through one shared junction is both calmer and more
  // honest: it shows the features feeding policy evaluation collectively.
  const triggerEdges = graph.edges.filter((e) => e.kind === "TRIGGERS");
  const bundleTriggers = triggerEdges.length > 2;
  let junction: { x: number; y: number } | null = null;
  if (bundleTriggers) {
    const sources = triggerEdges
      .map((e) => positioned.get(e.source))
      .filter((n): n is PositionedNode => n !== undefined);
    const targets = triggerEdges
      .map((e) => positioned.get(e.target))
      .filter((n): n is PositionedNode => n !== undefined);
    if (sources.length > 0 && targets.length > 0) {
      const rightOfSources = Math.max(...sources.map((n) => n.x + NODE_WIDTH));
      const leftOfTargets = Math.min(...targets.map((n) => n.x));
      const all = [...sources, ...targets];
      junction = {
        x: rightOfSources + (leftOfTargets - rightOfSources) / 2,
        y: all.reduce((sum, n) => sum + n.y + NODE_HEIGHT / 2, 0) / all.length,
      };
    }
  }

  const edges: PositionedEdge[] = [];
  for (const edge of graph.edges) {
    const source = positioned.get(edge.source);
    const target = positioned.get(edge.target);
    if (!source || !target) continue; // never draw an edge to a node we lack
    const crossBand = source.band !== target.band;

    if (edge.kind === "TRIGGERS" && junction !== null) {
      const sx = source.x + NODE_WIDTH;
      const sy = source.y + NODE_HEIGHT / 2;
      const tx = target.x;
      const ty = target.y + NODE_HEIGHT / 2;
      edges.push({
        ...edge,
        x1: sx,
        y1: sy,
        x2: tx,
        y2: ty,
        crossBand,
        path:
          `M ${sx} ${sy} Q ${(sx + junction.x) / 2} ${sy}, ${junction.x} ${junction.y} ` +
          `Q ${(junction.x + tx) / 2} ${ty}, ${tx} ${ty}`,
      });
      continue;
    }

    let x1: number;
    let y1: number;
    let x2: number;
    let y2: number;
    let path: string;

    if (crossBand) {
      // Leave the bottom of the source, enter the top of the target: the
      // visible "impact becomes consequence" hand-off between the two bands.
      x1 = source.x + NODE_WIDTH / 2;
      y1 = source.y + NODE_HEIGHT;
      x2 = target.x + NODE_WIDTH / 2;
      y2 = target.y;
      const midY = y1 + (y2 - y1) / 2;
      path = `M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`;
    } else {
      x1 = source.x + NODE_WIDTH;
      y1 = source.y + NODE_HEIGHT / 2;
      x2 = target.x;
      y2 = target.y + NODE_HEIGHT / 2;
      const midX = x1 + (x2 - x1) / 2;
      path = `M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`;
    }
    edges.push({ ...edge, x1, y1, x2, y2, path, crossBand });
  }

  const widest = Math.max(
    ...bandColumns.map(
      (columns) =>
        PADDING_X * 2 +
        Math.max(columns.length, 1) * NODE_WIDTH +
        Math.max(columns.length - 1, 0) * COLUMN_GAP,
    ),
    NODE_WIDTH + PADDING_X * 2,
  );

  const columns = used.map((column) => ({
    index: column,
    label: COLUMN_LABELS[column] ?? "",
    x: columnX.get(column) ?? PADDING_X,
    y: bandY[BAND_OF_COLUMN(column)] - 12,
  }));

  const policyJunction = junction;
  const bands: { label: string; y: number; height: number }[] = [];
  if (bandColumns[0].length > 0) {
    bands.push({ label: "SYSTEM IMPACT", y: bandY[0] - BAND_LABEL_H, height: heightA });
  }
  if (bandColumns[1].length > 0) {
    bands.push({ label: "DECISION PROOF", y: bandY[1] - BAND_LABEL_H, height: heightB });
  }

  return {
    nodes: Array.from(positioned.values()),
    edges,
    width: widest,
    height: bandY[1] + heightB + 16,
    columns,
    bands,
    policyJunction,
  };
}

/**
 * The subgraph that actually produced the verdict: walk backwards from the
 * verdict node across real edges. Used by "Why this decision?" to fade
 * everything that did not contribute. Traversal over backend-supplied edges,
 * not an inference about causality.
 */
export function verdictChain(graph: EvidenceGraph): Set<string> {
  const incoming = new Map<string, string[]>();
  for (const edge of graph.edges) {
    const bucket = incoming.get(edge.target);
    if (bucket) bucket.push(edge.source);
    else incoming.set(edge.target, [edge.source]);
  }
  const verdict = graph.nodes.find((n) => n.kind === "VERDICT");
  if (!verdict) return new Set();

  const chain = new Set<string>();
  const stack = [verdict.id];
  while (stack.length > 0) {
    const current = stack.pop();
    if (current === undefined || chain.has(current)) continue;
    chain.add(current);
    stack.push(...(incoming.get(current) ?? []));
  }
  return chain;
}

/** Human-readable causal path for one node, for screen readers and the inspector. */
export function causalPathFor(graph: EvidenceGraph, nodeId: string): string[] {
  const incoming = new Map<string, EvidenceEdge[]>();
  for (const edge of graph.edges) {
    const bucket = incoming.get(edge.target);
    if (bucket) bucket.push(edge);
    else incoming.set(edge.target, [edge]);
  }
  const labels = new Map(graph.nodes.map((n) => [n.id, n.detail || n.label]));

  const path: string[] = [];
  const seen = new Set<string>();
  let current: string | undefined = nodeId;
  while (current !== undefined && !seen.has(current)) {
    seen.add(current);
    path.unshift(labels.get(current) ?? current);
    const parents: EvidenceEdge[] = incoming.get(current) ?? [];
    const dependency: EvidenceEdge | undefined = parents.find(
      (e: EvidenceEdge) => e.kind === "DEPENDS_ON" || e.kind === "AFFECTS",
    );
    current = dependency === undefined ? undefined : dependency.source;
  }
  return path;
}
