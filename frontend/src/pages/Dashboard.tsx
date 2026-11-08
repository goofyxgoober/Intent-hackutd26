import { useEffect, useState } from "react";
import { useAuth } from "../auth/AuthContext";

interface Repo {
  id: number;
  full_name: string;
  private: boolean;
  language: string | null;
  updated_at: string;
}

export default function Dashboard() {
  const { user, logout } = useAuth();
  const [repos, setRepos] = useState<Repo[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/github/repos", { credentials: "include" })
      .then((res) => {
        if (!res.ok) throw new Error(`Request failed (${res.status})`);
        return res.json();
      })
      .then(setRepos)
      .catch((e: Error) => setError(e.message));
  }, []);

  return (
    <main className="dashboard">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">◆</span>
          <span>IntentFlow</span>
        </div>
        <div className="user">
          <img src={user!.avatar_url} alt="" width={28} height={28} />
          <span>{user!.name ?? user!.login}</span>
          <button className="btn-ghost" onClick={logout}>
            Sign out
          </button>
        </div>
      </header>

      <section className="panel">
        <h2>Your repositories</h2>
        {error && <div className="alert">{error}</div>}
        {!repos && !error && <p className="muted">Loading repositories…</p>}
        {repos && (
          <ul className="repo-list">
            {repos.map((r) => (
              <li key={r.id}>
                <span className="repo-name">{r.full_name}</span>
                <span className="muted">
                  {r.language ?? "—"} · {r.private ? "private" : "public"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
