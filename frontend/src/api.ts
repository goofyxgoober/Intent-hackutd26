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
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* keep default message */
    }
    throw new Error(message);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export interface IntentNode {
  node_id: string;
  name: string;
  source_file: string;
  intent_summary: string;
  inputs: Record<string, string>;
  outputs: Record<string, string>;
  business_invariants: string[];
  downstream_dependencies: string[];
  version?: number;
  stale?: boolean;
  updated_at?: number;
}

export interface ChangedFile {
  path: string;
  previous_path: string | null;
  status: string;
  additions: number;
  deletions: number;
  patch: string | null;
  patch_truncated?: boolean;
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
  initial_sync: boolean;
  files: ChangedFile[];
  commits: CommitSummary[];
  affected_intents: string[];
  stale_marked?: number;
}
