"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { api, type Changes, type PollStatus } from "./api";
import { useAuth } from "./AuthContext";
import { Stages, StatusBar, Terminal, TopBar } from "./Chrome";
import { IntentPanel } from "./IntentPanel";
import { RepoPanel, type RepoTab } from "./RepoPanel";
import { workspaceApi, type TreeView } from "./intentApi";
import { useWorkspaceEvents, type WorkspaceEvent } from "./useWorkspaceEvents";

type Line = { text: string; tone?: "green" | "red" | "dim" };

export default function RepoPage({ owner, repo }: { owner: string; repo: string }) {
  const { user, logout } = useAuth();
  const base = `/api/repos/${owner}/${repo}`;

  const [workspaceId, setWorkspaceId] = useState<number | null>(null);
  const [changes, setChanges] = useState<Changes | null>(null);
  const [latest, setLatest] = useState<Changes | null>(null);
  const [poll, setPoll] = useState<PollStatus | null>(null);
  const [tree, setTree] = useState<TreeView | null>(null);
  const [log, setLog] = useState<Line[]>([]);
  const [tab, setTab] = useState<RepoTab>("changes");
  const [historyPath, setHistoryPath] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const wsApi = useMemo(() => (workspaceId === null ? null : workspaceApi(workspaceId)), [workspaceId]);

  const say = useCallback((text: string, tone?: Line["tone"]) => setLog((l) => [...l.slice(-40), { text, tone }]), []);

  const loadTree = useCallback(async () => {
    if (wsApi) setTree(await wsApi.tree());
  }, [wsApi]);

  const loadLatest = useCallback(async () => {
    if (workspaceId === null) return;
    const wsBase = `/api/workspaces/${workspaceId}`;
    // Asking for the status also counts as activity, which keeps polling alive while the page is open.
    setPoll(await api<PollStatus>(`${wsBase}/sync/status`));
    setLatest(await api<Changes | null>(`${wsBase}/sync/latest`));
  }, [workspaceId]);

  useEffect(() => {
    loadLatest().catch(() => undefined);
    const timer = setInterval(() => loadLatest().catch(() => undefined), 10000);
    return () => clearInterval(timer);
  }, [loadLatest]);

  useEffect(() => {
    (async () => {
      try {
        const ws = await api<{ id: number }>(`${base}/connect`, { method: "POST" });
        setWorkspaceId(ws.id);
        setChanges(await api<Changes>(`${base}/changes`));
      } catch (e) {
        say(`✗ ${(e as Error).message}`, "red");
      }
    })();
  }, [base, say]);

  useEffect(() => {
    loadTree().catch((e: Error) => say(`✗ ${e.message}`, "red"));
  }, [loadTree, say]);

  // Agents (and other tabs) change the tree; refresh on their events.
  const live = useWorkspaceEvents(workspaceId, (e: WorkspaceEvent) => {
    if (e.type === "hello") return;
    if (e.type === "sync.batch") {
      const b = e.batch as { id: number; source: string; head: string; initial?: boolean; file_count?: number; affected_tenets: string[] };
      if (b.source !== "manual") {
        const affected = b.affected_tenets.length ? ` · ${b.affected_tenets.length} tenets affected` : "";
        say(
          b.initial
            ? `✓ repo ingested automatically (${b.file_count ?? 0} files at ${b.head.slice(0, 7)})`
            : `⇣ new commits on GitHub · now at ${b.head.slice(0, 7)}${affected}`,
          "green",
        );
      }
      setTab("changes");
      loadLatest().catch(() => undefined);
    }
    else if (e.type === "jev.verdict") say(`jev → ${e.verdict} (${e.confidence}): ${e.reason}`, e.verdict === "axiom_conflict" ? "red" : "dim");
    else if (e.type === "result.appended") say(`test ${e.claim_id} → ${e.verdict}`, e.verdict === "fail" ? "red" : "dim");
    loadTree().catch(() => undefined);
  });

  async function sync() {
    setBusy(true);
    say(`${user!.login}@intentflow:~$ sync ${owner}/${repo}`);
    try {
      const r = await api<Changes>(`${base}/sync`, { method: "POST" });
      if (r.status === "up_to_date") say("✓ already up to date.", "green");
      else if (r.initial) say(`✓ ingested ${r.file_count ?? 0} files at ${r.head.slice(0, 7)}. baseline set.`, "green");
      else
        say(
          `✓ ${r.files.length} files changed · ${r.affected_tenets.length} tenets affected · ${r.rerun_claims.length} claims to re-test`,
          "green",
        );
      setChanges({ ...r, synced: true });
      setTab("changes");
      await Promise.all([loadTree(), loadLatest()]);
    } catch (e) {
      say(`✗ ${(e as Error).message}`, "red");
    } finally {
      setBusy(false);
    }
  }

  async function exportFolder() {
    if (!wsApi) return;
    setBusy(true);
    say(`${user!.login}@intentflow:~$ export intent folder`);
    try {
      const r = await wsApi.exportFolder();
      say(r.changed ? `✓ committed ${r.files} files to ${r.branch} (${r.commit_sha.slice(0, 7)})` : "✓ nothing changed since the last export", "green");
    } catch (e) {
      say(`✗ ${(e as Error).message}`, "red");
    } finally {
      setBusy(false);
    }
  }

  const axioms = tree ? Object.values(tree.claims).filter((c) => c.status === "axiom").length : 0;
  const hypotheses = tree ? Object.values(tree.claims).filter((c) => c.status === "hypothesis").length : 0;

  return (
    <div className="app">
      <TopBar
        right={
          <>
            <span className="user">
              <img src={user!.avatar_url} alt="" width={22} height={22} />
              {user!.login}
            </span>
            <button className="btn" onClick={logout}>
              sign out
            </button>
          </>
        }
      />
      <div className="subbar">
        <Stages active={2} />
        <div className="chips">
          <Link className="chip" href="/dashboard">
            ← repos
          </Link>
          <Link className="chip" href={`/?repo=${encodeURIComponent(`${owner}/${repo}`)}`}>
            graph view →
          </Link>
          <button className="btn" onClick={sync} disabled={busy}>
            sync repo
          </button>
          <button className="btn" onClick={exportFolder} disabled={busy || !tree?.tenets.length}>
            export intent
          </button>
        </div>
      </div>

      <main className="canvas repo-canvas">
        <section className="col">
          <div ref={panelRef}>
            <RepoPanel owner={owner} repo={repo} latest={latest} changes={changes} poll={poll} tab={tab} onTab={setTab}
              historyPath={historyPath} onHistoryPath={setHistoryPath} />
          </div>
          {wsApi && <IntentPanel tree={tree} wsApi={wsApi} say={say} onChanged={() => loadTree()} />}
        </section>

        <Terminal className="dash-terminal">
          <div className="line">
            <span className="purple">⚡ TARGET →</span> {owner}/{repo} ·{" "}
            <span className="purple">{tree?.tenets.length ?? 0} tenets</span>
          </div>
          <div className="line dim">
            axioms → {axioms} · hypotheses → {hypotheses} · live → <span className={live ? "green" : "red"}>{live ? "on" : "off"}</span>
          </div>
          <div className="gap" />
          {log.length === 0 && <div className="line dim">└ sync to ingest the repo; agents' changes appear here live.</div>}
          {log.map((l, i) => (
            <div key={i} className={`line ${l.tone ?? ""}`}>
              {l.text.includes("@intentflow:~$") ? <span className="purple">{l.text}</span> : l.text}
            </div>
          ))}
        </Terminal>
      </main>

      <StatusBar sync="Ayaan OAuth webhook" />
    </div>
  );
}
