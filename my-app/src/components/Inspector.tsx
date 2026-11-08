"use client";

import { useState } from "react";
import type { GraphIndex } from "@/lib/graph/model";
import { boundaryOf } from "@/lib/graph/model";
import type { Focus } from "@/lib/focus";

interface Props {
  index: GraphIndex;
  nodeId: string;
  focus: Focus | null;
  onSelect(id: string | null): void;
  onGenerateTests(id: string): void;
  /** Tenets whose code links cover this node's file. */
  tenets?: { id: string; name: string; rollup: string }[];
  onOpenTenet?(id: string): void;
}

function IO({ label, map }: { label: string; map: Record<string, string> }) {
  const entries = Object.entries(map);
  if (!entries.length) return null;
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        {entries.map(([k, v]) => (
          <span key={k} className="io">
            <code>{k}</code> {v}
          </span>
        ))}
      </dd>
    </div>
  );
}

export function Inspector({ index, nodeId, focus, onSelect, onGenerateTests, tenets, onOpenTenet }: Props) {
  const [copied, setCopied] = useState(false);
  const node = index.nodes.get(nodeId);
  if (!node) return null;

  const ids = [...index.nodes.keys()];
  const downstream = (index.out.get(nodeId) ?? []).map((e) => ({ id: e.target, relation: e.relation }));
  const upstream = (index.in.get(nodeId) ?? []).map((e) => ({ id: e.source, relation: e.relation }));
  const external = index.dangling.get(nodeId) ?? [];

  async function copyContext() {
    if (!focus) return;
    try {
      await navigator.clipboard.writeText(focus.context);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      /* clipboard blocked */
    }
  }

  const DepList = ({ items, empty }: { items: { id: string; relation: string }[]; empty: string }) => (
    <div className="dependencies">
      {items.length ? (
        items.map((d) => (
          <button key={d.id + d.relation} onClick={() => onSelect(d.id)} title={d.relation.replace(/_/g, " ")}>
            {d.id}
          </button>
        ))
      ) : (
        <span>{empty}</span>
      )}
    </div>
  );

  return (
    <aside className="inspector" aria-label="Intent node inspector">
      <button className="close-inspector" onClick={() => onSelect(null)} aria-label="Close inspector">
        ×
      </button>
      <span className="eyebrow">
        INTENT NODE {ids.indexOf(nodeId) + 1}/{ids.length}
      </span>
      <h2>{node.name}</h2>
      <code>{node.node_id}</code>
      <dl>
        <div>
          <dt>source</dt>
          <dd>{node.source_file}</dd>
        </div>
        <div>
          <dt>intent</dt>
          <dd>{node.intent_summary}</dd>
        </div>
        <div>
          <dt>boundary</dt>
          <dd>{boundaryOf(node)}</dd>
        </div>
        <IO label="inputs" map={node.inputs} />
        <IO label="outputs" map={node.outputs} />
      </dl>

      <h3>Business invariants</h3>
      {node.business_invariants.length ? (
        <ol>
          {node.business_invariants.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ol>
      ) : (
        <p className="muted">none mapped</p>
      )}

      {tenets?.length ? (
        <>
          <h3>Constrained by tenets</h3>
          <div className="dependencies">
            {tenets.map((t) => (
              <button key={t.id} onClick={() => onOpenTenet?.(t.id)} title={`${t.rollup}: open in tenet hierarchy`}>
                {t.name}
              </button>
            ))}
          </div>
        </>
      ) : null}

      <h3>Downstream dependencies</h3>
      <DepList items={downstream} empty="terminal boundary" />
      {external.length ? (
        <div className="dependencies external">
          {external.map((id) => (
            <span key={id} title="referenced but not in the graph">
              {id} ↗
            </span>
          ))}
        </div>
      ) : null}

      <h3>Depended on by</h3>
      <DepList items={upstream} empty="entry point" />

      {focus ? (
        <>
          <h3>Retrieved context</h3>
          <p className="context-meta">
            {focus.nodeIds.size} nodes · ~{focus.tokens} tokens
            <button onClick={copyContext}>{copied ? "copied ✓" : "copy"}</button>
          </p>
        </>
      ) : null}

      <button className="generate" onClick={() => onGenerateTests(nodeId)}>
        generate invariant tests
      </button>
    </aside>
  );
}
