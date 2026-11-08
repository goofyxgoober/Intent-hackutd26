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
  onGenerateTests?(id: string): void;
  /** Tenets whose code links cover this node's file. */
  tenets?: { id: string; name: string; rollup: string }[];
  onOpenTenet?(id: string): void;
  onUpdateNode?(nodeId: string, updated: any): void;
}

type Tab = "intent" | "links" | "context" | "edit";

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

export function Inspector({ index, nodeId, focus, onSelect, onGenerateTests, tenets, onOpenTenet, onUpdateNode }: Props) {
  const [tab, setTab] = useState<Tab>("intent");
  const [copied, setCopied] = useState(false);
  const node = index.nodes.get(nodeId);

  const [editName, setEditName] = useState(node?.name ?? "");
  const [editSummary, setEditSummary] = useState(node?.intent_summary ?? "");
  const [editInvariants, setEditInvariants] = useState<string[]>(node?.business_invariants || []);
  const [newInv, setNewInv] = useState("");

  if (!node) return null;

  function saveNode() {
    const updated = {
      name: editName,
      intent_summary: editSummary,
      business_invariants: editInvariants,
    };
    node!.name = editName;
    node!.intent_summary = editSummary;
    node!.business_invariants = editInvariants;
    onUpdateNode?.(nodeId, updated);
    setTab("intent");
  }

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
      label="Codebase node inspector"
      eyebrow={
        <>
          <i className="pn-dot" /> codebase node
        </>
      }
      title={node.name}
      sub={<CopyChip text={node.source_file} />}
      tabs={[
        { id: "intent", label: "Intent", count: node.business_invariants.length },
        { id: "links", label: "Links", count: linkCount },
        { id: "context", label: "Context" },
        { id: "edit", label: "✎ Edit" },
      ]}
      tab={tab}
      onTab={(t) => setTab(t as Tab)}
      onClose={() => onSelect(null)}
      step={{ onPrev: () => go(-1), onNext: () => go(1), position: `${at + 1}/${ids.length}` }}
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

      {tab === "edit" ? (
        <div className="pn-edit-node" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div>
            <label style={{ fontSize: 11, textTransform: "uppercase", color: "var(--text-dim)", display: "block", marginBottom: 4 }}>
              Node Name
            </label>
            <input
              type="text"
              style={{ width: "100%", padding: "6px 8px", background: "rgba(0,0,0,0.2)", border: "1px solid var(--border)", borderRadius: 4, color: "inherit" }}
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
            />
          </div>

          <div>
            <label style={{ fontSize: 11, textTransform: "uppercase", color: "var(--text-dim)", display: "block", marginBottom: 4 }}>
              Intent Summary
            </label>
            <textarea
              rows={4}
              style={{ width: "100%", padding: "6px 8px", background: "rgba(0,0,0,0.2)", border: "1px solid var(--border)", borderRadius: 4, color: "inherit" }}
              value={editSummary}
              onChange={(e) => setEditSummary(e.target.value)}
            />
          </div>

          <div>
            <label style={{ fontSize: 11, textTransform: "uppercase", color: "var(--text-dim)", display: "block", marginBottom: 4 }}>
              Business Invariants ({editInvariants.length})
            </label>
            <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 8 }}>
              {editInvariants.map((invItem, idx) => (
                <div key={idx} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <input
                    type="text"
                    style={{ flex: 1, padding: "4px 8px", background: "rgba(0,0,0,0.2)", border: "1px solid var(--border)", borderRadius: 4, color: "inherit", fontSize: 12 }}
                    value={invItem}
                    onChange={(e) => {
                      const next = [...editInvariants];
                      next[idx] = e.target.value;
                      setEditInvariants(next);
                    }}
                  />
                  <button
                    type="button"
                    style={{ background: "none", border: "none", color: "var(--text-dim)", cursor: "pointer", fontSize: 16 }}
                    onClick={() => setEditInvariants(editInvariants.filter((_, i) => i !== idx))}
                    title="Remove invariant"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              <input
                type="text"
                placeholder="Add business invariant..."
                style={{ flex: 1, padding: "4px 8px", background: "rgba(0,0,0,0.2)", border: "1px solid var(--border)", borderRadius: 4, color: "inherit", fontSize: 12 }}
                value={newInv}
                onChange={(e) => setNewInv(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && newInv.trim()) {
                    e.preventDefault();
                    setEditInvariants([...editInvariants, newInv.trim()]);
                    setNewInv("");
                  }
                }}
              />
              <button
                type="button"
                className="pn-ghost"
                onClick={() => {
                  if (newInv.trim()) {
                    setEditInvariants([...editInvariants, newInv.trim()]);
                    setNewInv("");
                  }
                }}
              >
                Add
              </button>
            </div>
          </div>

          <div style={{ display: "flex", gap: 8, marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
            <button className="pn-ghost go" style={{ flex: 1, fontWeight: "bold" }} onClick={() => saveNode()}>
              Save Node
            </button>
            <button className="pn-ghost" onClick={() => setTab("intent")}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}
    </Panel>
  );
}
