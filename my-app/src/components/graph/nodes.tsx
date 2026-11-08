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
  const { node, dim, hit, score } = data;
  const kind = node.meta?.kind ?? "flow";
  const sub = node.meta?.status ?? node.source_file.split("/").slice(-2).join("/");

  return (
    <div
      className={`node-card ${kind} ${selected ? "selected" : ""} ${dim ? "dim" : ""} ${hit ? "hit" : ""}`}
      title={node.node_id}
    >
      <Handle type="target" position={Position.Top} isConnectable={false} />
      <span className="node-head">
        <strong>{node.name || node.node_id}</strong>
      </span>
      <small className="node-source">{sub}</small>
      <em>{node.intent_summary}</em>

      {kind === "test" && node.meta?.code_preview ? <code>{node.meta.code_preview}</code> : null}

      {kind === "flow" && node.business_invariants.length ? (
        <span className="node-count">
          {node.business_invariants.length} {node.business_invariants.length === 1 ? "invariant" : "invariants"}
        </span>
      ) : null}

      {kind === "infra" && node.business_invariants[0] ? (
        <span className="infra-note">{node.business_invariants[0]}</span>
      ) : null}

      {hit && score !== undefined ? <span className="hit-score" title="Retrieval relevance">{score.toFixed(2)}</span> : null}
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
