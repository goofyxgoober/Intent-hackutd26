import type { GraphIndex } from "@/lib/graph/model";
import type { RetrievalHit, RetrievalResult } from "@/lib/retrieval/engine";
import { estimateTokens, serializeContext } from "@/lib/retrieval/context";

/** The highlighted subgraph, plus the LLM context it would produce. */
export interface Focus {
  kind: "retrieval" | "neighborhood" | "path" | "downstream" | "upstream";
  label: string;
  nodeIds: Set<string>;
  edgeIds: Set<string>;
  scores: Map<string, number>;
  hits: RetrievalHit[];
  context: string;
  tokens: number;
  elapsedMs?: number;
}

export function focusFromResult(index: GraphIndex, r: RetrievalResult, kind: Focus["kind"], label: string): Focus {
  const context = serializeContext(index, r);
  return {
    kind,
    label,
    nodeIds: r.nodeIds,
    edgeIds: r.edgeIds,
    scores: new Map(r.hits.map((h) => [h.node_id, h.score])),
    hits: r.hits,
    context,
    tokens: estimateTokens(context),
    elapsedMs: r.elapsedMs,
  };
}

/** Focus over an explicit node list (paths, dependency closures). */
export function focusFromIds(index: GraphIndex, ids: string[], kind: Focus["kind"], label: string, pathEdgesOnly = false): Focus {
  const nodeIds = new Set(ids);
  const consecutive = new Set(ids.slice(1).map((id, i) => `${ids[i]}>${id}`));
  const edgeIds = new Set(
    index.edges
      .filter((e) =>
        pathEdgesOnly
          ? consecutive.has(`${e.source}>${e.target}`) || consecutive.has(`${e.target}>${e.source}`)
          : nodeIds.has(e.source) && nodeIds.has(e.target),
      )
      .map((e) => e.id),
  );
  const hits = ids.map((node_id, i) => ({ node_id, score: 1, hop: i, matched: [] }));
  return focusFromResult(index, { query: label, hits, nodeIds, edgeIds, elapsedMs: 0 }, kind, label);
}
