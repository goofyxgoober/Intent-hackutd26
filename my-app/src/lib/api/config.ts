import { createHttpSource } from "./httpSource";
import { createMockSource } from "./mockSource";
import type { GraphSource } from "./source";

/**
 * Runtime config from `.env.local` (NEXT_PUBLIC_* is inlined at build time):
 *   NEXT_PUBLIC_INTENTFLOW_API=/api            (proxied to the Python backend, see next.config.ts)
 *   NEXT_PUBLIC_INTENTFLOW_WS=ws://localhost:8000/api
 *   NEXT_PUBLIC_INTENTFLOW_REPO=legacy-monolith-app
 *   NEXT_PUBLIC_INTENTFLOW_USER=vishjit
 * Unset API → offline fixture. `?repo=owner/name` in the URL overrides the repo.
 */
export interface IntentflowConfig {
  apiBase?: string;
  wsBase?: string;
  repo: string;
  user: string;
}

/** Call only in the browser (reads the URL). */
export function getConfig(): IntentflowConfig {
  const params = new URLSearchParams(typeof window !== "undefined" ? window.location.search : "");
  return {
    apiBase: process.env.NEXT_PUBLIC_INTENTFLOW_API || undefined,
    wsBase: process.env.NEXT_PUBLIC_INTENTFLOW_WS || undefined,
    repo: params.get("repo") || process.env.NEXT_PUBLIC_INTENTFLOW_REPO || "legacy-monolith-app",
    user: process.env.NEXT_PUBLIC_INTENTFLOW_USER || "vishjit",
  };
}

export function createSource(config: IntentflowConfig): GraphSource {
  return config.apiBase ? createHttpSource(config.apiBase, config.wsBase) : createMockSource();
}
