"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "./AuthContext";
import { NodeCard, PROMPT, Stages, StatusBar, Terminal, TopBar } from "./Chrome";

interface Repo {
  id: number;
  full_name: string;
  private: boolean;
  default_branch: string;
  language: string | null;
  updated_at: string;
}

export default function DashboardPage() {
  const { user, logout } = useAuth();
  const [repos, setRepos] = useState<Repo[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/github/repos", { credentials: "include" })
      .then((res) => {
        if (!res.ok) throw new Error(`GET /api/github/repos → ${res.status}`);
        return res.json();
      })
      .then(setRepos)
      .catch((e: Error) => setError(e.message));
  }, []);

  const login = user!.login;

  return (
    <div className="app">
      <TopBar
        right={
          <>
            <span className="user">
              <img src={user!.avatar_url} alt="" width={22} height={22} />
              {login}
            </span>
            <button className="btn" onClick={logout}>
              sign out
            </button>
          </>
        }
      />
      <div className="subbar">
        <Stages active={1} />
        <div className="chips">
          <span className="chip">select a repo to sync</span>
        </div>
      </div>

      <main className="canvas dash-canvas">
        <section className="repo-grid">
          {error && (
            <NodeCard name="sync_error" tag="github" summary="Couldn't list repositories.">
              <div className="mono-list red">{error}</div>
            </NodeCard>
          )}
          {!repos && !error && <p className="hand dim loading">fetching repositories…</p>}
          {repos?.map((r) => (
            <NodeCard
              key={r.id}
              name={r.full_name.split("/")[1]}
              tag={r.private ? "private" : "public"}
              tagTone={r.private ? "muted" : "ok"}
              className="repo-node"
            >
              <div className="mono-list">
                <div>owner: {r.full_name.split("/")[0]}</div>
                <div>lang: {r.language ?? "—"}</div>
                <div>branch: {r.default_branch}</div>
              </div>
              <Link className="link-purple" href={`/?repo=${encodeURIComponent(r.full_name)}`}>
                [open graph]
              </Link>{" "}
              <Link className="link-purple" href={`/repos/${r.full_name}`}>
                [sync &amp; history]
              </Link>
            </NodeCard>
          ))}
        </section>

        <Terminal
          className="dash-terminal"
          footer={
            <div className="cta static">
              <span className="prompt">{PROMPT.replace("ayaan", login)}</span>
              <span className="cta-input placeholder">ask intent or execute command…</span>
              <span className="enter">↵</span>
            </div>
          }
        >
          <div className="line">
            <span className="purple">⚡ DISTRO →</span> Arch Linux x86_64 ·{" "}
            <span className="purple">Nemotron 70B Agentic Core</span>
          </div>
          <div className="line dim">
            GITHUB → <span className="text">{user!.name ?? login}</span> · session active
          </div>
          <div className="gap" />
          <div className="line">
            <span className="purple">{login}@intentflow:~$</span> repo list
          </div>
          <div className="line dim">
            └ {repos ? `${repos.length} repositories accessible` : "loading…"}
          </div>
          <div className="line green">✓ github oauth session verified.</div>
        </Terminal>
      </main>

      <StatusBar sync="Ayaan OAuth webhook" />
    </div>
  );
}
