"use client";

import { useState } from "react";
import type { GraphIndex } from "@/lib/graph/model";
import { boundaryOf } from "@/lib/graph/model";
import type { Focus } from "@/lib/focus";
import { Block, CopyChip, Panel } from "@/components/panel/Panel";

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

type Tab = "intent" | "links" | "context";

/** A flow row: a name and its type/meaning. */
function Flow({ label, map }: { label: string; map: Record<string, string> }) {
  const entries = Object.entries(map);
  return (
    <div className="pn-flow">
      <span className="pn-flow-label">{label}</span>
      {entries.length ? (
        <ul>
          {entries.map(([k, v]) => (
            <li key={k}>
              <code>{k}</code>
              <span>{v}</span>
            </li>
          ))}
        </ul>
      ) : (
        <em>nothing</em>
      )}
    </div>
  );
}

export function Inspector({ index, nodeId, focus, onSelect, onGenerateTests, tenets, onOpenTenet }: Props) {
  const [tab, setTab] = useState<Tab>("intent");
  const [copied, setCopied] = useState(false);
  const node = index.nodes.get(nodeId);
  if (!node) return null;

  const ids = [...index.nodes.keys()];
  const at = ids.indexOf(nodeId);
  const go = (d: number) => onSelect(ids[(at + d + ids.length) % ids.length]);

  const downstream = (index.out.get(nodeId) ?? []).map((e) => ({ id: e.target, relation: e.relation }));
  const upstream = (index.in.get(nodeId) ?? []).map((e) => ({ id: e.source, relation: e.relation }));
  const external = index.dangling.get(nodeId) ?? [];
  const nameOf = (id: string) => index.nodes.get(id)?.name ?? id;
  const linkCount = upstream.length + downstream.length + (tenets?.length ?? 0);

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

  const chips = (items: { id: string; relation: string }[], empty: string) =>
    items.length ? (
      <div className="pn-chips">
        {items.map((d) => (
          <button key={d.id + d.relation} onClick={() => onSelect(d.id)} title={d.relation.replace(/_/g, " ")}>
            <b>{nameOf(d.id)}</b>
            <small>{d.relation.replace(/_/g, " ")}</small>
          </button>
        ))}
      </div>
    ) : (
      <p className="pn-empty">{empty}</p>
    );

  return (
    <Panel
      label="Intent node inspector"
      eyebrow={
        <>
          <i className="pn-dot" /> intent node
        </>
      }
      title={node.name}
      sub={<CopyChip text={node.source_file} />}
      tabs={[
        { id: "intent", label: "Intent", count: node.business_invariants.length },
        { id: "links", label: "Links", count: linkCount },
        { id: "context", label: "Context" },
      ]}
      tab={tab}
      onTab={(t) => setTab(t as Tab)}
      onClose={() => onSelect(null)}
      step={{ onPrev: () => go(-1), onNext: () => go(1), position: `${at + 1}/${ids.length}` }}
      footer={
        <button className="pn-cta" onClick={() => onGenerateTests(nodeId)}>
          <span>Generate invariant tests</span>
          <i aria-hidden>→</i>
        </button>
      }
    >
      {tab === "intent" ? (
        <>
          <p className="pn-lead">{node.intent_summary}</p>
          <div className="pn-meta">
            <span className="pn-badge" title="architectural boundary">
              ⬡ {boundaryOf(node)}
            </span>
            <small>{node.node_id}</small>
          </div>

          <Block title="Business invariants" aside={node.business_invariants.length ? `${node.business_invariants.length} rules` : undefined}>
            {node.business_invariants.length ? (
              <ol className="pn-rules">
                {node.business_invariants.map((item, i) => (
                  <li key={item} style={{ ["--i" as string]: i }}>
                    <span>{i + 1}</span>
                    <p>{item}</p>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="pn-empty">No invariants mapped yet.</p>
            )}
          </Block>

          <Block title="Data in and out">
            <div className="pn-io">
              <Flow label="in" map={node.inputs} />
              <span className="pn-arrow" aria-hidden>→</span>
              <Flow label="out" map={node.outputs} />
            </div>
          </Block>
        </>
      ) : null}

      {tab === "links" ? (
        <>
          <Block title="Depends on" aside={downstream.length || undefined}>
            {chips(downstream, "Terminal boundary. Nothing downstream.")}
            {external.length ? (
              <div className="pn-chips ext">
                {external.map((id) => (
                  <span key={id} title="referenced but not in the graph">
                    {id} ↗
                  </span>
                ))}
              </div>
            ) : null}
          </Block>
          <Block title="Used by" aside={upstream.length || undefined}>
            {chips(upstream, "Entry point. Nothing calls it.")}
          </Block>
          {tenets?.length ? (
            <Block title="Constrained by tenets" aside={tenets.length}>
              <div className="pn-chips tenet">
                {tenets.map((t) => (
                  <button key={t.id} onClick={() => onOpenTenet?.(t.id)} title={`${t.rollup}: open in tenet hierarchy`}>
                    <b>{t.name}</b>
                    <small>{t.rollup}</small>
                  </button>
                ))}
              </div>
            </Block>
          ) : null}
        </>
      ) : null}

      {tab === "context" ? (
        focus ? (
          <Block title="Retrieved context">
            <div className="pn-gauge">
              <div>
                <b>{focus.nodeIds.size}</b>
                <small>nodes pulled in</small>
              </div>
              <div>
                <b>~{focus.tokens}</b>
                <small>tokens</small>
              </div>
            </div>
            <p className="pn-note">The slice of the graph an agent gets when it works on this node.</p>
            <button className="pn-ghost" onClick={() => void copyContext()}>
              {copied ? "Copied ✓" : "Copy context"}
            </button>
          </Block>
        ) : (
          <p className="pn-empty">No context retrieved for this node yet.</p>
        )
      ) : null}
    </Panel>
  );
}
