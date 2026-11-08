import type { IntentGraphPatch, IntentGraphPayload, PipelineStage } from "@/types/intent";

export type ConnectionState = "offline" | "connecting" | "live";

/** Messages pushed over the graph stream (WebSocket). */
export type GraphStreamMessage =
  | { type: "snapshot"; graph: IntentGraphPayload }
  | { type: "patch"; patch: IntentGraphPatch }
  | { type: "status"; stage?: PipelineStage; message?: string };

export interface GraphStreamHandlers {
  onMessage(msg: GraphStreamMessage): void;
  onConnection?(state: ConnectionState): void;
}

export interface GeneratedTests {
  node_id: string;
  tests: Array<{ name: string; code?: string; invariant?: string }>;
}

export interface AgentReply {
  answer: string;
}

/** Everything the dashboard needs from the backend. */
export interface GraphSource {
  readonly kind: "mock" | "http";
  readonly label: string;
  fetchGraph(repo: string, signal?: AbortSignal): Promise<IntentGraphPayload>;
  /** Live updates. Returns an unsubscribe function. */
  subscribe?(repo: string, handlers: GraphStreamHandlers): () => void;
  /** Ask the backend to re-pull the repo and re-parse. */
  requestSync?(repo: string): Promise<void>;
  /** Aadi's test generation from invariants. */
  generateTests?(repo: string, nodeId: string): Promise<GeneratedTests>;
  /** Aadi's Nemotron chat, given the retrieved intent context. */
  ask?(repo: string, question: string, context: string): Promise<AgentReply>;
}
