"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { IntentGraphPayload, PipelineStage } from "@/types/intent";
import type { ConnectionState, GraphSource } from "@/lib/api/source";
import { applyPatch, buildIndex, type GraphIndex } from "@/lib/graph/model";
import { createLocalRetriever, type Retriever } from "@/lib/retrieval/engine";

export type LoadStatus = "loading" | "ready" | "syncing" | "error";

export interface IntentGraphState {
  payload: IntentGraphPayload | null;
  index: GraphIndex | null;
  retriever: Retriever | null;
  status: LoadStatus;
  stage: PipelineStage;
  connection: ConnectionState;
  error: string | null;
  /** Bumps on every structural change; use it to trigger relayout. */
  revision: number;
  /** Last status/info message from the backend stream. */
  notice: string | null;
  sync(): Promise<void>;
}

export function useIntentGraph(source: GraphSource, repo: string): IntentGraphState {
  const [payload, setPayload] = useState<IntentGraphPayload | null>(null);
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [stage, setStage] = useState<PipelineStage>(0);
  const [connection, setConnection] = useState<ConnectionState>("offline");
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(
    async (mode: "loading" | "syncing") => {
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      setStatus(mode);
      setStage(0);
      setError(null);
      try {
        const data = await source.fetchGraph(repo, ctrl.signal);
        if (ctrl.signal.aborted) return;
        setPayload(data);
        setRevision((r) => r + 1);
        setStatus("ready");
        setStage(1);
      } catch (e) {
        if (ctrl.signal.aborted) return;
        setError(e instanceof Error ? e.message : String(e));
        setStatus("error");
      }
    },
    [source, repo],
  );

  useEffect(() => {
    load("loading");
    return () => abortRef.current?.abort();
  }, [load]);

  useEffect(() => {
    if (!source.subscribe) return;
    return source.subscribe(repo, {
      onConnection: setConnection,
      onMessage(msg) {
        if (msg.type === "snapshot") {
          setPayload(msg.graph);
          setRevision((r) => r + 1);
          setStatus("ready");
          setStage(1);
        } else if (msg.type === "patch") {
          setPayload((p) => (p ? applyPatch(p, msg.patch) : p));
          setRevision((r) => r + 1);
        } else if (msg.type === "status") {
          if (msg.stage !== undefined) setStage(msg.stage);
          if (msg.message) setNotice(msg.message);
        }
      },
    });
  }, [source, repo]);

  const sync = useCallback(async () => {
    if (source.requestSync) {
      // backend re-ingests and pushes a snapshot/patches over the stream
      setStatus("syncing");
      setStage(0);
      try {
        await source.requestSync(repo);
        await load("syncing"); // the stream may be down; always pull the fresh graph
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setStatus("error");
      }
    } else {
      await load("syncing");
    }
  }, [source, repo, load]);

  const index = useMemo(() => (payload ? buildIndex(payload) : null), [payload]);
  const retriever = useMemo(() => (index ? createLocalRetriever(index) : null), [index]);

  return { payload, index, retriever, status, stage, connection, error, revision, notice, sync };
}
