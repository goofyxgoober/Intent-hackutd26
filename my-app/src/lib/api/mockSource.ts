import type { IntentGraphPayload } from "@/types/intent";
import type { GraphSource } from "./source";
import fixture from "@/data/legacy-monolith-app.json";

/**
 * Offline source backed by a JSON fixture in the exact backend wire format.
 * Lets the graph UI be built and demoed before the pipeline is up.
 * It only fetches; sync, tests and ask are left undefined so the UI says
 * "backend not connected" instead of faking results.
 */
export function createMockSource(): GraphSource {
  return {
    kind: "mock",
    label: "local fixture",
    async fetchGraph(repo) {
      await new Promise((r) => setTimeout(r, 350));
      const data = structuredClone(fixture) as unknown as IntentGraphPayload;
      return { ...data, repo_name: repo || data.repo_name };
    },
  };
}
