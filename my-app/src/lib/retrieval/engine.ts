import type { IntentNode } from "@/types/intent";
import type { GraphIndex } from "@/lib/graph/model";

/*
 * Intent-graph retrieval:
 *   1. lexical seeding  — BM25 over weighted node fields
 *   2. graph expansion  — k-hop BFS from seeds, score decays per hop
 *   3. budget cut       — keep the top `maxNodes` by score
 * Pure functions with no React, so the same algorithm can be ported to the
 * Python/NetworkX backend and swapped in behind the `Retriever` interface.
 */

export interface RetrievalOptions {
  /** Hard cap on returned nodes (the context budget). */
  maxNodes?: number;
  /** How far to walk from each seed. */
  hops?: number;
  /** Score multiplier per hop (0..1). */
  decay?: number;
  /** Which edges to follow while expanding. */
  direction?: "out" | "in" | "both";
  /** Seed nodes chosen by the user (e.g. a clicked node). Bypasses BM25. */
  seeds?: string[];
  /** Seeds must reach this fraction of the best lexical score. */
  seedThreshold?: number;
}

export interface RetrievalHit {
  node_id: string;
  score: number;
  hop: number;
  /** The node this hit was reached from (undefined for seeds). */
  via?: string;
  /** Query terms that matched this node directly. */
  matched: string[];
}

export interface RetrievalResult {
  query: string;
  hits: RetrievalHit[];
  nodeIds: Set<string>;
  edgeIds: Set<string>;
  elapsedMs: number;
}

export interface Retriever {
  retrieve(query: string, opts?: RetrievalOptions): Promise<RetrievalResult>;
}

// ---------- tokenisation ----------

const STOP = new Set(
  "a an and are as at be by does for from how i in is it of on or that the this to what when where which who why with do my me show find".split(" "),
);

/** Splits snake_case, camelCase, paths and punctuation; lowercases; drops stopwords. */
export function tokenize(text: string): string[] {
  return text
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((t) => t.length > 1 && !STOP.has(t))
    .map(stem);
}

/** Tiny suffix stripper so "tokens"/"token", "validates"/"validate" collide. */
function stem(t: string): string {
  if (t.length > 4 && t.endsWith("ies")) return t.slice(0, -3) + "y";
  if (t.length > 4 && t.endsWith("ing")) return t.slice(0, -3);
  if (t.length > 3 && t.endsWith("es") && !t.endsWith("ses")) return t.slice(0, -1);
  if (t.length > 3 && t.endsWith("s") && !t.endsWith("ss")) return t.slice(0, -1);
  if (t.length > 4 && t.endsWith("ed")) return t.slice(0, -2);
  return t;
}

// ---------- index ----------

const FIELD_WEIGHTS = {
  id: 3,
  name: 3,
  summary: 2,
  invariants: 1.5,
  io: 1.2,
  file: 1,
} as const;

function fieldsOf(n: IntentNode): Record<keyof typeof FIELD_WEIGHTS, string> {
  return {
    id: n.node_id,
    name: n.name,
    summary: n.intent_summary,
    invariants: n.business_invariants.join(" "),
    io: [...Object.entries(n.inputs), ...Object.entries(n.outputs)].flat().join(" "),
    file: n.source_file,
  };
}

export interface LexicalIndex {
  /** term → (node_id → weighted term frequency) */
  postings: Map<string, Map<string, number>>;
  docLen: Map<string, number>;
  avgLen: number;
  size: number;
}

export function buildLexicalIndex(graph: GraphIndex): LexicalIndex {
  const postings = new Map<string, Map<string, number>>();
  const docLen = new Map<string, number>();
  let total = 0;

  for (const node of graph.nodes.values()) {
    let len = 0;
    for (const [field, text] of Object.entries(fieldsOf(node)) as [keyof typeof FIELD_WEIGHTS, string][]) {
      const w = FIELD_WEIGHTS[field];
      for (const term of tokenize(text)) {
        let p = postings.get(term);
        if (!p) postings.set(term, (p = new Map()));
        p.set(node.node_id, (p.get(node.node_id) ?? 0) + w);
        len += w;
      }
    }
    docLen.set(node.node_id, len);
    total += len;
  }

  return { postings, docLen, avgLen: total / Math.max(1, graph.nodes.size), size: graph.nodes.size };
}

