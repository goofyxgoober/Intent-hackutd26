"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  MarkerType,
  ReactFlow,
  applyNodeChanges,
  useNodesInitialized,
  useReactFlow,
  type NodeChange,
} from "@xyflow/react";

/** Screen space covered by floating panels, so the camera frames around them. */
export interface Insets {
  left: number;
  right: number;
}
import type { GraphIndex } from "@/lib/graph/model";
import { boundaryOf } from "@/lib/graph/model";
import { estimateSize, layoutGraph } from "@/lib/graph/layout";
import type { Focus } from "@/lib/focus";
import { nodeTypes, type BoundaryFlowNode, type IntentFlowNode } from "./nodes";
import { edgeTypes, type ChalkFlowEdge } from "./ChalkEdge";

const EDGE_COLOR = { normal: "#CBD5E1", hit: "#B76DF0", dim: "#2a2f3a" } as const;
const BOUNDARY_PAD = 26;
const BOUNDARY_ID = "__boundary:";

interface Props {
  index: GraphIndex;
  /** Bumps when the graph structure changes; triggers relayout. */
  revision: number;
  focus: Focus | null;
  selectedId: string | null;
  onSelect(id: string | null): void;
  insets: Insets;
}

export function GraphCanvas({ index, revision, focus, selectedId, onSelect, insets }: Props) {
  const [nodes, setNodes] = useState<IntentFlowNode[]>([]);
  const initialized = useNodesInitialized();
  const { fitView } = useReactFlow();
  const measuredFor = useRef(-1);
  const camera = useRef({ focus, insets });
  useEffect(() => {
    camera.current = { focus, insets };
  });

  // Pass 1: lay out with size estimates whenever the graph changes.
  useEffect(() => {
    const pos = layoutGraph(index, (id) => estimateSize(index.nodes.get(id)?.meta?.kind));
    setNodes((prev) => {
      const old = new Map(prev.map((n) => [n.id, n]));
      return [...index.nodes.values()].map((node) => ({
        ...old.get(node.node_id),
        id: node.node_id,
        type: "intent" as const,
        position: pos.get(node.node_id)!,
        data: { node, dim: false, hit: false, bound: false },
      }));
    });
  }, [index, revision]);

  // Pass 2: once React Flow has measured the real card sizes, relayout once and fit.
  useEffect(() => {
    if (!initialized || measuredFor.current === revision || !nodes.length) return;
    measuredFor.current = revision;
    const sizes = new Map(nodes.map((n) => [n.id, { width: n.measured?.width ?? 220, height: n.measured?.height ?? 150 }]));
    const pos = layoutGraph(index, (id) => sizes.get(id) ?? estimateSize(undefined));
    setNodes((ns) => ns.map((n) => ({ ...n, position: pos.get(n.id) ?? n.position })));
    requestAnimationFrame(() => {
      const { focus: f, insets: i } = camera.current;
      if (f?.nodeIds.size)
        fitView({ nodes: [...f.nodeIds].map((id) => ({ id })), padding: { top: "60px", bottom: "60px", left: `${i.left}px`, right: `${i.right}px` }, duration: 450, maxZoom: 1.1 });
      else fitView({ padding: 0.12, duration: 300 });
    });
  }, [initialized, revision, nodes, index, fitView]);

  // Move the camera to whatever is focused.
  useEffect(() => {
    if (!focus?.nodeIds.size) return;
    fitView({
      nodes: [...focus.nodeIds].map((id) => ({ id })),
      padding: { top: "60px", bottom: "60px", left: `${insets.left}px`, right: `${insets.right}px` },
      duration: 450,
      maxZoom: 1.1,
    });
  }, [focus, fitView]); // eslint-disable-line react-hooks/exhaustive-deps

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    const own = changes.filter((c) => !("id" in c && c.id.startsWith(BOUNDARY_ID))) as NodeChange<IntentFlowNode>[];
    setNodes((ns) => applyNodeChanges(own, ns));
  }, []);

  const renderNodes = useMemo(() => {
    const intent: IntentFlowNode[] = nodes.map((n) => {
      const hit = !!focus?.nodeIds.has(n.id);
      return {
        ...n,
        selected: n.id === selectedId,
        data: {
          ...n.data,
          dim: !!focus && !hit,
          hit,
          score: focus?.kind === "retrieval" || focus?.kind === "neighborhood" ? focus.scores.get(n.id) : undefined,
          bound: n.id === selectedId,
        },
      };
    });

    // Dashed boundaries wrap the current (possibly dragged) node positions.
    const groups = new Map<string, IntentFlowNode[]>();
    for (const n of intent) {
      const b = boundaryOf(n.data.node);
      groups.set(b, [...(groups.get(b) ?? []), n]);
    }
    const boxes: BoundaryFlowNode[] = [];
    for (const [label, members] of groups) {
      if (members.length < 2) continue;
      const x0 = Math.min(...members.map((m) => m.position.x)) - BOUNDARY_PAD;
      const y0 = Math.min(...members.map((m) => m.position.y)) - BOUNDARY_PAD - 14;
      const x1 = Math.max(...members.map((m) => m.position.x + (m.measured?.width ?? 220))) + BOUNDARY_PAD;
      const y1 = Math.max(...members.map((m) => m.position.y + (m.measured?.height ?? 150))) + BOUNDARY_PAD;
      boxes.push({
        id: BOUNDARY_ID + label,
        type: "boundary",
        position: { x: x0, y: y0 },
        width: x1 - x0,
        height: y1 - y0,
        data: { label, dim: !!focus && !members.some((m) => m.data.hit) },
        draggable: false,
        selectable: false,
        focusable: false,
        zIndex: -1,
      });
    }
    return [...boxes, ...intent];
  }, [nodes, focus, selectedId]);

  const edges = useMemo<ChalkFlowEdge[]>(() => {
    const small = index.edges.length <= 30;
    return index.edges.map((e) => {
      const state = !focus ? "normal" : focus.edgeIds.has(e.id) ? "hit" : "dim";
      const srcKind = index.nodes.get(e.source)?.meta?.kind;
      const tgtKind = index.nodes.get(e.target)?.meta?.kind;
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        type: "chalk",
        zIndex: state === "hit" ? 1 : 0,
        markerEnd: { type: MarkerType.ArrowClosed, color: EDGE_COLOR[state], width: 14, height: 14 },
        data: {
          relation: e.relation,
          state,
          dashed: tgtKind === "infra" || srcKind === "test",
          showLabel: state === "hit" || (!focus && small),
        },
      };
    });
  }, [index, focus]);

  return (
    <ReactFlow
      nodes={renderNodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      onNodesChange={onNodesChange}
      onNodeClick={(_, n) => n.type === "intent" && onSelect(n.id)}
      onPaneClick={() => onSelect(null)}
      nodesConnectable={false}
      edgesFocusable={false}
      minZoom={0.15}
      maxZoom={2}
      onlyRenderVisibleElements={index.nodes.size > 150}
      proOptions={{ hideAttribution: true }}
      fitView
    />
  );
}
