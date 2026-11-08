import dagre from "@dagrejs/dagre";
import type { GraphIndex } from "./model";
import { boundaryOf } from "./model";

export interface Size {
  width: number;
  height: number;
}
export type Positions = Map<string, { x: number; y: number }>;

/** Pre-measurement size estimates per node variant (matches index.css). */
export function estimateSize(kind: string | undefined): Size {
  if (kind === "test") return { width: 260, height: 170 };
  if (kind === "infra") return { width: 160, height: 100 };
  return { width: 220, height: 150 };
}

/**
 * Top-down layered layout. Nodes sharing a boundary are laid out as a
 * dagre compound cluster so each directory stays visually contiguous.
 * Returns top-left positions (React Flow's convention).
 */
export function layoutGraph(graph: GraphIndex, sizeOf: (id: string) => Size): Positions {
  const g = new dagre.graphlib.Graph({ compound: true, multigraph: true });
  g.setGraph({ rankdir: "TB", nodesep: 48, ranksep: 90, edgesep: 20, marginx: 40, marginy: 40 });
  g.setDefaultEdgeLabel(() => ({}));

  const boundaries = new Map<string, string[]>();
  for (const n of graph.nodes.values()) {
    const b = boundaryOf(n);
    boundaries.set(b, [...(boundaries.get(b) ?? []), n.node_id]);
  }

  for (const [id] of graph.nodes) g.setNode(id, sizeOf(id));
  for (const [b, members] of boundaries) {
    if (members.length < 2) continue;
    const cid = `__boundary:${b}`;
    g.setNode(cid, {});
    for (const m of members) g.setParent(m, cid);
  }
  for (const e of graph.edges) g.setEdge(e.source, e.target, {}, e.id);

  dagre.layout(g);

  const out: Positions = new Map();
  for (const [id] of graph.nodes) {
    const p = g.node(id);
    const s = sizeOf(id);
    out.set(id, { x: p.x - s.width / 2, y: p.y - s.height / 2 });
  }
  return out;
}
