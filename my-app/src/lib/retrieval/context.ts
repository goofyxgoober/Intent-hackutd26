import type { GraphIndex } from "@/lib/graph/model";
import type { RetrievalResult } from "./engine";

/**
 * Serialises retrieved nodes into the compact text block handed to the LLM
 * (Aadi's Nemotron orchestrator). One block per node, edges inline.
 */
export function serializeContext(graph: GraphIndex, result: Pick<RetrievalResult, "hits" | "nodeIds">): string {
  const blocks = result.hits.map(({ node_id }) => {
    const n = graph.nodes.get(node_id)!;
    const lines = [`[${n.node_id}] ${n.name} (${n.source_file})`, `intent: ${n.intent_summary}`];
    const ins = Object.keys(n.inputs);
    const outs = Object.keys(n.outputs);
    if (ins.length || outs.length) lines.push(`io: ${ins.join(", ") || "-"} -> ${outs.join(", ") || "-"}`);
    for (const inv of n.business_invariants) lines.push(`inv: ${inv}`);
    for (const e of graph.out.get(n.node_id) ?? []) {
      if (result.nodeIds.has(e.target)) lines.push(`-> ${e.target} (${e.relation})`);
    }
    return lines.join("\n");
  });
  return blocks.join("\n\n");
}

/**
 * Rough token estimate (~4 chars/token for English + code identifiers).
 * Replace with the real Nemotron tokenizer count from the backend when available.
 */
export const estimateTokens = (text: string) => Math.ceil(text.length / 4);
