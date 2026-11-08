"use client";

import { useState } from "react";
import type { Claim, Impact, Tenet, TreeView } from "./intentApi";
import { workspaceApi } from "./intentApi";
import { NodeCard } from "./Chrome";

type Api = ReturnType<typeof workspaceApi>;
type Say = (text: string, tone?: "green" | "red" | "dim") => void;

const VERDICT_TONE: Record<string, string> = {
  pass: "green", fail: "red", stale: "warn", inconclusive: "dim", untested: "dim", empty: "dim",
};

function orderTree(tree: TreeView): Tenet[] {
  const byId = Object.fromEntries(tree.tenets.map((t) => [t.id, t]));
  const out: Tenet[] = [];
  const walk = (id: string) => {
    const t = byId[id];
    if (!t) return;
    out.push(t);
    t.children.forEach(walk);
  };
  if (tree.root_id) walk(tree.root_id);
  return out;
}

export function IntentPanel({ tree, wsApi, say, onChanged }: { tree: TreeView | null; wsApi: Api; say: Say; onChanged: () => void }) {
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState<null | "root" | "child">(null);
  if (!tree) return <p className="hand dim lead">Loading intent tree…</p>;

  const ordered = orderTree(tree);
  const current = tree.tenets.find((t) => t.id === (selected ?? tree.root_id)) ?? null;
  const act = async (label: string, fn: () => Promise<unknown>) => {
    try {
      await fn();
      say(`✓ ${label}`, "green");
      onChanged();
      return true;
    } catch (e) {
      say(`✗ ${(e as Error).message}`, "red");
      return false;
    }
  };

  return (
    <div className="intent-panel">
      <div className="section-head">
        <h2 className="hand">intent tree</h2>
        {!tree.root_id ? (
          <button className="btn" onClick={() => setAdding("root")}>+ root tenet</button>
        ) : (
          current && <button className="btn" onClick={() => setAdding("child")}>+ child of {current.name}</button>
        )}
      </div>

      {adding && (
        <TenetForm
          onCancel={() => setAdding(null)}
          onSave={(name, functionality) =>
            act(`created tenet ${name}`, () =>
              wsApi.createTenet(name, functionality, adding === "root" ? null : current!.id),
            ).then((ok) => ok && setAdding(null))
          }
        />
      )}

      {ordered.length === 0 && !adding && (
        <p className="hand dim empty">No Tenets yet. The Intent Builder drafts the root from the code, or add one by hand.</p>
      )}

      <ul className="tenet-tree">
        {ordered.map((t) => (
          <li key={t.id}>
            <button
              className={`tenet-row ${current?.id === t.id ? "selected" : ""}`}
              style={{ paddingLeft: 8 + t.level * 18 }}
              onClick={() => setSelected(t.id)}
            >
              <span className="tname">{t.name}</span>
              {t.proposed && <span className="chip-mini warn">proposed</span>}
              {t.flagged_axioms > 0 && <span className="chip-mini red">⚑ {t.flagged_axioms}</span>}
              {t.references.length > 0 && <span className="chip-mini dim">↗ {t.references.length}</span>}
              <span className="counts dim">
                {t.axioms}A · {t.hypotheses}H
              </span>
              <span className={`verdict ${VERDICT_TONE[t.rollup]}`}>{t.rollup}</span>
            </button>
          </li>
        ))}
      </ul>

      {current && <TenetDetail tenet={current} tree={tree} wsApi={wsApi} act={act} />}
    </div>
  );
}

function TenetForm({ onSave, onCancel }: { onSave: (name: string, f: string) => void; onCancel: () => void }) {
  const [name, setName] = useState("");
  const [functionality, setFunctionality] = useState("");
  return (
    <div className="inline-form">
      <input id="tenet-name" placeholder="name, e.g. session validation" value={name} onChange={(e) => setName(e.target.value)} />
      <textarea id="tenet-functionality" placeholder="functionality: one precise paragraph" value={functionality} onChange={(e) => setFunctionality(e.target.value)} />
      <div className="row-actions">
        <button className="btn primary" disabled={!name.trim()} onClick={() => onSave(name.trim(), functionality.trim())}>save</button>
        <button className="btn" onClick={onCancel}>cancel</button>
      </div>
    </div>
  );
}

type Act = (label: string, fn: () => Promise<unknown>) => Promise<boolean>;

