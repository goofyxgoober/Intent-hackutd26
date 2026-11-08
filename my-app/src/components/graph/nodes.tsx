"use client";

import { memo } from "react";
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import type { IntentNode } from "@/types/intent";

export type IntentNodeData = {
  node: IntentNode;
  dim: boolean;
  hit: boolean;
  score?: number;
  bound: boolean;
};
export type IntentFlowNode = Node<IntentNodeData, "intent">;

export type BoundaryData = { label: string; dim: boolean };
export type BoundaryFlowNode = Node<BoundaryData, "boundary">;

export const IntentNodeCard = memo(function IntentNodeCard({ data, selected }: NodeProps<IntentFlowNode>) {
  const { node, dim, hit, score, bound } = data;
  const kind = node.meta?.kind ?? "flow";
  const sub = node.meta?.status ?? (kind === "infra" ? node.source_file : node.source_file.replace(/\.(py|ts|tsx|js)$/, ""));

  return (
    <div
      className={`node-card ${kind} ${selected ? "selected" : ""} ${dim ? "dim" : ""} ${hit ? "hit" : ""}`}
      title={node.name}
    >
      <Handle type="target" position={Position.Top} isConnectable={false} />
      <span className="node-head">
        <strong>{node.node_id}</strong>
        <small>{sub}</small>
      </span>
      <em>{node.intent_summary}</em>

      {kind === "test" && node.meta?.code_preview ? <code>{node.meta.code_preview}</code> : null}

      {kind === "flow" && node.business_invariants.length ? (
        <ul>
          {node.business_invariants.slice(0, 2).map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
      ) : null}

      {kind === "infra" && node.business_invariants[0] ? (
        <span className="infra-note">{node.business_invariants[0]}</span>
      ) : null}

      {bound && kind !== "infra" ? <span className="bind">[bound to terminal]</span> : null}
      {hit && score !== undefined ? <span className="hit-score">◆ {score.toFixed(2)}</span> : null}
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  );
});

export const BoundaryBox = memo(function BoundaryBox({ data }: NodeProps<BoundaryFlowNode>) {
  return (
    <div className={`boundary ${data.dim ? "dim" : ""}`}>
      <i className="chalk-note">{data.label}</i>
    </div>
  );
});

export const nodeTypes = { intent: IntentNodeCard, boundary: BoundaryBox };
