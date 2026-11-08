import type { Tenet, TreeView } from "@/gh/intentApi";
import type { GraphIndex } from "@/lib/graph/model";

const norm = (p: string) => p.replace(/^\.?\//, "");
const same = (a: string, b: string) => norm(a) === norm(b);

/** A tenet's own code links plus those of everything it owns. */
export function pathsUnder(tree: TreeView, id: string): string[] {
  const byId = new Map(tree.tenets.map((t) => [t.id, t]));
  const out = new Set<string>();
  const walk = (tid: string, seen: Set<string>) => {
    const t = byId.get(tid);
    if (!t || seen.has(tid)) return;
    seen.add(tid);
    t.code_links.forEach((l) => out.add(norm(l.path)));
    t.children.forEach((c) => walk(c, seen));
  };
  walk(id, new Set());
  return [...out];
}

/** Graph nodes implementing a tenet (matched on source_file ↔ code link). */
export function graphNodesFor(index: GraphIndex | null, tree: TreeView | null, tenetId: string): { id: string; name: string }[] {
  if (!index || !tree) return [];
  const paths = pathsUnder(tree, tenetId);
  return [...index.nodes.values()]
    .filter((n) => paths.some((p) => same(p, n.source_file)))
    .map((n) => ({ id: n.node_id, name: n.name }));
}

/** Tenets that constrain a graph node: those linking its file, plus a same-named tenet. */
export function tenetsForNode(tree: TreeView | null, nodeId: string, sourceFile: string): Tenet[] {
  if (!tree) return [];
  return tree.tenets.filter((t) => t.id === nodeId || t.code_links.some((l) => same(l.path, sourceFile)));
}

/** exact id → id substring → name substring */
export function resolveTenet(tree: TreeView | null, term: string): string | null {
  if (!tree || !term.trim()) return null;
  const q = term.toLowerCase().replace(/\s+/g, "_");
  return (
    tree.tenets.find((t) => t.id === term || t.id === q)?.id ??
    tree.tenets.find((t) => t.id.toLowerCase().includes(q))?.id ??
    tree.tenets.find((t) => t.name.toLowerCase().includes(term.toLowerCase()))?.id ??
    null
  );
}

/** Claims owned by a tenet and everything under it, grouped by the tenet that holds them. */
export function claimGroups(tree: TreeView, id: string): { tenet: Tenet; claims: TreeView["claims"][string][] }[] {
  const byId = new Map(tree.tenets.map((t) => [t.id, t]));
  const out: { tenet: Tenet; claims: TreeView["claims"][string][] }[] = [];
  const seen = new Set<string>();
  const walk = (tid: string) => {
    const t = byId.get(tid);
    if (!t || seen.has(tid)) return;
    seen.add(tid);
    const claims = t.claims.map((c) => tree.claims[c]).filter((c) => c && c.status !== "scrapped");
    if (claims.length) out.push({ tenet: t, claims });
    t.children.forEach(walk);
  };
  walk(id);
  return out;
}
