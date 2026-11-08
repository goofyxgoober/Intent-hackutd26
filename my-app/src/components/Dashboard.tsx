"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ReactFlowProvider, useReactFlow, useViewport } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { getConfig, createSource } from "@/lib/api/config";
import { useIntentGraph, type IntentGraphState } from "@/hooks/useIntentGraph";
import { boundaryOf } from "@/lib/graph/model";
import { focusFromResult, type Focus } from "@/lib/focus";
import type { RetrievalOptions } from "@/lib/retrieval/engine";
import { execute, type CommandContext, type Line, type Tone } from "@/lib/terminal/commands";
import { GraphCanvas } from "@/components/graph/GraphCanvas";
import { Inspector } from "@/components/Inspector";
import { Terminal } from "@/components/Terminal";

// Client-only module (loaded with ssr:false), so window/location are safe here.
const config = getConfig();
const source = createSource(config);
const STAGES = ["01. raw ast tangle", "02. functional intent graph", "03. modern branch merge"];

function Toolbar({ onSync, syncing }: { onSync(): void; syncing: boolean }) {
  const { zoom } = useViewport();
  const { zoomIn, zoomOut, fitView } = useReactFlow();
  return (
    <div className="toolbar">
      <button onClick={() => zoomOut({ duration: 150 })} aria-label="Zoom out">
        −
      </button>
      <button onClick={() => fitView({ padding: 0.12, duration: 300 })} title="Fit graph">
        {Math.round(zoom * 100)}%
      </button>
      <button onClick={() => zoomIn({ duration: 150 })} aria-label="Zoom in">
        +
      </button>
      <button className={syncing ? "syncing" : ""} onClick={onSync} disabled={syncing}>
        {syncing ? "syncing…" : "sync repo"}
      </button>
      <a href="/dashboard" title="GitHub repos, sync and history">github repos</a>
      <span>click nodes to inspect · / to query</span>
    </div>
  );
}

function StatusBar({ g, focus }: { g: IntentGraphState; focus: Focus | null }) {
  const boundaries = useMemo(
    () => (g.index ? new Set([...g.index.nodes.values()].map(boundaryOf)).size : 0),
    [g.index],
  );
  const link =
    source.kind === "mock" ? "fixture (offline)" : g.connection === "live" ? "live" : g.connection === "connecting" ? "connecting…" : "offline";

  return (
    <footer className="statusbar">
      <div>
        <span>
          source: <b>{source.label}</b>
        </span>
        <i>·</i>
        <span>
          graph: <b>{g.index ? `${g.index.nodes.size} nodes · ${g.index.edges.length} edges` : "—"}</b>
        </span>
        <i>·</i>
        <span className={g.status === "syncing" || g.connection === "connecting" ? "pulse" : ""}>
          stream: <b>{g.status === "syncing" ? "ingesting…" : link}</b>
        </span>
      </div>
      <p>
        {g.index
          ? `“${g.index.repo}: ${g.index.nodes.size} intent nodes across ${boundaries} boundaries”`
          : g.status === "error"
            ? "“graph unavailable”"
            : "“distilling ast…”"}
        {focus ? (
          <b>
            {focus.nodeIds.size} in context · ~{focus.tokens} tokens
          </b>
        ) : null}
      </p>
    </footer>
  );
}

