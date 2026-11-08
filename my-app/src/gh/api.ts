/** Small fetch helper: sends the session cookie and surfaces the API's error message. */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    ...init,
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
  });
  if (!res.ok) {
    let message = `${init.method ?? "GET"} ${path} → ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (body.detail && typeof body.detail.message === "string") message = body.detail.message;
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* keep default message */
    }
    throw new Error(message);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export interface ChangedFile {
  path: string;
  previous_path: string | null;
  status: string;
  additions: number;
  deletions: number;
  patch: string | null;
  patch_truncated?: boolean;
  /** Line ranges [start, end]: `added` in the new file, `removed` in the old file. */
  changed_lines?: { added: [number, number][]; removed: [number, number][] };
}

export interface CommitSummary {
  sha: string;
  message: string;
  author: string;
  avatar_url: string | null;
  date: string;
  html_url: string | null;
}

export interface CommitDetail extends CommitSummary {
  full_message: string;
  parents: string[];
  stats: { total?: number; additions?: number; deletions?: number };
  files: ChangedFile[];
}

export interface Comparison {
  base: string;
  head: string;
  status: string;
  ahead_by: number;
  behind_by: number;
  commits: CommitSummary[];
  truncated: boolean;
  files: ChangedFile[];
}

export interface Changes {
  base: string | null;
  head: string;
  /** Preview only: nothing has been synced yet. */
  initial_sync?: boolean;
  /** Sync result: this sync ingested the repo for the first time. */
  initial?: boolean;
  /** Present when this object is the result of a sync rather than a preview. */
  synced?: boolean;
  status?: string;
  /** For batches: "poll", "manual" or "webhook". */
  source?: string;
  created_at?: number;
  file_count?: number;
  files: ChangedFile[];
  commits: CommitSummary[];
  affected_tenets: string[];
  changed_leaves: string[];
  rerun_claims: string[];
}

export interface PollStatus {
  polling: boolean;
  interval_seconds: number;
  last_checked_at: number | null;
  last_seen_head: string | null;
  last_error: string | null;
  last_synced_sha: string | null;
}
