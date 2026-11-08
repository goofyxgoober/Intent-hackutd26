"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import dagre from "@dagrejs/dagre";
import { MarkerType, ReactFlow, useNodesInitialized, useReactFlow } from "@xyflow/react";
import type { TreeView } from "@/gh/intentApi";
import { edgeTypes, type ChalkFlowEdge } from "@/components/graph/ChalkEdge";
import { tenetNodeTypes, type TenetFlowNode } from "./TenetNode";
import type { Insets } from "@/components/graph/GraphCanvas";

const EDGE = { normal: "#CBD5E1", hit: "#B76DF0", dim: "#2a2f3a" } as const;

interface Props {
  tree: TreeView;
  selectedId: string | null;
  /** Tenets lit up by a cross-view jump or a terminal query. */
  highlight: Set<string> | null;
  onSelect(id: string | null): void;
  insets: Insets;
}

function layout(tree: TreeView, size: (id: string) => { width: number; height: number }) {
  const g = new dagre.graphlib.Graph({ multigraph: true });
  g.setGraph({ rankdir: "TB", nodesep: 36, ranksep: 80, marginx: 40, marginy: 40 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const t of tree.tenets) g.setNode(t.id, size(t.id));
  // only ownership edges shape the hierarchy; references would fold it into a tangle
  for (const t of tree.tenets) for (const c of t.children) if (g.hasNode(c)) g.setEdge(t.id, c, {}, `own:${t.id}:${c}`);
  dagre.layout(g);
  return (id: string) => {
    const p = g.node(id);
    const s = size(id);
    return { x: p.x - s.width / 2, y: p.y - s.height / 2 };
  };
}

export function TenetCanvas({ tree, selectedId, highlight, onSelect, insets }: Props) {
  const [measuredPos, setMeasuredPos] = useState<{ shape: string; pos: Map<string, { x: number; y: number }> } | null>(null);
  const initialized = useNodesInitialized();
  const { fitView, getNodes } = useReactFlow();
  const shape = useMemo(() => tree.tenets.map((t) => `${t.id}>${t.children.join(",")}`).join("|"), [tree.tenets]);
  const measured = useRef("");
  const camera = useRef({ highlight, insets });
  useEffect(() => {
    camera.current = { highlight, insets };
  });

  // Pass 1: lay out with size estimates; pass 2 (below) replaces it once cards are measured.
  const placed = useMemo(() => {
    if (measuredPos?.shape === shape) return measuredPos.pos;
    const pos = layout(tree, () => ({ width: 220, height: 150 }));
    return new Map(tree.tenets.map((t) => [t.id, pos(t.id)]));
  }, [measuredPos, shape, tree]);

  const base = useMemo<TenetFlowNode[]>(
    () =>
      tree.tenets.map((t) => ({
        id: t.id,
        type: "tenet" as const,
        position: placed.get(t.id) ?? { x: 0, y: 0 },
        data: { tenet: t, dim: false, hit: false },
      })),
    [tree.tenets, placed],
  );

  useEffect(() => {
    if (!initialized || measured.current === shape || !tree.tenets.length) return;
    measured.current = shape;
    const sizes = new Map(getNodes().map((n) => [n.id, { width: n.measured?.width ?? 220, height: n.measured?.height ?? 150 }]));
    const pos = layout(tree, (id) => sizes.get(id) ?? { width: 220, height: 150 });
    setMeasuredPos({ shape, pos: new Map(tree.tenets.map((t) => [t.id, pos(t.id)])) });
    requestAnimationFrame(() => {
      const { highlight: h, insets: i } = camera.current;
      if (h?.size)
        fitView({ nodes: [...h].map((id) => ({ id })), padding: { top: "60px", bottom: "60px", left: `${i.left}px`, right: `${i.right}px` }, duration: 450, maxZoom: 1.1 });
      else fitView({ padding: 0.12, duration: 300 });
    });
  }, [initialized, shape, base, tree, fitView, getNodes]);

  // Camera follows a jump/highlight.
  useEffect(() => {
    if (!highlight?.size) return;
    fitView({
      nodes: [...highlight].map((id) => ({ id })),
      padding: { top: "60px", bottom: "60px", left: `${insets.left}px`, right: `${insets.right}px` },
      duration: 450,
      maxZoom: 1.1,
    });
  }, [highlight]); // eslint-disable-line react-hooks/exhaustive-deps

  const nodes = useMemo<TenetFlowNode[]>(
    () =>
      base.map((n) => {
        const hit = !!highlight?.has(n.id);
        return { ...n, selected: n.id === selectedId, data: { ...n.data, hit, dim: !!highlight && !hit } };
      }),
    [base, selectedId, highlight],
  );

  const edges = useMemo<ChalkFlowEdge[]>(() => {
    const out: ChalkFlowEdge[] = [];
    const ids = new Set(tree.tenets.map((t) => t.id));
    const mk = (id: string, source: string, target: string, relation: string, dashed: boolean): ChalkFlowEdge => {
      const hot = !highlight ? "normal" : highlight.has(source) && highlight.has(target) ? "hit" : "dim";
      return {
        id, source, target, type: "chalk", zIndex: hot === "hit" ? 1 : 0,
        markerEnd: { type: MarkerType.ArrowClosed, color: EDGE[hot], width: 14, height: 14 },
        data: { relation, state: hot, dashed, showLabel: dashed && hot !== "dim" },
      };
    };
    for (const t of tree.tenets) {
      for (const c of t.children) if (ids.has(c)) out.push(mk(`own:${t.id}:${c}`, t.id, c, "owns", false));
      for (const r of t.references) if (ids.has(r)) out.push(mk(`ref:${t.id}:${r}`, t.id, r, "references", true));
    }
    return out;
  }, [tree.tenets, highlight]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={tenetNodeTypes}
      edgeTypes={edgeTypes}
      onNodeClick={(_, n) => onSelect(n.id)}
      onPaneClick={() => onSelect(null)}
      nodesConnectable={false}
      nodesDraggable={false}
      edgesFocusable={false}
      minZoom={0.15}
      maxZoom={2}
      proOptions={{ hideAttribution: true }}
      fitView
    />
  );
}
