import { useEffect, useState } from "react";
import { api, type Changes, type CommitDetail, type CommitSummary, type Comparison } from "../api";
import { NodeCard } from "./Chrome";
import { CommitList, FileDiffList, shortSha } from "./GitViews";

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
/** Commit message without its first line (already shown in the row). */
const body = (message: string) => message.split("\n").slice(1).join("\n").trim();

export type RepoTab = "changes" | "history" | "compare";

interface Props {
  owner: string;
  repo: string;
  changes: Changes | null;
  tab: RepoTab;
  onTab: (t: RepoTab) => void;
  historyPath: string | null;
  onHistoryPath: (path: string | null) => void;
}

export function RepoPanel({ owner, repo, changes, tab, onTab, historyPath, onHistoryPath }: Props) {
  const gh = `/api/github/repos/${owner}/${repo}`;
  const showHistory = (path: string) => {
    onHistoryPath(path);
    onTab("history");
  };

  return (
    <NodeCard name={`${owner}/${repo}`} tag={changes ? `head ${shortSha(changes.head)}` : "loading…"}>
      <div className="tabs" role="tablist">
        {(["changes", "history", "compare"] as RepoTab[]).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            className={tab === t ? "tab active" : "tab"}
            onClick={() => onTab(t)}
          >
            {t}
          </button>
        ))}
      </div>
      {tab === "changes" && <ChangesTab changes={changes} gh={gh} onHistory={showHistory} />}
      {tab === "history" && <HistoryTab gh={gh} path={historyPath} onPath={onHistoryPath} />}
      {tab === "compare" && <CompareTab gh={gh} onHistory={showHistory} />}
    </NodeCard>
  );
}

function ChangesTab({ changes, gh, onHistory }: { changes: Changes | null; gh: string; onHistory: (p: string) => void }) {
  if (!changes) return <p className="hand dim lead">Reading the repository…</p>;
  if (changes.initial_sync)
    return <p className="hand lead">Not synced yet. Sync to set a baseline for tracking changes.</p>;
  if (changes.files.length === 0) return <p className="hand lead">Up to date with the last sync.</p>;
  const range = `${shortSha(changes.base ?? "")} → ${shortSha(changes.head)}`;
  return (
    <>
      <p className="hand lead">
        {changes.stale_marked !== undefined
          ? `${plural(changes.files.length, "file")} modified in this sync (${range}).`
          : `${plural(changes.files.length, "file")} modified since the last sync (${range}).`}
      </p>
      <FileDiffList
        files={changes.files}
        rawDiffUrl={changes.base ? `${gh}/diff?base=${changes.base}&head=${changes.head}` : undefined}
        onHistory={onHistory}
      />
    </>
  );
}

function HistoryTab({ gh, path, onPath }: { gh: string; path: string | null; onPath: (p: string | null) => void }) {
  const [commits, setCommits] = useState<CommitSummary[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, CommitDetail>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setCommits(null);
    setSelected(null);
    setError(null);
    const q = new URLSearchParams({ limit: "30" });
    if (path) q.set("path", path);
    api<CommitSummary[]>(`${gh}/commits?${q}`)
      .then(setCommits)
      .catch((e: Error) => setError(e.message));
  }, [gh, path]);

  function select(sha: string) {
    setSelected(selected === sha ? null : sha);
    if (!details[sha]) {
      api<CommitDetail>(`${gh}/commits/${sha}`)
        .then((d) => setDetails((all) => ({ ...all, [sha]: d })))
        .catch((e: Error) => setError(e.message));
    }
  }

  return (
    <>
      <div className="filter-row">
        {path ? (
          <span className="chip">
            history of <b>{path}</b>{" "}
            <button className="as-button chip-x" onClick={() => onPath(null)} aria-label="Show all commits">
              ×
            </button>
          </span>
        ) : (
          <span className="dim small">All commits on the default branch. Click one to see its diffs.</span>
        )}
      </div>
      {error && <p className="red small">✗ {error}</p>}
      {!commits && !error && <p className="hand dim lead">Loading commits…</p>}
      {commits && (
        <CommitList
          commits={commits}
          selected={selected}
          onSelect={select}
          renderDetail={(sha) => {
            const d = details[sha];
            if (!d) return <p className="dim small detail">Loading commit…</p>;
            return (
              <div className="detail">
                {body(d.full_message) && <pre className="commit-body">{body(d.full_message)}</pre>}
                <p className="dim small">
                  {plural(d.files.length, "file")} · <span className="green">+{d.stats.additions ?? 0}</span>{" "}
                  <span className="red">−{d.stats.deletions ?? 0}</span>
                  {d.html_url && (
                    <>
                      {" · "}
                      <a className="link-purple" href={d.html_url} target="_blank" rel="noreferrer">
                        [view on GitHub]
                      </a>
                    </>
                  )}
                </p>
                <FileDiffList files={d.files} rawDiffUrl={`${gh}/diff?sha=${sha}`} onHistory={(p) => onPath(p)} />
              </div>
            );
          }}
        />
      )}
    </>
  );
}

function CompareTab({ gh, onHistory }: { gh: string; onHistory: (p: string) => void }) {
  const [branches, setBranches] = useState<{ name: string; sha: string }[]>([]);
  const [base, setBase] = useState("");
  const [head, setHead] = useState("");
  const [result, setResult] = useState<Comparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<{ name: string; sha: string }[]>(`${gh}/branches`)
      .then((b) => {
        setBranches(b);
        const main = b.find((x) => x.name === "main" || x.name === "master")?.name ?? b[0]?.name ?? "";
        setBase(main);
        setHead(b.find((x) => x.name !== main)?.name ?? main);
      })
      .catch((e: Error) => setError(e.message));
  }, [gh]);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setResult(await api<Comparison>(`${gh}/compare?${new URLSearchParams({ base, head })}`));
    } catch (err) {
      setResult(null);
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <form className="compare-form" onSubmit={run}>
        <datalist id="branch-names">
          {branches.map((b) => (
            <option key={b.name} value={b.name} />
          ))}
        </datalist>
        <label>
          <span className="dim small">base</span>
          <input id="compare-base" list="branch-names" value={base} onChange={(e) => setBase(e.target.value)} placeholder="main or a commit sha" />
        </label>
        <span className="dim compare-dots">…</span>
        <label>
          <span className="dim small">head</span>
          <input id="compare-head" list="branch-names" value={head} onChange={(e) => setHead(e.target.value)} placeholder="branch or commit sha" />
        </label>
        <button className="btn primary" disabled={busy || !base || !head}>
          compare
        </button>
      </form>
      {error && <p className="red small">✗ {error}</p>}
      {result && (
        <>
          <p className="hand lead">
            {result.head} is {plural(result.ahead_by, "commit")} ahead and {result.behind_by} behind {result.base}.
          </p>
          {result.commits.length > 0 && <CommitList commits={result.commits} />}
          <FileDiffList
            files={result.files}
            rawDiffUrl={`${gh}/diff?${new URLSearchParams({ base: result.base, head: result.head })}`}
            onHistory={onHistory}
          />
          {result.truncated && <p className="dim small">GitHub lists at most 300 files per comparison.</p>}
        </>
      )}
    </>
  );
}
