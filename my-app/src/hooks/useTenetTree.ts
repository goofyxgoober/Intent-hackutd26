"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { GraphSource } from "@/lib/api/source";
import { api } from "@/gh/api";
import { workspaceApi, type TreeView } from "@/gh/intentApi";
import { useWorkspaceEvents, type WorkspaceEvent } from "@/gh/useWorkspaceEvents";
import fixture from "@/fixtures/legacy-monolith-app.tenets.json";

export type TenetStatus = "loading" | "ready" | "signin" | "unlinked" | "error";
type Api = ReturnType<typeof workspaceApi>;

export interface TenetTreeState {
  tree: TreeView | null;
  status: TenetStatus;
  error: string | null;
  /** True when the tree comes from the offline fixture and can't be edited. */
  offline: boolean;
  live: boolean;
  wsApi: Api | null;
  reload(): Promise<void>;
  /** Last event message from the backend, for the terminal. */
  notice: string | null;
}

/**
 * The Axiom/Tenet hierarchy for the repo the graph page is showing.
 * Live mode: finds (or creates) the workspace for `owner/name`, loads `/api/workspaces/{id}/tree`
 * and refreshes on the workspace WebSocket. Offline mode: a fixture in the same wire format.
 */
export function useTenetTree(source: GraphSource, repo: string, enabled: boolean): TenetTreeState {
  const offline = source.kind === "mock";
  const isDemo = offline || !repo.includes("/");
  const [tree, setTree] = useState<TreeView | null>(isDemo ? (fixture as unknown as TreeView) : null);
  const [status, setStatus] = useState<TenetStatus>(isDemo ? "ready" : "loading");
  const [error, setError] = useState<string | null>(null);
  const [workspaceId, setWorkspaceId] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const wsApi = useMemo(() => (workspaceId === null ? null : workspaceApi(workspaceId)), [workspaceId]);
  const wsApiRef = useRef(wsApi);
  useEffect(() => {
    wsApiRef.current = wsApi;
  }, [wsApi]);

  const fail = useCallback((e: unknown) => {
    const msg = e instanceof Error ? e.message : String(e);
    setError(msg);
    setStatus(/sign in|unauth|401|not authenticated/i.test(msg) ? "signin" : "error");
  }, []);

  // Resolve repo → workspace once (only when the tenet view is first needed).
  useEffect(() => {
    if (offline || !enabled || workspaceId !== null) return;
    let cancelled = false;
    (async () => {
      try {
        let full = repo.includes("/") ? repo : null;
        if (!full) {
          try {
            const mine = await api<{ full_name: string }[]>("/api/repos");
            full = mine.find((r) => r.full_name.split("/")[1] === repo)?.full_name ?? null;
          } catch {
            // Not signed in to GitHub yet; keep demo tree for demo repos
            if (isDemo && !cancelled) {
              setTree(fixture as unknown as TreeView);
              setStatus("ready");
              return;
            }
          }
        }
        if (!full) {
          if (!cancelled) setStatus(isDemo ? "ready" : "unlinked");
          return;
        }
        const [owner, name] = full.split("/");
        const ws = await api<{ id: number }>(`/api/repos/${owner}/${name}/connect`, { method: "POST" });
        if (!cancelled) setWorkspaceId(ws.id);
      } catch (e) {
        if (!cancelled) {
          if (isDemo) {
            setTree(fixture as unknown as TreeView);
            setStatus("ready");
          } else {
            fail(e);
          }
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [offline, enabled, repo, workspaceId, fail, isDemo]);

  const reload = useCallback(async () => {
    const w = wsApiRef.current;
    if (!w) return;
    try {
      setTree(await w.tree());
      setStatus("ready");
      setError(null);
    } catch (e) {
      fail(e);
    }
  }, [fail]);

  useEffect(() => {
    if (wsApi) void reload();
  }, [wsApi, reload]);

  const live = useWorkspaceEvents(offline ? null : workspaceId, (e: WorkspaceEvent) => {
    if (e.type === "hello") return;
    if (e.type === "flag.raised") setNotice(`⚑ ${String(e.kind).replace(/_/g, " ")} on ${String(e.claim_id)}: ${String(e.reason ?? "")}`);
    else if (e.type === "sync.batch") setNotice("⇣ new commits synced: tenet tree refreshed");
    else if (e.type === "jev.verdict") setNotice(`jev → ${String(e.verdict)} (${String(e.confidence)})`);
    else if (e.type === "grill.question") setNotice(`🔥 Tenet grilling active for "${String(e.tenet_name ?? 'System')}": ${String(e.question_text ?? 'Questions ready (type "grill")')}`);
    else if (e.type === "grill.done") setNotice(`✓ Grilling complete for "${String(e.tenet_name ?? 'tenet')}"`);
    void reload();
  });

  return { tree, status, error, offline, live, wsApi, reload, notice };
}
