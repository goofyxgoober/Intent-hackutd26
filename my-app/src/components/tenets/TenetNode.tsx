"use client";

import { memo } from "react";
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import type { Tenet } from "@/gh/intentApi";

export type TenetNodeData = { tenet: Tenet; dim: boolean; hit: boolean };
export type TenetFlowNode = Node<TenetNodeData, "tenet">;

export const TenetCard = memo(function TenetCard({ data, selected }: NodeProps<TenetFlowNode>) {
  const { tenet: t, dim, hit } = data;
  return (
    <div
      className={`node-card tenet-card level-${Math.min(t.level, 3)} ${t.is_leaf ? "leaf" : "feature"} ${selected ? "selected" : ""} ${dim ? "dim" : ""} ${hit ? "hit" : ""}`}
      title={t.name}
    >
      <Handle type="target" position={Position.Top} isConnectable={false} />
      <span className="node-head">
        <strong>{t.name}</strong>
        <small>{t.level === 0 ? "root" : t.is_leaf ? "leaf" : `L${t.level}`}</small>
      </span>
      <em>{t.functionality || "no functionality statement yet"}</em>
      <span className="tenet-meta">
        <span className="ax" title="Axioms: locked, human-confirmed rules">◆ {t.axioms} locked</span>
        <span className="hy" title="Hypotheses: proposed rules, still editable">◇ {t.hypotheses} proposed</span>
        {t.flagged_axioms > 0 ? <span className="flag">⚑ {t.flagged_axioms}</span> : null}
        {t.proposed ? <span className="warn">proposed</span> : null}
        {t.references.length ? <span>↗ {t.references.length}</span> : null}
        <span className={`verdict ${t.rollup}`}>{t.rollup}</span>
      </span>
      {t.code_links[0] ? <span className="infra-note">{t.code_links[0].path}{t.code_links.length > 1 ? ` +${t.code_links.length - 1}` : ""}</span> : null}
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  );
});

export const tenetNodeTypes = { tenet: TenetCard };