function Workspace() {
  const g = useIntentGraph(source, config.repo);
  const { fitView } = useReactFlow();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focus, setFocus] = useState<Focus | null>(null);
  const [termOpen, setTermOpen] = useState(true);
  const [termMin, setTermMin] = useState(false);
  const [busy, setBusy] = useState(false);
  const [lines, setLines] = useState<Line[]>(() => [
    { id: 0, text: `⚡ INTENTFLOW ➔ graph retrieval engine · source: ${source.label}`, tone: "accent" },
    { id: 1, text: `TARGET ➔ ${config.repo}` },
  ]);
  const lineId = useRef(2);
  const inputRef = useRef<HTMLInputElement>(null);
  const prompt = `${config.user}@intentflow`;

  const print = useCallback((text: string | string[], tone?: Tone) => {
    const arr = Array.isArray(text) ? text : [text];
    setLines((ls) => [...ls, ...arr.map((t) => ({ id: lineId.current++, text: t, tone }))].slice(-500));
  }, []);

  useEffect(() => {
    if (g.status === "ready" && g.index) {
      const b = new Set([...g.index.nodes.values()].map(boundaryOf)).size;
      print(`  ✓ mapped ${g.index.nodes.size} intent nodes · ${g.index.edges.length} edges · ${b} boundaries`, "success");
      const dangling = [...g.index.dangling.values()].flat().length;
      if (dangling) print(`  ${dangling} dependency reference(s) point outside the graph`, "muted");
    }
    if (g.status === "error") print(`  ✗ failed to load graph: ${g.error}`, "error");
  }, [g.status, g.revision]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (g.notice) print(`  ${g.notice}`, "muted");
  }, [g.notice, print]);

  // drop selection/focus that no longer exists after a patch
  useEffect(() => {
    if (selectedId && g.index && !g.index.nodes.has(selectedId)) setSelectedId(null);
    setFocus((f) => (f && g.index && [...f.nodeIds].every((id) => g.index!.nodes.has(id)) ? f : null));
  }, [g.index]); // eslint-disable-line react-hooks/exhaustive-deps

  const query = useCallback(
    async (q: string, opts?: RetrievalOptions, kind: Focus["kind"] = "retrieval") => {
      if (!g.retriever || !g.index) return null;
      const r = await g.retriever.retrieve(q, opts);
      const f = focusFromResult(g.index, r, kind, q);
      setFocus(f.nodeIds.size ? f : null);
      return f;
    },
    [g.retriever, g.index],
  );

  /** Select a node and retrieve its 1-hop neighborhood as the active context. */
  const select = useCallback(
    async (id: string | null, log = false) => {
      setSelectedId(id);
      if (!id) return setFocus(null);
      const f = await query(id, { seeds: [id], hops: 1, maxNodes: 12 }, "neighborhood");
      if (log && f && g.index) {
        const n = g.index.nodes.get(id)!;
        setTermOpen(true);
        setTermMin(false);
        print(["", `${prompt}:~$ inspect ${id}`], "prompt");
        print(`  bound ${n.source_file} · ${n.business_invariants.length} invariant(s) · ${f.nodeIds.size} nodes · ~${f.tokens} tokens retrieved`);
      }
    },
    [query, g.index, print, prompt],
  );

  const run = useCallback(
    async (raw: string, echo = true) => {
      if (raw === "clear") return setLines([]);
      if (echo) print(["", `${prompt}:~$ ${raw}`], "prompt");
      const ctx: CommandContext = {
        index: g.index,
        source,
        repo: config.repo,
        focus,
        print,
        clear: () => setLines([]),
        select: (id) => void select(id),
        setFocus,
        query: (q, o) => query(q, o),
        sync: g.sync,
        fit: () => fitView({ padding: 0.12, duration: 300 }),
      };
      setBusy(true);
      try {
        await execute(raw, ctx);
      } finally {
        setBusy(false);
      }
    },
    [g.index, g.sync, focus, print, prompt, select, query, fitView],
  );

  // keyboard: "/" focuses the terminal, Esc clears focus
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement)?.closest("input, textarea");
      if (e.key === "/" && !typing) {
        e.preventDefault();
        setTermOpen(true);
        setTermMin(false);
        requestAnimationFrame(() => inputRef.current?.focus());
      } else if (e.key === "Escape") {
        void select(null);
        (document.activeElement as HTMLElement)?.blur?.();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [select]);

  const syncing = g.status === "syncing" || g.status === "loading";

  return (
    <main className="workspace">
      <header className="legend">
        <div className="journey" aria-label="Modernization pipeline">
          {STAGES.map((s, i) => (
            <span key={s} className="stage">
              {i > 0 ? <b>→</b> : null}
              <span className={g.stage === i ? "active" : ""}>{s}</span>
            </span>
          ))}
        </div>
        <Toolbar onSync={() => run("sync")} syncing={syncing} />
      </header>

      <div className="viewport">
        {g.index ? (
          <GraphCanvas
            index={g.index}
            revision={g.revision}
            focus={focus}
            selectedId={selectedId}
            onSelect={(id) => void select(id, true)}
            insets={{
              left: termOpen && !termMin && window.innerWidth > 900 ? 570 : 40,
              right: selectedId ? 350 : 40,
            }}
          />
        ) : (
          <div className="graph-empty">
            <img src="/assets/94db2.svg" alt="" />
            {g.status === "error" ? (
              <>
                <i className="chalk-note">couldn't reach the intent graph</i>
                <code>{g.error}</code>
                <button onClick={() => g.sync()}>retry</button>
              </>
            ) : (
              <i className="chalk-note">untangling {config.repo}…</i>
            )}
          </div>
        )}
      </div>

      {selectedId && g.index ? (
        <Inspector
          index={g.index}
          nodeId={selectedId}
          focus={focus}
          onSelect={(id) => void select(id, true)}
          onGenerateTests={(id) => {
            setTermOpen(true);
            setTermMin(false);
            void run(`tests ${id}`);
          }}
        />
      ) : null}

      <Terminal
        lines={lines}
        prompt={prompt}
        title={`~ : zsh — Konsole (${source.kind === "mock" ? "local retrieval" : "Nemotron RAG"})`}
        open={termOpen}
        minimized={termMin}
        busy={busy}
        onOpenChange={setTermOpen}
        onMinimizedChange={setTermMin}
        onSubmit={(raw) => void run(raw)}
        inputRef={inputRef}
      />

      <StatusBar g={g} focus={focus} />
    </main>
  );
}

export default function Dashboard() {
  return (
    <ReactFlowProvider>
      <Workspace />
    </ReactFlowProvider>
  );
}
