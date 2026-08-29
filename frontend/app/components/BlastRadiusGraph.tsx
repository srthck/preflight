"use client";

import { useMemo, useState } from "react";
import { ArrowRight, CircleSlash, Database, GitBranch, X } from "lucide-react";
import styles from "../page.module.css";
import type { BlastRadiusFinding, BlastRadiusReport, CapabilityEntry, Graph } from "../../lib/api";
import { evidenceLabel } from "./format";

function kindOf(graph: Graph, entityId: string): string {
  return graph.entities.find((e) => e.entity_id === entityId)?.kind ?? "UNKNOWN";
}

export function BlastRadiusGraph({
  blastRadius,
  graph,
  capability,
}: {
  blastRadius: BlastRadiusReport;
  graph: Graph;
  capability: CapabilityEntry;
}) {
  const [selected, setSelected] = useState<BlastRadiusFinding | null>(null);
  const wasAnalyzed = capability.status === "ANALYZED";

  const columns = useMemo(() => {
    const byHop = new Map<number, BlastRadiusFinding[]>();
    for (const finding of blastRadius.findings) {
      const list = byHop.get(finding.hop_distance) ?? [];
      list.push(finding);
      byHop.set(finding.hop_distance, list);
    }
    return Array.from(byHop.entries()).sort(([a], [b]) => a - b);
  }, [blastRadius.findings]);

  const rootKind = kindOf(graph, blastRadius.target);

  return (
    <article className={styles.panel} id="blast-radius">
      <div className={styles.panelTitle}>
        <span>BLAST RADIUS — CAUSAL DEPENDENCY GRAPH</span>
        <small>
          {wasAnalyzed ? (
            <>
              {blastRadius.summary.affected_count} affected · {blastRadius.summary.direct_count} direct
              · {blastRadius.summary.indirect_count} indirect · bounded to {blastRadius.max_hops} hops
            </>
          ) : (
            capability.status.replaceAll("_", " ")
          )}
        </small>
      </div>

      {!wasAnalyzed ? (
        <p className={styles.coverageWarn}>
          <CircleSlash size={14} />
          <span>{capability.detail} This is not the same as zero impact — the analysis did not run.</span>
        </p>
      ) : blastRadius.findings.length === 0 ? (
        <p className={styles.emptyNote}>
          Analyzed: <code>{blastRadius.target}</code> has zero downstream dependents in the semantic
          graph. This is a computed result, not a missing one.
        </p>
      ) : (
        <div className={styles.graphScroll}>
          <div className={styles.graphFlow}>
            <div className={styles.graphColumn}>
              <div className={styles.graphColumnLabel}>ROOT MUTATION · HOP 0</div>
              <div className={`${styles.graphNode} ${styles.graphNodeRoot}`}>
                <Database size={13} />
                <span>{blastRadius.target}</span>
                <small>{rootKind}</small>
              </div>
            </div>
            {columns.map(([hop, findings]) => (
              <div className={styles.graphColumn} key={hop}>
                <div className={styles.graphColumnLabel}>
                  {hop === 1 ? "DIRECT IMPACT" : "INDIRECT IMPACT"} · HOP {hop}
                </div>
                {findings.map((finding) => (
                  <button
                    // Keyed by cause AND entity: in a convergence the same
                    // downstream entity legitimately appears once per causal
                    // path, so keying on the entity alone collides.
                    key={`${finding.target}:${finding.affected_entity}`}
                    className={`${styles.graphNode} ${
                      finding.category === "DIRECT" ? styles.graphNodeDirect : styles.graphNodeIndirect
                    } ${selected?.affected_entity === finding.affected_entity ? styles.graphNodeSelected : ""}`}
                    onClick={() => setSelected(finding)}
                    aria-pressed={selected?.affected_entity === finding.affected_entity}
                  >
                    <GitBranch size={13} />
                    <span>{finding.affected_entity}</span>
                    <small>
                      {kindOf(graph, finding.affected_entity)} · severity {finding.severity.toFixed(3)}
                    </small>
                    <em>{finding.path.edge_types[finding.path.edge_types.length - 1]}</em>
                  </button>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className={styles.legend}>
        <span>
          <i className={styles.legendDotRoot} /> Root mutation
        </span>
        <span>
          <i className={styles.legendDotDirect} /> Direct impact (1 hop)
        </span>
        <span>
          <i className={styles.legendDotIndirect} /> Indirect impact (2+ hops)
        </span>
        <span>Click a node for evidence provenance</span>
      </div>

      {selected && (
        <div className={styles.inspector} role="dialog" aria-label={`Evidence for ${selected.affected_entity}`}>
          <div className={styles.inspectorHead}>
            <div>
              <div className={styles.kicker}>EVIDENCE PROVENANCE</div>
              <strong>{selected.affected_entity}</strong>
            </div>
            <button onClick={() => setSelected(null)} aria-label="Close evidence panel">
              <X size={16} />
            </button>
          </div>
          <div className={styles.pathChain}>
            {selected.path.nodes.map((node, i) => (
              <div className={styles.pathChainNode} key={node}>
                <span className={node === blastRadius.target ? styles.changed : ""}>{node}</span>
                {i < selected.path.nodes.length - 1 && (
                  <>
                    <ArrowRight size={13} />
                    <small>{selected.path.edge_types[i]}</small>
                  </>
                )}
              </div>
            ))}
          </div>
          <p className={styles.reasonText}>{selected.reason}</p>
          <div className={styles.evidenceList}>
            {selected.path.evidence.length === 0 ? (
              <p className={styles.emptyNote}>No source-level evidence attached to this edge.</p>
            ) : (
              selected.path.evidence.map((item, i) => (
                <div className={styles.evidenceCard} key={i}>
                  {evidenceLabel(item).map((row) => (
                    <div key={row.key} className={styles.evidenceRow}>
                      <span>{row.key.replaceAll("_", " ")}</span>
                      <code>{row.value}</code>
                    </div>
                  ))}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </article>
  );
}
