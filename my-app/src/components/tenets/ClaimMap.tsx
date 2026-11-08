"use client";

import type { Claim, Tenet } from "@/gh/intentApi";
import { VERDICT_GLYPH } from "@/lib/claimStyle";

interface Props {
  groups: { tenet: Tenet; claims: Claim[] }[];
  activeClaim: string | null;
  onOpenClaim(id: string): void;
  onOpenTenet(id: string): void;
}

/**
 * Visual map of the claims behind a tenet. Green = axiom (locked), yellow = hypothesis (editable).
 * Axioms form the foundation row, hypotheses sit above it. Block height is confidence; the glyph is the
 * latest verdict. Every block opens its claim.
 */
export function ClaimMap({ groups, activeClaim, onOpenClaim, onOpenTenet }: Props) {
  const all = groups.flatMap((g) => g.claims);
  if (!all.length) return <p className="muted">no claims to map yet</p>;
  const axioms = all.filter((c) => c.status === "axiom").length;
  const hyps = all.length - axioms;
  const flagged = all.filter((c) => c.flags.length).length;

  const block = (c: Claim) => {
    const h = 20 + Math.round(Math.max(0, Math.min(1, c.confidence)) * 22);
    const deps = c.dependencies.length;
    return (
      <button
        key={c.id}
        className={`cm-block ${c.status === "axiom" ? "axiom" : "hyp"} ${c.flags.length ? "flagged" : ""} ${activeClaim === c.id ? "active" : ""}`}
        style={{ height: h }}
        onClick={() => onOpenClaim(c.id)}
        title={`${c.status} · ${c.result.verdict}${c.result.flaky ? " (flaky)" : ""} · confidence ${Math.round(c.confidence * 100)}%${deps ? ` · depends on ${deps}` : ""}\n${c.statement}`}
        aria-label={`${c.status}: ${c.statement}`}
      >
        <i className={`g v-${c.result.verdict}`}>{VERDICT_GLYPH[c.result.verdict]}</i>
        {c.flags.length ? <b>⚑</b> : null}
        {deps ? <span className="cm-deps">{"·".repeat(Math.min(deps, 4))}</span> : null}
      </button>
    );
  };

  return (
    <div className="claim-map">
      <div className="cm-summary">
        <span className="ax"><b>{axioms}</b> axioms</span>
        <span className="hy"><b>{hyps}</b> hypotheses</span>
        {flagged ? <span className="bad"><b>{flagged}</b> flagged</span> : null}
      </div>
      <div className="cm-bar" role="img" aria-label={`${axioms} axioms, ${hyps} hypotheses`}>
        {axioms ? <i className="ax" style={{ flexGrow: axioms }} /> : null}
        {hyps ? <i className="hy" style={{ flexGrow: hyps }} /> : null}
      </div>

      {groups.map(({ tenet, claims }) => {
        const hyp = claims.filter((c) => c.status === "hypothesis");
        const ax = claims.filter((c) => c.status === "axiom");
        return (
          <div key={tenet.id} className="cm-group">
            {groups.length > 1 ? (
              <button className="cm-title" onClick={() => onOpenTenet(tenet.id)} title="open this tenet">{tenet.name}</button>
            ) : null}
            <div className="cm-row hyp">{hyp.length ? hyp.map(block) : <em>no hypotheses</em>}</div>
            <div className="cm-row ax">{ax.length ? ax.map(block) : <em>no axioms locked</em>}</div>
          </div>
        );
      })}

      <div className="cm-legend">
        <span><i className="sw ax" /> axiom · locked</span>
        <span><i className="sw hyp" /> hypothesis · proposed</span>
        <span>✓ pass · ✗ fail · ↻ stale · ? inconclusive · · untested</span>
        <span className="note">height = confidence · dots = dependencies</span>
      </div>
    </div>
  );
}
