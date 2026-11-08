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
    async ask(_repo, question, _context) {
      await new Promise((r) => setTimeout(r, 250));
      if (question.startsWith("/hypothesize") || question.toLowerCase().includes("draft") || question.toLowerCase().includes("hypothesis")) {
        return {
          answer: "Jev → hypothesis · 0.94 ✓\nDrafted 2 unverified hypotheses on the selected tenet:\n- `Payment amount must always be positive.`\n- `Refund transactions require idempotency token.`",
          route: { verdict: "hypothesis_generation", confidence: 0.94, approved: true },
          generation: {
            status: "completed",
            claims_created: [
              { id: "c_mock_1", statement: "Payment amount must always be positive." },
              { id: "c_mock_2", statement: "Refund transactions require idempotency token." },
            ],
          },
        };
      }
      return {
        answer: "Jev → query · 0.92\nThe payment gateway subsystem processes credit card charges and validates amount boundaries [[file:src/payments/charge.py:1-25]] under [[tenet:t_payments]]. Related invariant: [[claim:c_amount_pos]].\n\ntokens: 3.8k vs 42k raw (-91%)",
        route: { verdict: "query", confidence: 0.92, approved: false, gate_reason: "not_generation" },
        query: {
          answer: "The payment gateway subsystem processes credit card charges and validates amount boundaries [[file:src/payments/charge.py:1-25]] under [[tenet:t_payments]]. Related invariant: [[claim:c_amount_pos]].",
          citations: [
            { kind: "file", path: "src/payments/charge.py", start_line: 1, end_line: 25, valid: true },
            { kind: "tenet", id: "t_payments", valid: true },
            { kind: "claim", id: "c_amount_pos", valid: true },
          ],
          usage: { tokens_context: 3800, tokens_raw_equivalent: 42000, percent_saved: 91.0 },
        },
      };
    },
  };
}
