import type { IntentGraphPayload } from "@/types/intent";
import type { AgentReply, GeneratedTests, GraphSource, GraphStreamHandlers, GraphStreamMessage } from "./source";

/**
 * REST + WebSocket implementation. Endpoints (see docs/graph-frontend-contract.md):
 *   GET  {api}/repos/:repo/graph              → IntentGraphPayload
 *   POST {api}/repos/:repo/sync               → 202
 *   POST {api}/repos/:repo/nodes/:id/tests    → GeneratedTests
 *   POST {api}/repos/:repo/ask {question, context} → AgentReply
 *   WS   {ws}/repos/:repo/graph               → GraphStreamMessage frames
 */
export function createHttpSource(apiBase: string, wsBase?: string): GraphSource {
  const api = new URL(apiBase.replace(/\/$/, ""), window.location.href).href.replace(/\/$/, "");
  const ws = (wsBase ?? api.replace(/^http/, "ws")).replace(/\/$/, "");
  // "owner/name" keeps its slash: the backend routes GitHub repos by owner and name.
  const repoPath = (repo: string) => `/repos/${repo.split("/").map(encodeURIComponent).join("/")}`;

  async function json<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${api}${path}`, {
      credentials: "include",
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
    if (!res.ok) {
      let detail = "";
      try {
        const body = await res.json();
        detail = typeof body.detail === "string" ? body.detail : (body.detail?.message ?? "");
      } catch {
        /* no JSON body */
      }
      throw new Error(`${res.status} ${detail || res.statusText}`.trim());
    }
    return res.status === 204 || res.status === 202 ? (undefined as T) : res.json();
  }

  return {
    kind: "http",
    label: new URL(api).host,

    // "owner/name" is a connected GitHub repo; a bare name is the seeded demo graph.
    fetchGraph: (repo, signal) => json<IntentGraphPayload>(repo.includes("/") ? `${repoPath(repo)}/graph` : "/graph", { signal }),

    // A GitHub repo runs the full pipeline (pull, snapshot, annotate, tenets); the demo graph has nothing to pull.
    requestSync: async (repo) => {
      if (repo.includes("/")) await json<void>(`${repoPath(repo)}/pipeline`, { method: "POST" });
    },

    generateTests: (repo, nodeId) =>
      json<GeneratedTests>(`${repoPath(repo)}/nodes/${encodeURIComponent(nodeId)}/tests`, { method: "POST" }),

    ask: (repo, question, context) =>
      json<AgentReply>(`${repoPath(repo)}/ask`, { method: "POST", body: JSON.stringify({ question, context }) }),

    subscribe(repo, { onMessage, onConnection }: GraphStreamHandlers) {
      let socket: WebSocket | null = null;
      let closed = false;
      let retry = 0;
      let timer: number | undefined;

      const connect = () => {
        onConnection?.("connecting");
        socket = new WebSocket(`${ws}${repoPath(repo)}/graph`);
        socket.onopen = () => {
          retry = 0;
          onConnection?.("live");
        };
        socket.onmessage = (ev) => {
          try {
            onMessage(JSON.parse(ev.data) as GraphStreamMessage);
          } catch {
            /* ignore malformed frames */
          }
        };
        socket.onclose = () => {
          onConnection?.("offline");
          if (closed) return;
          // exponential backoff, capped at 15s
          timer = window.setTimeout(connect, Math.min(15000, 500 * 2 ** retry++));
        };
      };

      connect();
      return () => {
        closed = true;
        window.clearTimeout(timer);
        socket?.close();
      };
    },
  };
}

export type { AgentReply, GeneratedTests };
