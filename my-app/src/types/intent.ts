// Shared data contract. Mirrors CONTEXT.md §5 exactly so the backend
// (Indra's intent engine, Ayaan's pipeline) can send its JSON unchanged.

/** CONTEXT.md §5.1 — one functional flow block. */
export interface IntentNode {
  node_id: string;
  name: string;
  source_file: string;
  intent_summary: string;
  inputs: Record<string, string>;
  outputs: Record<string, string>;
  business_invariants: string[];
  downstream_dependencies: string[];
  /** Optional UI-only hints. The backend may omit this entirely. */
  meta?: IntentNodeMeta;
}

export interface IntentNodeMeta {
  /** Visual variant. Defaults to "flow". */
  kind?: "flow" | "test" | "infra";
  /** Short badge text, e.g. "2 passing". */
  status?: string;
  /** Overrides the directory-based boundary grouping. */
  boundary?: string;
  /** Small code excerpt shown on test nodes. */
  code_preview?: string;
  /** Tokens the raw source of this node would cost an LLM. Drives the Raw vs Intent token meter. */
  raw_tokens?: number;
}

/** CONTEXT.md §5.2 edge. */
export interface IntentEdge {
  source: string;
  target: string;
  relation: string;
}

/**
 * Wire format for a full graph. §5.2 lists `nodes` as ids only; the frontend
 * needs the node bodies too, so the payload carries full IntentNode objects.
 * If `edges` is empty, edges are derived from `downstream_dependencies`.
 */
export interface IntentGraphPayload {
  repo_name: string;
  nodes: IntentNode[];
  edges: IntentEdge[];
}

/** Incremental update (Indra's "dynamic incremental updates"). */
export interface IntentGraphPatch {
  upsert_nodes?: IntentNode[];
  remove_nodes?: string[];
  upsert_edges?: IntentEdge[];
  remove_edges?: Array<Pick<IntentEdge, "source" | "target"> & { relation?: string }>;
}

export type PipelineStage = 0 | 1 | 2;
