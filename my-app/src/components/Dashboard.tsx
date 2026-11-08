"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ReactFlowProvider, useReactFlow, useViewport } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { getConfig, createSource } from "@/lib/api/config";
import { useIntentGraph, type IntentGraphState } from "@/hooks/useIntentGraph";
import { boundaryOf } from "@/lib/graph/model";
import { focusFromIds, focusFromResult, type Focus } from "@/lib/focus";
import { useTenetTree } from "@/hooks/useTenetTree";
import { graphNodesFor, tenetsForNode } from "@/lib/tenetLinks";
import type { RetrievalOptions } from "@/lib/retrieval/engine";
import { execute, type CommandContext, type Line, type Tone } from "@/lib/terminal/commands";
import { GraphCanvas } from "@/components/graph/GraphCanvas";
import { Inspector } from "@/components/Inspector";
import { Terminal } from "@/components/Terminal";
import { TenetCanvas } from "@/components/tenets/TenetCanvas";
import { TenetInspector } from "@/components/tenets/TenetInspector";
import { ClaimDetail } from "@/components/tenets/ClaimDetail";
import { Guide } from "@/components/panel/Guide";
import { TokenMeter } from "@/components/panel/TokenMeter";

type View = "graph" | "tenets";

// Client-only module (loaded with ssr:false), so window/location are safe here.
const config = getConfig();
const source = createSource(config);
const STAGES = ["Raw AST", "Intent graph", "Modern merge"];

const VIEWS: { id: View; label: string; hint: string }[] = [
  { id: "graph", label: "Codebase", hint: "What the code does" },
  { id: "tenets", label: "Tenets", hint: "What it must keep true" },
];

function ViewSwitch({ view, onChange }: { view: View; onChange(v: View): void }) {
  return (
    <div className="view-switch" role="tablist" aria-label="Workspace view" data-view={view}>
      <i className="vs-pill" aria-hidden />
      {VIEWS.map((v) => (
        <button key={v.id} role="tab" aria-selected={view === v.id} className={view === v.id ? "active" : ""} onClick={() => onChange(v.id)} title={v.hint}>
          {v.label}
        </button>
      ))}
    </div>
  );
}

const Icon = {
  minus: <path d="M5 12h14" />,
  plus: <path d="M12 5v14M5 12h14" />,
  sync: <path d="M20 11a8 8 0 0 0-14-4M4 5v4h4M4 13a8 8 0 0 0 14 4m2 2v-4h-4" />,
  git: <path d="M9 19c-4 1-4-2-6-2m12 4v-3.500a3 3 0 0 0-1-2.500c3 0 6-1.500 6-6a4.600 4.600 0 0 0-1.300-3.200 4.200 4.200 0 0 0-.1-3.200s-1.100-.3-3.500 1.300a12 12 0 0 0-6.200 0C6.500 2.800 5.400 3.100 5.400 3.100a4.200 4.200 0 0 0-.1 3.200A4.600 4.600 0 0 0 4 9.500c0 4.600 3 6 6 6a3 3 0 0 0-1 2.500V21" />,
};
const Svg = ({ d, spin }: { d: keyof typeof Icon; spin?: boolean }) => (
  <svg className={spin ? "spin" : ""} viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    {Icon[d]}
  </svg>
);

interface Me { login: string; avatar_url: string }

