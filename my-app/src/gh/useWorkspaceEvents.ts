"use client";

import { useEffect, useRef, useState } from "react";

export interface WorkspaceEvent {
  type: string;
  [key: string]: unknown;
}

/** Live workspace events over WebSocket, reconnecting with backoff. */
export function useWorkspaceEvents(workspaceId: number | null, onEvent: (e: WorkspaceEvent) => void) {
  const handler = useRef(onEvent);
  handler.current = onEvent;
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (workspaceId === null) return;
    let ws: WebSocket | null = null;
    let retry = 0;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;

    const open = () => {
      // Next rewrites don't proxy WebSockets, so connect to the backend directly.
      const backend = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
      ws = new WebSocket(`${backend.replace(/^http/, "ws")}/ws/workspaces/${workspaceId}`);
      ws.onopen = () => {
        retry = 0;
        setConnected(true);
      };
      ws.onmessage = (m) => {
        try {
          handler.current(JSON.parse(m.data));
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!stopped) timer = setTimeout(open, Math.min(30000, 1000 * 2 ** retry++));
      };
    };
    open();
    return () => {
      stopped = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, [workspaceId]);

  return connected;
}
