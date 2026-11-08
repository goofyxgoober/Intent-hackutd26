import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Changes, type IntentNode } from "../api";
import { useAuth } from "../auth/AuthContext";
import { NodeCard, Stages, StatusBar, Terminal, TopBar } from "../components/Chrome";
import { RepoPanel, type RepoTab } from "../components/RepoPanel";

const blankIntent = (): IntentNode => ({
  node_id: "new_intent",
  name: "",
  source_file: "",
  intent_summary: "",
  inputs: {},
  outputs: {},
  business_invariants: [],
  downstream_dependencies: [],
});

function stripMeta(n: IntentNode): IntentNode {
  const { version: _v, stale: _s, updated_at: _u, ...rest } = n;
  return rest;
}

export default function Repo() {
  const { owner = "", repo = "" } = useParams();
  const { user, logout } = useAuth();
  const base = `/api/repos/${owner}/${repo}`;

  const [changes, setChanges] = useState<Changes | null>(null);
  const [intents, setIntents] = useState<IntentNode[] | null>(null);
  const [log, setLog] = useState<{ text: string; tone?: "green" | "red" | "dim" }[]>([]);
  const [editing, setEditing] = useState<{ original: IntentNode | null; text: string } | null>(null);
  const [tab, setTab] = useState<RepoTab>("changes");
  const [historyPath, setHistoryPath] = useState<string | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [busy, setBusy] = useState(false);

  const say = (text: string, tone?: "green" | "red" | "dim") =>
    setLog((l) => [...l.slice(-30), { text, tone }]);

  const loadIntents = useCallback(async () => {
    setIntents(await api<IntentNode[]>(`${base}/intents`));
  }, [base]);

  const load = useCallback(async () => {
    try {
      await api(`${base}/connect`, { method: "POST" });
      const [c] = await Promise.all([api<Changes>(`${base}/changes`), loadIntents()]);
      setChanges(c);
    } catch (e) {
      say(`✗ ${(e as Error).message}`, "red");
    }
  }, [base, loadIntents]);

  useEffect(() => {
    load();
  }, [load]);

  async function sync() {
    setBusy(true);
    say(`${user!.login}@intentflow:~$ sync ${owner}/${repo}`);
    try {
      const r = await api<Changes>(`${base}/sync`, { method: "POST" });
      say(
        r.initial_sync
          ? `✓ baseline set at ${r.head.slice(0, 7)}. future changes are tracked from here.`
          : `✓ ${r.files.length} files changed · ${r.stale_marked ?? 0} intents flagged stale`,
        "green",
      );
      // Keep showing what this sync covered; the next preview starts from the new head.
      setChanges(r);
      setTab("changes");
      await loadIntents();
    } catch (e) {
      say(`✗ ${(e as Error).message}`, "red");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!editing) return;
    let node: IntentNode;
    try {
      node = JSON.parse(editing.text);
    } catch {
      say("✗ intent JSON is invalid. check commas and quotes.", "red");
      return;
    }
    setBusy(true);
    try {
      const params = editing.original?.version ? `?expected_version=${editing.original.version}` : "";
      const saved = await api<IntentNode>(`${base}/intents/${encodeURIComponent(node.node_id)}${params}`, {
        method: "PUT",
        body: JSON.stringify(node),
      });
      say(`✓ saved ${saved.node_id} (v${saved.version})`, "green");
      setEditing(null);
      await loadIntents();
    } catch (e) {
      say(`✗ ${(e as Error).message}`, "red");
    } finally {
      setBusy(false);
    }
  }

  async function remove(node: IntentNode) {
    setBusy(true);
    try {
      await api(`${base}/intents/${encodeURIComponent(node.node_id)}`, { method: "DELETE" });
      say(`✓ deleted ${node.node_id}`, "green");
      setEditing(null);
      await loadIntents();
    } catch (e) {
      say(`✗ ${(e as Error).message}`, "red");
    } finally {
      setBusy(false);
    }
  }

  async function exportIntents() {
    setBusy(true);
    say(`${user!.login}@intentflow:~$ export intents`);
    try {
      const r = await api<{ branch: string; path: string; commit_sha: string }>(`${base}/intents/export`, {
        method: "POST",
      });
      say(`✓ committed ${r.path} to ${r.branch} (${r.commit_sha.slice(0, 7)})`, "green");
    } catch (e) {
      say(`✗ ${(e as Error).message}`, "red");
    } finally {
      setBusy(false);
    }
  }

  const affected = new Set(changes?.affected_intents ?? []);

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
          <Link className="chip" to="/dashboard">
            ← repos
          </Link>
          <button className="btn" onClick={sync} disabled={busy}>
            sync repo
          </button>
          <button className="btn" onClick={exportIntents} disabled={busy || !intents?.length}>
            export intents
          </button>
        </div>
      </div>

      <main className="canvas repo-canvas">
        <section className="col">
          <div ref={panelRef}>
            <RepoPanel
              owner={owner}
              repo={repo}
              changes={changes}
              tab={tab}
              onTab={setTab}
              historyPath={historyPath}
              onHistoryPath={setHistoryPath}
            />
          </div>

          <div className="section-head">
            <h2 className="hand">functional intents</h2>
            <button className="btn" onClick={() => setEditing({ original: null, text: JSON.stringify(blankIntent(), null, 2) })}>
              + new intent
            </button>
          </div>

          {editing && (
            <NodeCard name={editing.original ? `edit ${editing.original.node_id}` : "new intent"} tag="IntentNode JSON">
              <textarea
                id="intent-editor"
                className="editor"
                spellCheck={false}
                value={editing.text}
                onChange={(e) => setEditing({ ...editing, text: e.target.value })}
              />
              <div className="row-actions">
                <button className="btn primary" onClick={save} disabled={busy}>
                  save
                </button>
                <button className="btn" onClick={() => setEditing(null)}>
                  cancel
                </button>
                {editing.original && (
                  <button className="btn danger" onClick={() => remove(editing.original!)} disabled={busy}>
                    delete
                  </button>
                )}
              </div>
            </NodeCard>
          )}

          {intents && intents.length === 0 && !editing && (
            <p className="hand dim empty">No intents stored for this repo yet. Add one, or let the intent engine fill them in.</p>
          )}
          <div className="intent-grid">
            {intents?.map((n) => (
              <NodeCard
                key={n.node_id}
                name={n.node_id}
                tag={n.stale ? "stale" : affected.has(n.node_id) ? "file changed" : `v${n.version}`}
                tagTone={n.stale || affected.has(n.node_id) ? "warn" : "muted"}
                summary={n.intent_summary || n.name}
                className={n.stale ? "node-stale" : ""}
              >
                <div className="mono-list">
                  <div>{n.source_file}</div>
                  {n.business_invariants.slice(0, 2).map((inv) => (
                    <div key={inv}>• {inv}</div>
                  ))}
                </div>
                <div className="card-actions">
                  <button
                    className="link-purple as-button"
                    onClick={() => setEditing({ original: n, text: JSON.stringify(stripMeta(n), null, 2) })}
                  >
                    [edit intent]
                  </button>
                  <button
                    className="link-purple as-button"
                    onClick={() => {
                      setHistoryPath(n.source_file);
                      setTab("history");
                      panelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
                    }}
                  >
                    [history]
                  </button>
                </div>
              </NodeCard>
            ))}
          </div>
        </section>

        <Terminal className="dash-terminal">
          <div className="line">
            <span className="purple">⚡ TARGET →</span> {owner}/{repo} ·{" "}
            <span className="purple">{intents?.length ?? 0} intents</span>
          </div>
          <div className="line dim">
            last sync →{" "}
            {changes?.stale_marked !== undefined
              ? changes.head.slice(0, 7)
              : changes?.base
                ? changes.base.slice(0, 7)
                : "never"} · stale →{" "}
            {intents?.filter((n) => n.stale).length ?? 0}
          </div>
          <div className="gap" />
          {log.length === 0 && <div className="line dim">└ sync to track modified files; edit intents on the left.</div>}
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
