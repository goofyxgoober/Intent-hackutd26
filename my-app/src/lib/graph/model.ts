import type { IntentEdge, IntentGraphPatch, IntentGraphPayload, IntentNode } from "@/types/intent";

export interface IndexedEdge extends IntentEdge {
  id: string;
}

/** Read-optimised view of a graph. Rebuilt whenever the payload changes. */
export interface GraphIndex {
  repo: string;
  nodes: Map<string, IntentNode>;
  edges: IndexedEdge[];
  out: Map<string, IndexedEdge[]>;
  in: Map<string, IndexedEdge[]>;
  /** Dependencies named by a node that don't exist in the graph (yet). */
  dangling: Map<string, string[]>;
}

export const edgeId = (e: Pick<IntentEdge, "source" | "target" | "relation">) =>
  `${e.source}->${e.target}:${e.relation}`;

/** Edges from the payload, or derived from downstream_dependencies when absent. */
function resolveEdges(payload: IntentGraphPayload): IntentEdge[] {
  if (payload.edges.length) return payload.edges;
  return payload.nodes.flatMap((n) =>
    n.downstream_dependencies.map((target) => ({
      source: n.node_id,
      target,
      relation: "depends_on",
    })),
  );
}

export function buildIndex(payload: IntentGraphPayload): GraphIndex {
  const nodes = new Map(payload.nodes.map((n) => [n.node_id, n]));
  const out = new Map<string, IndexedEdge[]>();
  const inn = new Map<string, IndexedEdge[]>();
  const dangling = new Map<string, string[]>();
  const seen = new Set<string>();
  const edges: IndexedEdge[] = [];

  for (const id of nodes.keys()) {
    out.set(id, []);
    inn.set(id, []);
  }

  for (const e of resolveEdges(payload)) {
    if (!nodes.has(e.source)) continue;
    if (!nodes.has(e.target)) {
      dangling.set(e.source, [...(dangling.get(e.source) ?? []), e.target]);
      continue;
    }
    const id = edgeId(e);
    if (seen.has(id)) continue;
    seen.add(id);
    const ie = { ...e, id };
    edges.push(ie);
    out.get(e.source)!.push(ie);
    inn.get(e.target)!.push(ie);
  }

  for (const n of payload.nodes) {
    for (const dep of n.downstream_dependencies) {
      if (!nodes.has(dep) && !dangling.get(n.node_id)?.includes(dep)) {
        dangling.set(n.node_id, [...(dangling.get(n.node_id) ?? []), dep]);
      }
    }
  }

  return { repo: payload.repo_name, nodes, edges, out, in: inn, dangling };
}

/** Pure patch application. Removing a node also drops its edges. */
export function applyPatch(payload: IntentGraphPayload, patch: IntentGraphPatch): IntentGraphPayload {
  const removed = new Set(patch.remove_nodes ?? []);
  const byId = new Map(payload.nodes.filter((n) => !removed.has(n.node_id)).map((n) => [n.node_id, n]));
  for (const n of patch.upsert_nodes ?? []) byId.set(n.node_id, n);

  const dropEdge = (e: IntentEdge) =>
    removed.has(e.source) ||
    removed.has(e.target) ||
    (patch.remove_edges ?? []).some(
      (r) => r.source === e.source && r.target === e.target && (!r.relation || r.relation === e.relation),
    );

  const edges = new Map(payload.edges.filter((e) => !dropEdge(e)).map((e) => [edgeId(e), e]));
  for (const e of patch.upsert_edges ?? []) edges.set(edgeId(e), e);

  return { repo_name: payload.repo_name, nodes: [...byId.values()], edges: [...edges.values()] };
}

/** Which dashed boundary a node is drawn inside. */
export function boundaryOf(node: IntentNode): string {
  if (node.meta?.boundary) return node.meta.boundary;
  const parts = node.source_file.split("/").filter(Boolean);
  if (parts.length <= 1) return parts[0] ?? "root";
  // "src/auth/session.py" → "src/auth"; "tests/test_x.py" → "tests"
  return parts[0] === "src" || parts[0] === "lib" || parts[0] === "app"
    ? parts.slice(0, 2).join("/")
    : parts[0];
}

/** BFS shortest directed path (falls back to undirected). Returns node ids. */
export function shortestPath(index: GraphIndex, from: string, to: string): string[] | null {
  const walk = (undirected: boolean) => {
    const prev = new Map<string, string | null>([[from, null]]);
    const queue = [from];
    while (queue.length) {
      const cur = queue.shift()!;
      if (cur === to) break;
      const next = [
        ...(index.out.get(cur) ?? []).map((e) => e.target),
        ...(undirected ? (index.in.get(cur) ?? []).map((e) => e.source) : []),
      ];
      for (const n of next) {
        if (!prev.has(n)) {
          prev.set(n, cur);
          queue.push(n);
        }
      }
    }
    if (!prev.has(to)) return null;
    const path: string[] = [];
    for (let c: string | null = to; c; c = prev.get(c) ?? null) path.unshift(c);
    return path;
  };
  if (!index.nodes.has(from) || !index.nodes.has(to)) return null;
  return walk(false) ?? walk(true);
}

/** Every node reachable along `dir` edges (excluding the start). */
export function reachable(index: GraphIndex, start: string, dir: "out" | "in"): string[] {
  const seen = new Set([start]);
  const stack = [start];
  while (stack.length) {
    const cur = stack.pop()!;
    for (const e of index[dir].get(cur) ?? []) {
      const n = dir === "out" ? e.target : e.source;
      if (!seen.has(n)) {
        seen.add(n);
        stack.push(n);
      }
    }
  }
  seen.delete(start);
  return [...seen];
}
