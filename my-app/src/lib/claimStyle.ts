import type { Verdict } from "@/gh/intentApi";

/** Verdicts are shown as glyphs so colour can mean one thing only: axiom (green) vs hypothesis (yellow). */
export const VERDICT_GLYPH: Record<Verdict | "empty", string> = {
  pass: "✓", fail: "✗", stale: "↻", inconclusive: "?", untested: "·", empty: "·",
};

export const VERDICT_TEXT: Record<Verdict | "empty", string> = {
  pass: "passing", fail: "failing", stale: "stale: wording changed since the last run", inconclusive: "inconclusive", untested: "never run", empty: "no claims",
};

export const fmtTime = (t: number | null | undefined) => (t ? new Date(t * 1000).toLocaleString() : "never");