function TenetDetail({ tenet, tree, wsApi, act }: { tenet: Tenet; tree: TreeView; wsApi: Api; act: Act }) {
  const [adding, setAdding] = useState(false);
  const claims = tenet.claims.map((id) => tree.claims[id]).filter(Boolean);
  const axioms = claims.filter((c) => c.status === "axiom");
  const hypotheses = claims.filter((c) => c.status === "hypothesis");
  const names = Object.fromEntries(tree.tenets.map((t) => [t.id, t.name]));

  return (
    <NodeCard name={tenet.name} tag={`level ${tenet.level} · ${tenet.is_leaf ? "leaf" : "feature"}`} summary={tenet.functionality || "No functionality statement yet."}>
      <div className="mono-list">
        {tenet.code_links.length > 0 && <div>code: {tenet.code_links.map((l) => l.path).join(", ")}</div>}
        {tenet.references.length > 0 && <div>references: {tenet.references.map((r) => names[r] ?? r).join(", ")}</div>}
        {tenet.referenced_by.length > 0 && <div>referenced by: {tenet.referenced_by.map((r) => names[r] ?? r).join(", ")}</div>}
        <div className="dim small">id {tenet.id}</div>
      </div>

      <h3 className="claim-group">axioms · {axioms.length}</h3>
      {axioms.length === 0 && <p className="dim small">None locked yet. Promote a passing Hypothesis.</p>}
      {axioms.map((c) => <ClaimCard key={c.id} claim={c} wsApi={wsApi} act={act} />)}

      <h3 className="claim-group">hypotheses · {hypotheses.length}</h3>
      {hypotheses.map((c) => <ClaimCard key={c.id} claim={c} wsApi={wsApi} act={act} />)}

      {adding ? (
        <ClaimForm
          initial={{ statement: "", test_explanation: "", test_implementation: "" }}
          onCancel={() => setAdding(false)}
          onSave={(f) => act("added hypothesis", () => wsApi.createClaim(tenet.id, f)).then((ok) => ok && setAdding(false))}
        />
      ) : (
        <button className="link-purple as-button" onClick={() => setAdding(true)}>[+ hypothesis]</button>
      )}
    </NodeCard>
  );
}

type ClaimText = Pick<Claim, "statement" | "test_explanation" | "test_implementation">;

function ClaimForm({ initial, onSave, onCancel, reasonLabel }: {
  initial: ClaimText;
  onSave: (f: ClaimText, reason: string) => void;
  onCancel: () => void;
  reasonLabel?: string;
}) {
  const [f, setF] = useState(initial);
  const [reason, setReason] = useState("");
  return (
    <div className="inline-form">
      <label className="dim small">statement</label>
      <textarea id="claim-statement" value={f.statement} onChange={(e) => setF({ ...f, statement: e.target.value })} />
      <label className="dim small">test explanation</label>
      <textarea id="claim-explanation" value={f.test_explanation} onChange={(e) => setF({ ...f, test_explanation: e.target.value })} />
      <label className="dim small">test implementation details</label>
      <textarea id="claim-implementation" className="tall" value={f.test_implementation} onChange={(e) => setF({ ...f, test_implementation: e.target.value })} />
      {reasonLabel && (
        <>
          <label className="dim small">{reasonLabel}</label>
          <input id="claim-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
        </>
      )}
      <div className="row-actions">
        <button className="btn primary" disabled={!f.statement.trim() || (!!reasonLabel && !reason.trim())} onClick={() => onSave(f, reason)}>save</button>
        <button className="btn" onClick={onCancel}>cancel</button>
      </div>
    </div>
  );
}

function ImpactSummary({ impact }: { impact: Impact }) {
  return (
    <div className="impact">
      <div>dependent claims: <b>{impact.dependent_claims.length}</b></div>
      <div>integration claims above: <b>{impact.integration_claims_above.length}</b></div>
      <div>referencing tenets: <b>{impact.referencing_tenets.length}</b></div>
      <div>linked code: <b>{impact.linked_code.map((l) => l.path).join(", ") || "none"}</b></div>
      <div>results going stale: <b>{impact.results_going_stale.length}</b></div>
      <div>spec sections made provisional: <b>{impact.spec_sections_provisional.length}</b></div>
    </div>
  );
}

