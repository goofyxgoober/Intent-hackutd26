"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "./AuthContext";
import { NodeCard, TopBar } from "./Chrome";

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

  if (!user) return <div className="centered muted">Loading…</div>;
  const login = user.login;

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
              Sign out
            </button>
          </>
        }
      />
      <div className="subbar">
        <h1 className="page-title">Repositories</h1>
        <p className="page-sub">Choose a repository to open its graph, sync it or review its history.</p>
      </div>

      <main className="canvas dash-canvas">
        <section className="repo-grid">
          {error && (
            <NodeCard name="Couldn't list repositories" tag="GitHub">
              <div className="mono-list red">{error}</div>
            </NodeCard>
          )}
          {!repos && !error && <p className="dim loading">Loading repositories…</p>}
          {repos?.map((r) => (
            <NodeCard
              key={r.id}
              name={r.full_name.split("/")[1]}
              tag={r.private ? "private" : "public"}
              tagTone={r.private ? "muted" : "ok"}
              className="repo-node"
            >
              <div className="mono-list">
                <div>{r.full_name.split("/")[0]}</div>
                <div>{r.language ?? "No language"} · {r.default_branch}</div>
              </div>
              <div className="card-actions">
                <Link className="link-purple" href={`/?repo=${encodeURIComponent(r.full_name)}`}>
                  Open graph
                </Link>
                <Link className="link-purple" href={`/repos/${r.full_name}`}>
                  Sync &amp; history
                </Link>
              </div>
            </NodeCard>
          ))}
        </section>
      </main>

    </div>
  );
}
