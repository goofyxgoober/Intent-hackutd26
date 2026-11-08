# IntentFlow — Graph Visualizer & Retrieval: Integration Contract

Owner: **Vishjit**. This doc describes what the graph dashboard expects from the backend, and the hooks other modules plug into.

## Run modes

| Mode | How | Data |
| :-- | :-- | :-- |
| Offline (default) | no env vars | `src/data/legacy-monolith-app.json` fixture, same wire format as the backend |
| Live | `NEXT_PUBLIC_INTENTFLOW_API=/api` in `.env.local` (Next proxies `/api/*` → `INTENTFLOW_BACKEND_URL`, default `http://localhost:8000`) | REST + WebSocket below |

Stack: Next.js (App Router) frontend, Python backend. The graph renders client-only (`next/dynamic`, `ssr: false`).

`?repo=<name>` in the URL selects the repo. Next rewrites don't proxy WebSockets, so set `NEXT_PUBLIC_INTENTFLOW_WS=ws://localhost:8000/api` to point straight at the Python server.

## Wire format (CONTEXT.md §5, unchanged)

```ts
IntentGraphPayload = { repo_name: string; nodes: IntentNode[]; edges: IntentEdge[] }
IntentNode = { node_id, name, source_file, intent_summary, inputs, outputs,
               business_invariants: string[], downstream_dependencies: string[],
               meta?: { kind?: "flow"|"test"|"infra", status?, boundary?, code_preview? } }
IntentEdge = { source, target, relation }
```

- `nodes` carries **full node objects**, not just ids as §5.2 shows.
- If `edges` is empty, the UI derives `depends_on` edges from `downstream_dependencies`.
- A dependency naming a node that isn't in the graph is shown as an external ref (↗), not an error.
- `meta` is optional, UI-only. Boundaries (the dashed groups) default to the source directory (`src/auth`, `infra`, `tests`, …).

## Endpoints (Ayaan)

| Method | Path | Body | Returns | Owner |
| :-- | :-- | :-- | :-- | :-- |
| GET | `/repos/:repo/graph` | — | `IntentGraphPayload` | Ayaan / Indra |
| POST | `/repos/:repo/sync` | — | 202; then push over WS | Ayaan |
| POST | `/repos/:repo/nodes/:id/tests` | — | `{ node_id, tests: [{ name, code?, invariant? }] }` | Aadi |
| POST | `/repos/:repo/ask` | `{ question, context }` | `{ answer }` | Aadi |
| WS | `/repos/:repo/graph` | — | stream of messages ↓ | Ayaan / Indra |

REST goes through the Next proxy, so it needs no CORS. The Python WebSocket endpoint must accept the dashboard origin. Every endpoint except the GET is optional: if it isn't implemented, the UI says "not connected" instead of faking a result.

### WebSocket messages

```json
{ "type": "snapshot", "graph": IntentGraphPayload }
{ "type": "patch", "patch": { "upsert_nodes": [], "remove_nodes": [], "upsert_edges": [], "remove_edges": [{ "source", "target", "relation?" }] } }
{ "type": "status", "stage": 0 | 1 | 2, "message": "free text shown in the terminal" }
```

- `stage` drives the header: 0 raw AST tangle → 1 functional intent graph → 2 modern branch merge.
- Indra's incremental updates should send `patch`, not full snapshots. Removing a node drops its edges automatically.
- The client reconnects with exponential backoff (capped at 15 s).

## Retrieval (Vishjit)

`src/lib/retrieval/engine.ts` contains pure functions, so the same algorithm can be ported to Python/NetworkX:

1. **Seed:** BM25 over node fields, weighted id/name ×3, summary ×2, invariants ×1.5, I/O ×1.2, file ×1. Tokens split snake_case/camelCase/paths with light stemming and prefix matching. Seeds are nodes scoring ≥ 35% of the top score.
2. **Expand:** k-hop BFS (default 1 hop, both directions), score × 0.5 per hop.
3. **Budget:** keep the top `maxNodes` (default 8).

A node click retrieves with `seeds: [id]`. A typed question retrieves lexically. The result is serialized by `serializeContext()` into the compact block Aadi's agent receives as `context`. Token counts are estimated at ~4 chars/token until the backend supplies the real tokenizer count.

To move retrieval server-side, implement the `Retriever` interface (`retrieve(query, opts) → RetrievalResult`) over HTTP and swap it in `useIntentGraph`. The UI doesn't change.

## Extension points

- **New terminal commands** (e.g. Aadi's): append a `Command` to `commands` in `src/lib/terminal/commands.ts`.
- **New backend**: implement `GraphSource` (`src/lib/api/source.ts`).
- **Free-text input** in the terminal → retrieval → `source.ask()` when connected.

Terminal commands: `help, inspect, query, invariants, deps, impact, path, ls, context, tests, reset, fit, sync, clear`. `/` focuses the terminal, `Esc` clears the selection.
