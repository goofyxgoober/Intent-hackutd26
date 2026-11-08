/** Typed client for /api/workspaces/{id} (intent engine). */
import { api } from "./api";

export type Verdict = "pass" | "fail" | "inconclusive" | "stale" | "untested";
export type Status = "axiom" | "hypothesis" | "scrapped";

export interface Flag {
  kind: string;
  detail: string;
  at: number;
}

export interface Claim {
  id: string;
  tenet_id: string;
  status: Status;
  verification: "verified" | "accepted_without_verification" | "unverified_edit" | null;
  confidence: number;
  proposed: boolean;
  flags: Flag[];
  version: number;
  statement: string;
  test_explanation: string;
  test_implementation: string;
  dependencies: string[];
  content_hash: string;
  remade_from?: string | null;
  provenance: { kind?: string; role?: string; actor?: string; via?: string; run_id?: string; commit_range?: string };
  result: { verdict: Verdict; flaky: boolean; runs: number; last_run_at: number | null };
}

export interface Tenet {
  id: string;
  name: string;
  parent_id: string | null;
  functionality: string;
  children: string[];
  references: string[];
  cross_cutting: string[];
  code_links: { path: string; start_line?: number; end_line?: number; symbol?: string }[];
  /** Questions the Intent Builder could not resolve; shown so nobody mistakes a guess for a fact. */
  open_unknowns?: string[];
  claims: string[];
  proposed: boolean;
  level: number;
  is_leaf: boolean;
  referenced_by: string[];
  axioms: number;
  hypotheses: number;
  flagged_axioms: number;
  rollup: Verdict | "empty";
}

export interface TreeView {
  root_id: string | null;
  tenets: Tenet[];
  claims: Record<string, Claim>;
}

export interface RunRecord {
  claim_hash: string;
  verdict: "pass" | "fail" | "inconclusive";
  invoked?: string;
  expected?: string;
  actual?: string;
  notes?: string;
  code_ref?: string | null;
  underspecified?: string | null;
  at: number;
  runner?: string;
}

export interface ResultsFile {
  runs: RunRecord[];
  invalidations: { at: number; reason: string }[];
  summary: Claim["result"];
}

export interface RejectedReading {
  tenet_id: string;
  interpretation: string;
  reason?: string;
  recorded_at?: number;
}

export interface Impact {
  claim_id: string;
  dependent_claims: { id: string; tenet_id: string; status: Status; statement: string }[];
  integration_claims_above: { id: string; tenet_id: string; status: Status }[];
  referencing_tenets: string[];
  affected_tenets: string[];
  linked_code: { path: string }[];
  results_going_stale: string[];
  spec_sections_provisional: string[];
}

export function workspaceApi(id: number) {
  const base = `/api/workspaces/${id}`;
  const post = <T,>(path: string, body: unknown) => api<T>(base + path, { method: "POST", body: JSON.stringify(body) });
  return {
    tree: () => api<TreeView>(`${base}/tree`),
    createTenet: (name: string, functionality: string, parent_id: string | null) =>
      post<Tenet>("/tenets", { name, functionality, parent_id, provenance: { via: "manual" } }),
    updateTenet: (id: string, fields: Partial<Pick<Tenet, "name" | "functionality">>) =>
      api<Tenet>(`${base}/tenets/${id}`, { method: "PATCH", body: JSON.stringify(fields) }),
    createClaim: (tenet: string, fields: Pick<Claim, "statement" | "test_explanation" | "test_implementation">) =>
      post<Claim>(`/tenets/${tenet}/claims`, { ...fields, provenance: { via: "manual" } }),
    editHypothesis: (id: string, fields: Partial<Claim>) =>
      api<Claim>(`${base}/claims/${id}`, { method: "PATCH", body: JSON.stringify(fields) }),
    editAxiom: (id: string, fields: Partial<Claim>, reason: string) =>
      api<Claim>(`${base}/claims/${id}/axiom`, {
        method: "PUT",
        body: JSON.stringify({ ...fields, reason, acknowledge_warning: true }),
      }),
    results: (id: string) => api<ResultsFile>(`${base}/claims/${id}/results`),
    rejected: (tenetId: string) => api<RejectedReading[]>(`${base}/tenets/${tenetId}/rejected`),
    scrapWith: (id: string, reason: string, rejected_interpretation?: string) =>
      post<Claim>(`/claims/${id}/scrap`, { reason, rejected_interpretation }),
    impact: (id: string) => api<Impact>(`${base}/claims/${id}/impact`),
    promote: (id: string, acceptWithoutVerification = false) =>
      post<Claim>(`/claims/${id}/promote`, { accept_without_verification: acceptWithoutVerification }),
    demote: (id: string, reason: string) => post<Claim>(`/claims/${id}/demote`, { reason }),
    scrap: (id: string, reason: string) => post<Claim>(`/claims/${id}/scrap`, { reason }),
    clearFlag: (id: string, kind: string) => api<Claim>(`${base}/claims/${id}/flags/${kind}`, { method: "DELETE" }),
    exportFolder: () => post<{ branch: string; commit_sha: string; files: number; changed: boolean }>("/export", {}),
  };
}