/** Who the backend thinks is signed in (the GitHub session cookie), or null. Offline fixture has no account. */
function useMe(): Me | null | undefined {
  const [me, setMe] = useState<Me | null | undefined>(source.kind === "http" ? undefined : null);
  useEffect(() => {
    if (source.kind !== "http") return;
    let off = false;
    fetch("/auth/me", { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((u) => !off && setMe(u))
      .catch(() => !off && setMe(null));
    return () => {
      off = true;
    };
  }, []);
  return me;
}

function Toolbar({ onSync, syncing, view }: { onSync(): void; syncing: boolean; view: View }) {
  const { zoom } = useViewport();
  const { zoomIn, zoomOut, fitView } = useReactFlow();
  const me = useMe();
  return (
    <div className="toolbar">
      <span className="tb-hint" aria-hidden>
        <kbd>click</kbd> {view === "graph" ? "a node" : "a tenet"} <kbd>/</kbd> ask <kbd>esc</kbd> clear
      </span>
      <div className="tb-group" role="group" aria-label="Zoom">
        <button onClick={() => zoomOut({ duration: 150 })} aria-label="Zoom out"><Svg d="minus" /></button>
        <button className="tb-zoom" onClick={() => fitView({ padding: 0.12, duration: 300 })} title="Fit graph to screen">
          {Math.round(zoom * 100)}%
        </button>
        <button onClick={() => zoomIn({ duration: 150 })} aria-label="Zoom in"><Svg d="plus" /></button>
      </div>
      <Guide />
      <a className="tb-ghost" href="/dashboard" title="GitHub repos, sync and history"><Svg d="git" /> Repos</a>
      {me === null && source.kind === "http" ? (
        <a className="tb-ghost" href="/login">Sign in</a>
      ) : me ? (
        <a className="tb-me" href="/dashboard" title={`Signed in as ${me.login}`}>
          <img src={me.avatar_url} alt="" width={22} height={22} />
        </a>
      ) : null}
      <button className={`tb-primary ${syncing ? "syncing" : ""}`} onClick={onSync} disabled={syncing}>
        <Svg d="sync" spin={syncing} /> {syncing ? "Syncing" : "Sync repo"}
      </button>
    </div>
  );
}

function StatusBar({ g, focus, view, tenets }: { g: IntentGraphState; focus: Focus | null; view: View; tenets: ReturnType<typeof useTenetTree> }) {
  const boundaries = useMemo(
    () => (g.index ? new Set([...g.index.nodes.values()].map(boundaryOf)).size : 0),
    [g.index],
  );
  const ts = useMemo(() => {
    const t = tenets.tree?.tenets ?? [];
    return { n: t.length, a: t.reduce((x, y) => x + (y.is_leaf ? y.axioms : 0), 0), h: t.reduce((x, y) => x + (y.is_leaf ? y.hypotheses : 0), 0), f: t.reduce((x, y) => x + y.flagged_axioms, 0) };
  }, [tenets.tree]);
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
        {view === "tenets" ? (
          <>
            <i>·</i>
            <span>
              tenets: <b>{tenets.tree ? `${ts.n} · ${ts.a}A · ${ts.h}H${ts.f ? ` · ⚑${ts.f}` : ""}` : "—"}</b>
            </span>
            <i>·</i>
            <span>
              intent api: <b>{tenets.offline ? "fixture (offline)" : tenets.live ? "live" : tenets.status}</b>
            </span>
          </>
        ) : null}
      </div>
      <p>
        {view === "tenets" ? (
          tenets.tree ? `“${ts.n} tenets · ${ts.a} axioms locked · ${ts.h} hypotheses open”` : tenets.status === "signin" ? "“sign in to load the tenet hierarchy”" : "“reading the tenet tree…”"
        ) : g.index
          ? `“${g.index.repo}: ${g.index.nodes.size} intent nodes across ${boundaries} boundaries”`
          : g.status === "error"
            ? "“graph unavailable”"
            : "“distilling ast…”"}
        {view === "graph" && focus && g.index ? <TokenMeter index={g.index} focus={focus} /> : null}
      </p>
    </footer>
  );
}

function Workspace() {
  const g = useIntentGraph(source, config.repo);
  const { fitView } = useReactFlow();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focus, setFocus] = useState<Focus | null>(null);
  const [view, setViewState] = useState<View>(() => (new URLSearchParams(window.location.search).get("view") === "tenets" ? "tenets" : "graph"));
  const [tenetId, setTenetId] = useState<string | null>(null);
  const [claimId, setClaimId] = useState<string | null>(null);
  const [tenetHit, setTenetHit] = useState<Set<string> | null>(null);
  const tenets = useTenetTree(source, config.repo, true);
  // a claim that was scrapped away or removed by a sync simply closes
  const openClaimId = claimId && tenets.tree?.claims[claimId] ? claimId : null;
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

  useEffect(() => {
    if (tenets.notice) print(`  ${tenets.notice}`, "muted");
  }, [tenets.notice, print]);

  const setView = useCallback((v: View) => {
    setViewState(v);
    const url = new URL(window.location.href);
    if (v === "tenets") url.searchParams.set("view", "tenets");
    else url.searchParams.delete("view");
    window.history.replaceState(null, "", url);
  }, []);

  const ancestry = useCallback(
    (id: string) => {
      const byId = new Map((tenets.tree?.tenets ?? []).map((t) => [t.id, t]));
      const out = new Set<string>();
      for (let t = byId.get(id); t && !out.has(t.id); t = t.parent_id ? byId.get(t.parent_id) : undefined) out.add(t.id);
      return out;
    },
    [tenets.tree],
  );

  /** Jump to a tenet in the hierarchy view, lighting up its path from the root. */
  const openTenet = useCallback(
    (id: string | null) => {
      setTenetId(id);
      setClaimId(null);
      setTenetHit(id ? ancestry(id) : null);
      if (id) setView("tenets");
    },
    [ancestry, setView],
  );

  /** Open one axiom/hypothesis in the detail drawer (and select its tenet). */
  const openClaim = useCallback(
    (id: string | null) => {
      const c = id ? tenets.tree?.claims[id] : null;
      setClaimId(c ? id : null);
      if (c) {
        setTenetId(c.tenet_id);
        setTenetHit(null);
        setView("tenets");
      }
    },
    [tenets.tree, setView],
  );

  /** Jump from a tenet to the graph nodes that implement it. */
  const showTenetInGraph = useCallback(
    (id: string) => {
      if (!g.index || !tenets.tree) return;
      const nodes = graphNodesFor(g.index, tenets.tree, id);
      const t = tenets.tree.tenets.find((x) => x.id === id);
      setView("graph");
      if (!nodes.length) {
        print(`  no graph nodes are bound to ${t?.name ?? id} yet`, "muted");
        return;
      }
      setFocus(focusFromIds(g.index, nodes.map((n) => n.id), "downstream", `tenet: ${t?.name ?? id}`));
      setSelectedId(nodes.length === 1 ? nodes[0].id : null);
      print(`  ${t?.name ?? id} → ${nodes.length} graph node(s): ${nodes.map((n) => n.id).join(", ")}`, "muted");
    },
    [g.index, tenets.tree, print, setView],
  );

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
        sync: async () => {
          await g.sync();
          await tenets.reload();
        },
        tenets: tenets.tree,
        view,
        setView,
        selectTenet: openTenet,
        openClaim,
        selection: {
          view: view === "tenets" ? "intent" : "codebase",
          tenet_id: tenetId,
          claim_id: openClaimId,
          file: selectedId ? (g.index?.nodes.get(selectedId)?.source_file ?? null) : null,
        },
        fit: () => fitView({ padding: 0.12, duration: 300 }),
      };
      setBusy(true);
      try {
        await execute(raw, ctx);
      } finally {
        setBusy(false);
      }
    },
    [g.index, g.sync, focus, print, prompt, select, query, fitView, tenets, view, setView, openTenet, openClaim, tenetId, openClaimId, selectedId],
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
        setTenetId(null);
        setClaimId(null);
        setTenetHit(null);
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
        <ViewSwitch view={view} onChange={setView} />
        <ol className="journey" aria-label="Modernization pipeline">
          {STAGES.map((label, i) => (
            <li key={label} className={g.stage > i ? "done" : g.stage === i ? "active" : ""} aria-current={g.stage === i ? "step" : undefined}>
              <i aria-hidden>{g.stage > i ? "✓" : i + 1}</i>
              <span>{label}</span>
            </li>
          ))}
        </ol>
        <Toolbar onSync={() => run("sync")} syncing={syncing} view={view} />
      </header>

      <div className="viewport">
        {view === "tenets" ? (
          tenets.tree && tenets.tree.tenets.length ? (
            <TenetCanvas
              tree={tenets.tree}
              selectedId={tenetId}
              highlight={tenetHit}
              onSelect={(id) => {
                setTenetId(id);
                setClaimId(null);
                setTenetHit(null);
              }}
              insets={{
                left: termOpen && !termMin && window.innerWidth > 900 ? 570 : 40,
                right: openClaimId ? 520 : tenetId ? 450 : 40,
              }}
            />
          ) : (
            <div className="graph-empty">
              <img src="/assets/94db2.svg" alt="" />
              {tenets.status === "signin" ? (
                <>
                  <i className="chalk-note">sign in to read the tenet hierarchy</i>
                  <a className="empty-link" href="/login">sign in with github</a>
                </>
              ) : tenets.status === "unlinked" ? (
                <>
                  <i className="chalk-note">{config.repo} isn&apos;t connected to a workspace yet</i>
                  <a className="empty-link" href="/dashboard">connect a github repo</a>
                  <code>or open ?repo=owner/name</code>
                </>
              ) : tenets.status === "error" ? (
                <>
                  <i className="chalk-note">couldn&apos;t reach the intent engine</i>
                  <code>{tenets.error}</code>
                  <button onClick={() => void tenets.reload()}>retry</button>
                </>
              ) : tenets.status === "ready" ? (
                <i className="chalk-note">no tenets yet: the intent builder drafts the root from the code</i>
              ) : (
                <i className="chalk-note">reading the tenet tree…</i>
              )}
            </div>
          )
        ) : g.index && g.index.nodes.size > 0 ? (
          <GraphCanvas
            index={g.index}
            revision={g.revision}
            focus={focus}
            selectedId={selectedId}
            onSelect={(id) => void select(id, true)}
            insets={{
              left: termOpen && !termMin && window.innerWidth > 900 ? 570 : 40,
              right: selectedId ? 415 : 40,
            }}
          />
        ) : (
          <div className="graph-empty">
            <img src="/assets/94db2.svg" alt="" />
            {g.status === "error" && /^401/.test(g.error ?? "") ? (
              <>
                <i className="chalk-note">sign in to read {config.repo}</i>
                <a className="empty-link" href="/login">sign in with github</a>
              </>
            ) : g.status === "error" && /^404/.test(g.error ?? "") ? (
              <>
                <i className="chalk-note">{config.repo} isn&apos;t connected yet</i>
                <a className="empty-link" href="/dashboard">connect a github repo</a>
              </>
            ) : g.status === "error" ? (
              <>
                <i className="chalk-note">couldn&apos;t reach the intent graph</i>
                <code>{g.error}</code>
                <button onClick={() => g.sync()}>retry</button>
              </>
            ) : g.index ? (
              <>
                <i className="chalk-note">{config.repo} hasn&apos;t been read yet</i>
                <code>pull the code, map the imports, draft the first tenets</code>
                <button onClick={() => void run("sync")} disabled={syncing}>{syncing ? "reading the code…" : "read this repo"}</button>
              </>
            ) : (
              <i className="chalk-note">untangling {config.repo}…</i>
            )}
          </div>
        )}
      </div>

      {view === "tenets" && openClaimId && tenets.tree ? (
        <ClaimDetail
          key={openClaimId}
          tree={tenets.tree}
          claimId={openClaimId}
          wsApi={tenets.wsApi}
          onBack={() => setClaimId(null)}
          onClose={() => {
            setClaimId(null);
            setTenetId(null);
          }}
          onOpenClaim={openClaim}
          onOpenTenet={openTenet}
          onChanged={() => void tenets.reload()}
          say={(t, tone) => print(t, tone)}
        />
      ) : view === "tenets" && tenetId && tenets.tree ? (
        <TenetInspector
          tree={tenets.tree}
          tenetId={tenetId}
          wsApi={tenets.wsApi}
          graphNodes={graphNodesFor(g.index, tenets.tree, tenetId)}
          activeClaim={null}
          onOpenClaim={openClaim}
          onSelect={(id) => {
            setTenetId(id);
            setTenetHit(id ? ancestry(id) : null);
          }}
          onShowInGraph={showTenetInGraph}
          onChanged={() => void tenets.reload()}
          say={(t, tone) => print(t, tone)}
        />
      ) : null}

      {view === "graph" && selectedId && g.index ? (
        <Inspector
          index={g.index}
          nodeId={selectedId}
          focus={focus}
          tenets={tenetsForNode(tenets.tree, selectedId, g.index.nodes.get(selectedId)?.source_file ?? "")}
          onOpenTenet={openTenet}
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

      <StatusBar g={g} focus={focus} view={view} tenets={tenets} />
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