function bm25(lex: LexicalIndex, terms: string[], k1 = 1.2, b = 0.75) {
  const scores = new Map<string, { score: number; matched: Set<string> }>();
  for (const term of new Set(terms)) {
    // exact term, plus prefix matches so "auth" hits "authorization"
    const lists: [string, Map<string, number>][] = [];
    for (const [t, p] of lex.postings) {
      if (t === term || (term.length >= 3 && t.startsWith(term))) lists.push([t, p]);
    }
    for (const [t, posting] of lists) {
      const exact = t === term ? 1 : 0.6;
      const idf = Math.log(1 + (lex.size - posting.size + 0.5) / (posting.size + 0.5));
      for (const [id, tf] of posting) {
        const len = lex.docLen.get(id) ?? lex.avgLen;
        const s = (idf * tf * (k1 + 1)) / (tf + k1 * (1 - b + (b * len) / lex.avgLen));
        const cur = scores.get(id) ?? { score: 0, matched: new Set<string>() };
        cur.score += s * exact;
        cur.matched.add(term);
        scores.set(id, cur);
      }
    }
  }
  return scores;
}

// ---------- retrieval ----------

const DEFAULTS: Required<Omit<RetrievalOptions, "seeds">> = {
  maxNodes: 8,
  hops: 1,
  decay: 0.5,
  direction: "both",
  seedThreshold: 0.35,
};

export function retrieve(
  graph: GraphIndex,
  lex: LexicalIndex,
  query: string,
  options: RetrievalOptions = {},
): RetrievalResult {
  const t0 = performance.now();
  const opts = { ...DEFAULTS, ...options };
  const hits = new Map<string, RetrievalHit>();

  if (opts.seeds?.length) {
    for (const id of opts.seeds) {
      if (graph.nodes.has(id)) hits.set(id, { node_id: id, score: 1, hop: 0, matched: [] });
    }
  } else {
    const scored = bm25(lex, tokenize(query));
    const best = Math.max(0, ...[...scored.values()].map((s) => s.score));
    for (const [id, { score, matched }] of scored) {
      if (best > 0 && score >= best * opts.seedThreshold) {
        hits.set(id, { node_id: id, score: score / best, hop: 0, matched: [...matched] });
      }
    }
  }

  // k-hop expansion; a node keeps the best score it is reached with
  let frontier = [...hits.values()];
  for (let hop = 1; hop <= opts.hops; hop++) {
    const next: RetrievalHit[] = [];
    for (const h of frontier) {
      const neighbors = [
        ...(opts.direction !== "in" ? (graph.out.get(h.node_id) ?? []).map((e) => e.target) : []),
        ...(opts.direction !== "out" ? (graph.in.get(h.node_id) ?? []).map((e) => e.source) : []),
      ];
      for (const n of neighbors) {
        const score = h.score * opts.decay;
        const existing = hits.get(n);
        if (!existing || existing.score < score) {
          const hit = { node_id: n, score, hop, via: h.node_id, matched: existing?.matched ?? [] };
          hits.set(n, hit);
          next.push(hit);
        }
      }
    }
    frontier = next;
  }

  const ranked = [...hits.values()].sort((a, b) => b.score - a.score || a.hop - b.hop).slice(0, opts.maxNodes);
  const nodeIds = new Set(ranked.map((h) => h.node_id));
  const edgeIds = new Set(
    graph.edges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target)).map((e) => e.id),
  );

  return { query, hits: ranked, nodeIds, edgeIds, elapsedMs: performance.now() - t0 };
}

/** Local in-browser retriever. Swap for an HTTP one without touching the UI. */
export function createLocalRetriever(graph: GraphIndex): Retriever {
  const lex = buildLexicalIndex(graph);
  return { retrieve: async (q, o) => retrieve(graph, lex, q, o) };
}
