"use client";

import { useState } from "react";
import type { ChangedFile, CommitSummary } from "./api";

export function shortSha(sha: string) {
  return sha.slice(0, 7);
}

export function timeAgo(iso: string) {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)}d ago`;
  return new Date(iso).toLocaleDateString();
}

function fmtRanges(ranges: [number, number][]): string {
  return ranges.map(([a, b]) => (a === b ? `${a}` : `${a}–${b}`)).join(", ");
}

/** "+ lines 12–15, 40 · − line 11" for one file. */
export function ChangedLines({ file }: { file: ChangedFile }) {
  const cl = file.changed_lines;
  if (!cl || (cl.added.length === 0 && cl.removed.length === 0)) return null;
  const count = (r: [number, number][]) => r.reduce((n, [a, b]) => n + b - a + 1, 0);
  return (
    <div className="changed-lines small">
      {cl.added.length > 0 && (
        <span className="green">+ line{count(cl.added) === 1 ? "" : "s"} {fmtRanges(cl.added)}</span>
      )}
      {cl.added.length > 0 && cl.removed.length > 0 && <span className="dim"> · </span>}
      {cl.removed.length > 0 && (
        <span className="red">− line{count(cl.removed) === 1 ? "" : "s"} {fmtRanges(cl.removed)}</span>
      )}
    </div>
  );
}

/** Changed files with +/- counts and line numbers; click a file to show its diff. */
export function FileDiffList({
  files,
  rawDiffUrl,
  onHistory,
}: {
  files: ChangedFile[];
  rawDiffUrl?: string;
  onHistory?: (path: string) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  if (files.length === 0) return <p className="dim small">No file changes.</p>;
  return (
    <ul className="file-list">
      {files.map((f) => (
        <li key={f.path}>
          <div className="file-line">
            <button className="file-row" onClick={() => setOpen(open === f.path ? null : f.path)}>
              <span className={`fstatus ${f.status}`}>{f.status}</span>
              <span className="fpath">{f.previous_path ? `${f.previous_path} → ${f.path}` : f.path}</span>
              <span className="fdelta">
                <span className="green">+{f.additions}</span> <span className="red">−{f.deletions}</span>
              </span>
            </button>
            {onHistory && (
              <button className="link-purple as-button file-history" onClick={() => onHistory(f.path)}>
                [history]
              </button>
            )}
          </div>
          <ChangedLines file={f} />
          {open === f.path &&
            (f.patch ? (
              <pre className="patch">
                {f.patch.split("\n").map((line, i) => (
                  <span
                    key={i}
                    className={
                      line.startsWith("@@") ? "hunk" : line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : ""
                    }
                  >
                    {line + "\n"}
                  </span>
                ))}
              </pre>
            ) : (
              <p className="dim small patch-note">
                {f.patch_truncated ? "GitHub didn't include this diff (file too large or binary). " : "No text diff. "}
                {rawDiffUrl && (
                  <a className="link-purple" href={rawDiffUrl} target="_blank" rel="noreferrer">
                    [open full diff]
                  </a>
                )}
              </p>
            ))}
        </li>
      ))}
    </ul>
  );
}

/** Commit rows; the selected one can render its details underneath. */
export function CommitList({
  commits,
  selected,
  onSelect,
  renderDetail,
}: {
  commits: CommitSummary[];
  selected?: string | null;
  onSelect?: (sha: string) => void;
  renderDetail?: (sha: string) => React.ReactNode;
}) {
  if (commits.length === 0) return <p className="dim small">No commits.</p>;
  return (
    <ul className="commit-list">
      {commits.map((c) => (
        <li key={c.sha} className={selected === c.sha ? "selected" : ""}>
          <button className="commit-row" onClick={() => onSelect?.(c.sha)} disabled={!onSelect}>
            <span className="csha purple">{shortSha(c.sha)}</span>
            <span className="cmsg">{c.message}</span>
            <span className="cmeta dim">
              {c.author} · {timeAgo(c.date)}
            </span>
          </button>
          {selected === c.sha && renderDetail?.(c.sha)}
        </li>
      ))}
    </ul>
  );
}
