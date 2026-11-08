"use client";

import { useEffect, useMemo, useState } from "react";
import type { Claim, Impact, RejectedReading, ResultsFile, TreeView, workspaceApi } from "@/gh/intentApi";
import { VERDICT_GLYPH, VERDICT_TEXT, fmtTime } from "@/lib/claimStyle";
import { missingParts, parseRecipe } from "@/lib/recipe";

type Api = ReturnType<typeof workspaceApi>;
type Panel = null | "promote" | "demote" | "edit" | "scrap";

interface Props {
  tree: TreeView;
  claimId: string;
  /** null while offline: the claim is readable but nothing can change. */
  wsApi: Api | null;
  onBack(): void;
  onClose(): void;
  onOpenClaim(id: string): void;
  onOpenTenet(id: string): void;
  onChanged(): void;
  say(text: string, tone?: "success" | "error" | "muted"): void;
}


/**
 * One claim, opened up: statement, what the test checks, the full implementation recipe, run history,
 * the bottom-up promotion gate, dependencies in both directions, and every action the user is allowed.
 * Status changes are two-phase: the impact is shown first, then the user confirms.
 * Mount with key={claimId} so panel state resets between claims.
 */
export function ClaimDetail({ tree, claimId, wsApi, onBack, onClose, onOpenClaim, onOpenTenet, onChanged, say }: Props) {
  const claim = tree.claims[claimId];
  const [panel, setPanel] = useState<Panel>(null);
  const [impact, setImpact] = useState<Impact | null>(null);
  const [results, setResults] = useState<ResultsFile | null>(null);
  const [rejected, setRejected] = useState<RejectedReading[]>([]);
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [understood, setUnderstood] = useState(false);
  const [form, setForm] = useState(() => ({
    statement: claim?.statement ?? "",
    test_explanation: claim?.test_explanation ?? "",
    test_implementation: claim?.test_implementation ?? "",
  }));
  const [rejectedText, setRejectedText] = useState(claim?.statement ?? "");

  const hash = claim?.content_hash;
  const runs = claim?.result.runs;
  useEffect(() => {
    if (!wsApi) return;
    let off = false;
    wsApi.results(claimId).then((r) => !off && setResults(r)).catch(() => undefined);
    return () => {
      off = true;
    };
  }, [wsApi, claimId, hash, runs]);

  const tenetId = claim?.tenet_id;
  useEffect(() => {
    if (!wsApi || !tenetId) return;
    let off = false;
    wsApi.rejected(tenetId).then((r) => !off && setRejected(r)).catch(() => undefined);
    return () => {
      off = true;
    };
  }, [wsApi, tenetId, claim?.status]);

  const recipe = useMemo(() => parseRecipe(claim?.test_implementation ?? ""), [claim?.test_implementation]);
  if (!claim) return null;

  const tenet = tree.tenets.find((t) => t.id === claim.tenet_id);
  const isAxiom = claim.status === "axiom";
  const scrapped = claim.status === "scrapped";
  const verdict = claim.result.verdict;
  const verified = verdict === "pass" && !claim.result.flaky;
  const deps = claim.dependencies.map((id) => tree.claims[id]).filter(Boolean) as Claim[];
  const blockers = deps.filter((d) => d.status !== "axiom" && d.result.verdict !== "pass");
  const dependents = Object.values(tree.claims).filter((c) => c.dependencies.includes(claim.id) && c.status !== "scrapped");
  const missing = missingParts(recipe);
  const conf = Math.round(Math.max(0, Math.min(1, claim.confidence)) * 100);
  const sibling = (id: string) => tree.tenets.find((t) => t.id === id)?.name ?? id;

  async function open(p: Exclude<Panel, null>) {
    setPanel(p);
    setReason("");
    setUnderstood(false);
    if (wsApi && (p !== "edit" || isAxiom)) {
      try {
        setImpact(await wsApi.impact(claim.id));
      } catch (e) {
        say(`  ✗ ${(e as Error).message}`, "error");
      }
    }
  }

  async function act(label: string, fn: () => Promise<unknown>) {
    setBusy(true);
    try {
      await fn();
      say(`  ✓ ${label}`, "success");
      setPanel(null);
      onChanged();
    } catch (e) {
      say(`  ✗ ${(e as Error).message}`, "error");
    } finally {
      setBusy(false);
    }
  }

  const impactBlock = (i: Impact | null) =>
    i ? (
      <div className="impact-box">
        <span className="impact-title">what this touches</span>
        <ul>
          <li>
            <b>{i.dependent_claims.length}</b> dependent claim{i.dependent_claims.length === 1 ? "" : "s"}
            {i.dependent_claims.slice(0, 3).map((d) => (
              <button key={d.id} className="inline-link" onClick={() => onOpenClaim(d.id)} title={d.statement}>{d.id}</button>
            ))}
          </li>
          <li><b>{i.integration_claims_above.length}</b> integration claims above</li>
          <li><b>{i.referencing_tenets.length}</b> referencing tenets{i.referencing_tenets.length ? `: ${i.referencing_tenets.map(sibling).join(", ")}` : ""}</li>
          <li><b>{i.linked_code.length}</b> linked code location{i.linked_code.length === 1 ? "" : "s"}{i.linked_code.length ? `: ${i.linked_code.map((l) => l.path).join(", ")}` : ""}</li>
          <li><b>{i.results_going_stale.length}</b> result{i.results_going_stale.length === 1 ? "" : "s"} going stale</li>
          <li><b>{i.spec_sections_provisional.length}</b> spec section{i.spec_sections_provisional.length === 1 ? "" : "s"} made provisional</li>
        </ul>
      </div>
    ) : null;

  const textFields = (
    <>
      <label>statement</label>
      <textarea value={form.statement} onChange={(e) => setForm({ ...form, statement: e.target.value })} />
      <label>what the test checks</label>
      <textarea value={form.test_explanation} onChange={(e) => setForm({ ...form, test_explanation: e.target.value })} />
      <label>implementation recipe</label>
      <textarea className="tall" value={form.test_implementation} onChange={(e) => setForm({ ...form, test_implementation: e.target.value })} />
    </>
  );

  return (
    <aside className={`inspector claim-detail ${isAxiom ? "is-axiom" : "is-hyp"}`} aria-label="Claim detail">
      <button className="close-inspector" onClick={onClose} aria-label="Close">×</button>
      <button className="back-link" onClick={onBack}>← {tenet?.name ?? "tenet"}</button>

      <span className={`status-pill ${isAxiom ? "axiom" : "hyp"}`}>{isAxiom ? "◆ axiom · locked" : scrapped ? "scrapped" : "◇ hypothesis · editable"}</span>
      <h2 className="claim-title">{claim.statement}</h2>
      <code>{claim.id} · v{claim.version}</code>

      <div className="badge-row">
        <span className={`vbadge v-${verdict}`} title={VERDICT_TEXT[verdict]}>{VERDICT_GLYPH[verdict]} {verdict}</span>
        {claim.result.flaky ? <span className="vbadge warn">flaky</span> : null}
        {claim.verification === "accepted_without_verification" ? <span className="vbadge warn">accepted unverified</span> : null}
        {claim.verification === "unverified_edit" ? <span className="vbadge warn">edited · unverified</span> : null}
        {claim.proposed ? <span className="vbadge warn">proposed</span> : null}
        {claim.flags.length ? <span className="vbadge bad">⚑ {claim.flags.length}</span> : null}
      </div>
      <div className="conf" title={`confidence ${conf}%`}>
        <span>confidence</span>
        <i><b style={{ width: `${conf}%` }} /></i>
        <span>{conf}%</span>
      </div>

      {claim.flags.map((f) => (
        <div key={f.kind + f.at} className="flag-box">
          <b>⚑ {f.kind.replace(/_/g, " ")}</b>
          <span>{f.detail}</span>
          <em>Nothing has changed automatically. You decide: investigate, then demote or dismiss.</em>
          {wsApi ? <button className="inline-link" onClick={() => void act("flag dismissed", () => wsApi.clearFlag(claim.id, f.kind))}>dismiss</button> : null}
        </div>
      ))}

      {/* ------------------------------------------------------------ actions */}
      {scrapped ? <p className="muted">scrapped: kept only as a rejected interpretation so it isn&apos;t regenerated.</p> : wsApi ? (
        panel === null ? (
          <div className="action-row">
            {isAxiom ? (
              <>
                <button className="act warn" onClick={() => void open("demote")}>demote…</button>
                <button className="act" onClick={() => void open("edit")}>edit by hand…</button>
              </>
            ) : (
              <>
                <button className="act go" onClick={() => void open("promote")}>promote…</button>
                <button className="act" onClick={() => void open("edit")}>edit</button>
                <button className="act warn" onClick={() => void open("scrap")}>scrap…</button>
              </>
            )}
          </div>
        ) : null
      ) : (
        <p className="muted">offline fixture: connect the backend to promote, demote, edit or scrap.</p>
      )}

      {panel === "promote" ? (
        <div className="confirm-card go">
          <h4>Lock this as an axiom?</h4>
          <p>
            Only you can do this; agents can never lock or unlock a claim. Bottom-up rule: it needs a passing, non-flaky test
            for the <i>current wording</i> and every dependency locked or passing.
          </p>
          <ul className="gate">
            <li className={verified ? "ok" : "no"}>{verified ? "✓" : "✗"} {verified ? "test passes for this exact wording" : `no passing test yet (${verdict})`}</li>
            <li className={blockers.length ? "no" : "ok"}>
              {blockers.length ? "✗" : "✓"} {deps.length ? `${deps.length - blockers.length}/${deps.length} dependencies ready` : "no dependencies"}
            </li>
          </ul>
          {blockers.length ? (
            <p className="blockers">
              blocked by:{" "}
              {blockers.map((b) => <button key={b.id} className="inline-link" onClick={() => onOpenClaim(b.id)}>{b.id}</button>)}
              <br />
              <em>Dependency blockers can&apos;t be overridden. Lock or fix those first.</em>
            </p>
          ) : null}
          {impactBlock(impact)}
          <div className="row">
            <button className="act go" disabled={busy || !verified || blockers.length > 0} onClick={() => void act(`promoted ${claim.id} to axiom`, () => wsApi!.promote(claim.id, false))}>promote</button>
            {!verified ? (
              <button className="act warn" disabled={busy || blockers.length > 0} onClick={() => void act(`promoted ${claim.id} (accepted without verification)`, () => wsApi!.promote(claim.id, true))}>accept without verification</button>
            ) : null}
            <button className="act" onClick={() => setPanel(null)}>cancel</button>
          </div>
        </div>
      ) : null}

      {panel === "demote" ? (
        <div className="confirm-card warn">
          <h4>Demote to hypothesis?</h4>
          <p>It unlocks the claim so agents may edit it. Dependents stay axioms but are flagged as sitting on an unlocked base, and their results go stale.</p>
          {impactBlock(impact)}
          <label>reason (recorded in history)</label>
          <input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="required" />
          <div className="row">
            <button className="act warn" disabled={busy || !reason.trim()} onClick={() => void act(`demoted ${claim.id}`, () => wsApi!.demote(claim.id, reason))}>demote</button>
            <button className="act" onClick={() => setPanel(null)}>cancel</button>
          </div>
        </div>
      ) : null}

      {panel === "scrap" ? (
        <div className="confirm-card warn">
          <h4>Scrap this hypothesis?</h4>
          <p>The wording is kept as a rejected interpretation, so the Remake Agent can&apos;t propose it again.</p>
          <label>why is this reading wrong?</label>
          <input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="required" />
          <label>rejected interpretation</label>
          <textarea value={rejectedText} onChange={(e) => setRejectedText(e.target.value)} />
          <div className="row">
            <button className="act warn" disabled={busy || !reason.trim()} onClick={() => void act(`scrapped ${claim.id}`, () => wsApi!.scrapWith(claim.id, reason, rejectedText.trim() || undefined))}>scrap</button>
            <button className="act" onClick={() => setPanel(null)}>cancel</button>
          </div>
        </div>
      ) : null}

      {panel === "edit" ? (
        <div className={`confirm-card ${isAxiom ? "warn" : ""}`}>
          {isAxiom ? (
            <>
              <h4>Edit an axiom by hand</h4>
              <p>
                ⚠ Changing an axiom carelessly can break the base other claims, the spec and generated code rest on. It stays an
                axiom but is marked unverified until its test passes again. You type the wording; no model drafts it.
              </p>
              {impactBlock(impact)}
            </>
          ) : (
            <h4>Edit hypothesis</h4>
          )}
          {textFields}
          {isAxiom ? (
            <>
              <label>reason for this edit</label>
              <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="required" />
              <label className="check"><input type="checkbox" checked={understood} onChange={(e) => setUnderstood(e.target.checked)} /> I understand what this affects</label>
            </>
          ) : null}
          <div className="row">
            <button
              className="act go"
              disabled={busy || !form.statement.trim() || (isAxiom && (!understood || !reason.trim()))}
              onClick={() =>
                void act(isAxiom ? "axiom edited by hand (now unverified)" : "hypothesis saved", () =>
                  isAxiom ? wsApi!.editAxiom(claim.id, form, reason) : wsApi!.editHypothesis(claim.id, form),
                )
              }
            >
              save
            </button>
            <button className="act" onClick={() => setPanel(null)}>cancel</button>
          </div>
        </div>
      ) : null}

      {/* ------------------------------------------------------------ the information */}
      <h3>What the test checks</h3>
      <p className="prose">{claim.test_explanation || <span className="muted">not written yet</span>}</p>

      <h3>Implementation recipe</h3>
      {recipe.length ? (
        <>
          <div className="recipe">
            {recipe.map((p) => (
              <div key={p.label} className={`recipe-part ${p.tone}`}>
                <span>{p.label.toLowerCase()}</span>
                <pre>{p.body}</pre>
              </div>
            ))}
          </div>
          {missing.length ? <p className="muted">⚠ recipe is missing: {missing.join(", ").toLowerCase()}. The runner would report inconclusive.</p> : null}
        </>
      ) : (
        <p className="muted">no recipe yet: the Test Author writes one after the statement is settled.</p>
      )}

      <h3>Verification</h3>
      <dl>
        <div><dt>latest</dt><dd>{VERDICT_GLYPH[verdict]} {VERDICT_TEXT[verdict]}</dd></div>
        <div><dt>runs</dt><dd>{claim.result.runs} · last {fmtTime(claim.result.last_run_at)}</dd></div>
        <div><dt>binding</dt><dd>results are tied to this exact wording; any edit makes them stale</dd></div>
      </dl>
      {results?.runs.length ? (
        <ol className="runs">
          {[...results.runs].reverse().map((r, i) => (
            <li key={r.at + ":" + i} className={`run ${r.verdict}`}>
              <b>{VERDICT_GLYPH[r.verdict]} {r.verdict}</b>
              <span>{fmtTime(r.at)}{r.runner ? ` · ${r.runner}` : ""}{r.claim_hash !== claim.content_hash ? " · older wording" : ""}</span>
              {r.underspecified ? <em>recipe underspecified: {r.underspecified}</em> : null}
              {r.invoked || r.expected || r.actual || r.notes ? (
                <details>
                  <summary>details</summary>
                  {r.invoked ? <p><i>invoked</i> {r.invoked}</p> : null}
                  {r.expected ? <p><i>expected</i> {r.expected}</p> : null}
                  {r.actual ? <p><i>actual</i> {r.actual}</p> : null}
                  {r.notes ? <p><i>notes</i> {r.notes}</p> : null}
                </details>
              ) : null}
            </li>
          ))}
        </ol>
      ) : (
        <p className="muted">no runs recorded{wsApi ? "" : " (offline)"}.</p>
      )}
      {results?.invalidations.length ? <p className="muted">{results.invalidations.length} invalidation(s): {results.invalidations[results.invalidations.length - 1].reason}</p> : null}

      <h3>Depends on · {deps.length}</h3>
      {deps.length ? (
        <ul className="dep-claims">
          {deps.map((d) => (
            <li key={d.id}>
              <button className={`dep ${d.status === "axiom" ? "axiom" : "hyp"} ${d.status === "axiom" || d.result.verdict === "pass" ? "ready" : "blocked"}`} onClick={() => onOpenClaim(d.id)}>
                <i>{d.status === "axiom" ? "◆" : "◇"}</i>
                <span>{d.statement}</span>
                <small>{sibling(d.tenet_id)} · {d.status === "axiom" || d.result.verdict === "pass" ? "ready" : "blocking"}</small>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">none: this claim stands on its own.</p>
      )}
      {dependents.length ? (
        <>
          <h3>Depended on by · {dependents.length}</h3>
          <ul className="dep-claims">
            {dependents.map((d) => (
              <li key={d.id}>
                <button className={`dep ${d.status === "axiom" ? "axiom" : "hyp"}`} onClick={() => onOpenClaim(d.id)}>
                  <i>{d.status === "axiom" ? "◆" : "◇"}</i>
                  <span>{d.statement}</span>
                  <small>{sibling(d.tenet_id)}</small>
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      <h3>Provenance</h3>
      <dl>
        <div><dt>source</dt><dd>{[claim.provenance.kind, claim.provenance.role, claim.provenance.actor].filter(Boolean).join(" · ") || "unknown"}{claim.provenance.via ? ` · via ${claim.provenance.via}` : ""}</dd></div>
        {claim.remade_from ? <div><dt>remade from</dt><dd>{claim.remade_from}</dd></div> : null}
        <div><dt>tenet</dt><dd><button className="inline-link" onClick={() => onOpenTenet(claim.tenet_id)}>{tenet?.name ?? claim.tenet_id}</button></dd></div>
      </dl>

      {!isAxiom && rejected.length ? (
        <>
          <h3>Rejected readings · {rejected.length}</h3>
          <ul className="rejected">
            {rejected.map((r, i) => (
              <li key={i}>{r.interpretation}{r.reason ? <em> ({r.reason})</em> : null}</li>
            ))}
          </ul>
        </>
      ) : null}
    </aside>
  );
}