function ClaimCard({ claim, wsApi, act }: { claim: Claim; wsApi: Api; act: Act }) {
  const [mode, setMode] = useState<null | "edit" | "demote" | "axiom-edit" | "scrap">(null);
  const [impact, setImpact] = useState<Impact | null>(null);
  const [reason, setReason] = useState("");
  const [needsOverride, setNeedsOverride] = useState(false);
  const isAxiom = claim.status === "axiom";
  const text = { statement: claim.statement, test_explanation: claim.test_explanation, test_implementation: claim.test_implementation };

  const withImpact = async (m: "demote" | "axiom-edit") => {
    setImpact(await wsApi.impact(claim.id));
    setMode(m);
  };
  const promote = async (override = false) => {
    const ok = await act(override ? "promoted (accepted without verification)" : "promoted to Axiom", () =>
      wsApi.promote(claim.id, override),
    );
    setNeedsOverride(!ok && !override);
  };

  return (
    <div className={`claim ${claim.status} ${claim.flags.length ? "flagged" : ""}`}>
      <div className="claim-head">
        <span className={`chip-mini ${isAxiom ? "purple" : "dim"}`}>{claim.status}</span>
        {claim.verification === "accepted_without_verification" && <span className="chip-mini warn">unverified (accepted)</span>}
        {claim.verification === "unverified_edit" && <span className="chip-mini warn">unverified (edited)</span>}
        {claim.proposed && <span className="chip-mini warn">proposed</span>}
        <span className={`verdict ${VERDICT_TONE[claim.result.verdict]}`}>
          {claim.result.verdict}{claim.result.flaky ? " · flaky" : ""}
        </span>
      </div>
      <p className="claim-statement">{claim.statement}</p>
      {claim.test_explanation && <p className="dim small">{claim.test_explanation}</p>}
      {claim.flags.map((f) => (
        <p key={f.kind + f.at} className="flag small">
          ⚑ {f.kind.replace(/_/g, " ")}: {f.detail}{" "}
          <button className="as-button link-purple" onClick={() => act("flag dismissed", () => wsApi.clearFlag(claim.id, f.kind))}>[dismiss]</button>
        </p>
      ))}

      {mode === null && (
        <div className="card-actions">
          {isAxiom ? (
            <>
              <button className="link-purple as-button" onClick={() => withImpact("demote")}>[demote]</button>
              <button className="link-purple as-button" onClick={() => withImpact("axiom-edit")}>[edit by hand]</button>
            </>
          ) : (
            <>
              <button className="link-purple as-button" onClick={() => promote()}>[promote]</button>
              {needsOverride && (
                <button className="link-purple as-button warn" onClick={() => promote(true)}>[accept without verification]</button>
              )}
              <button className="link-purple as-button" onClick={() => setMode("edit")}>[edit]</button>
              <button className="link-purple as-button" onClick={() => setMode("scrap")}>[scrap]</button>
            </>
          )}
        </div>
      )}

      {mode === "edit" && (
        <ClaimForm initial={text} onCancel={() => setMode(null)}
          onSave={(f) => act("hypothesis saved", () => wsApi.editHypothesis(claim.id, f)).then((ok) => ok && setMode(null))} />
      )}

      {mode === "scrap" && (
        <div className="inline-form">
          <label className="dim small">why is this interpretation wrong? (kept so it isn't regenerated)</label>
          <input id="scrap-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
          <div className="row-actions">
            <button className="btn danger" disabled={!reason.trim()} onClick={() => act("scrapped", () => wsApi.scrap(claim.id, reason)).then((ok) => ok && setMode(null))}>scrap</button>
            <button className="btn" onClick={() => setMode(null)}>cancel</button>
          </div>
        </div>
      )}

      {mode === "demote" && impact && (
        <div className="inline-form warn-box">
          <p className="small">Demoting unlocks this Claim so agents can edit it. This is what it affects:</p>
          <ImpactSummary impact={impact} />
          <label className="dim small">reason (recorded in history)</label>
          <input id="demote-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
          <div className="row-actions">
            <button className="btn danger" disabled={!reason.trim()} onClick={() => act("demoted to Hypothesis", () => wsApi.demote(claim.id, reason)).then((ok) => ok && setMode(null))}>demote</button>
            <button className="btn" onClick={() => setMode(null)}>cancel</button>
          </div>
        </div>
      )}

      {mode === "axiom-edit" && impact && (
        <div className="warn-box">
          <p className="small">
            ⚠ Changing an Axiom carelessly can break the base that other Claims, the spec and generated code rest on.
            It stays an Axiom but is marked unverified until its test passes again.
          </p>
          <ImpactSummary impact={impact} />
          <ClaimForm initial={text} reasonLabel="reason for this edit" onCancel={() => setMode(null)}
            onSave={(f, why) => act("axiom edited by hand", () => wsApi.editAxiom(claim.id, f, why)).then((ok) => ok && setMode(null))} />
        </div>
      )}
    </div>
  );
}
