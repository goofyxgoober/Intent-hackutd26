"use client";

import { useMemo, useState } from "react";
import type { Claim, Tenet, TreeView, workspaceApi } from "@/gh/intentApi";
import { VERDICT_GLYPH } from "@/lib/claimStyle";
import { claimGroups, pathsUnder } from "@/lib/tenetLinks";
import { ClaimMap } from "./ClaimMap";

type Api = ReturnType<typeof workspaceApi>;

interface Props {
  tree: TreeView;
  tenetId: string;
  /** null while offline: everything is read-only. */
  wsApi: Api | null;
  /** graph node ids whose source_file matches one of this tenet's code links */
  graphNodes: { id: string; name: string }[];
  activeClaim: string | null;
  onSelect(id: string | null): void;
  onOpenClaim(id: string): void;
  onShowInGraph(tenetId: string): void;
  onChanged(): void;
  say(text: string, tone?: "success" | "error" | "muted"): void;
}

const firstSentence = (s: string) => (s.match(/^.*?[.!?](\s|$)/)?.[0] ?? s).trim();

export function TenetInspector({ tree, tenetId, wsApi, graphNodes, activeClaim, onSelect, onOpenClaim, onShowInGraph, onChanged, say }: Props) {
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const t = tree.tenets.find((x) => x.id === tenetId);
  const byId = useMemo(() => new Map(tree.tenets.map((x) => [x.id, x])), [tree.tenets]);
  if (!t) return null;

  const ref = (id: string) => byId.get(id)?.name ?? id;
  const claims = t.claims.map((id) => tree.claims[id]).filter((c): c is Claim => !!c && c.status !== "scrapped");
  const ordered = [...claims.filter((c) => c.status === "axiom"), ...claims.filter((c) => c.status === "hypothesis")];
  const groups = claimGroups(tree, t.id);
  const all = groups.flatMap((g) => g.claims);

  // ---- derived detail
  const path: Tenet[] = [];
  for (let x: Tenet | undefined = t; x && !path.includes(x); x = x.parent_id ? byId.get(x.parent_id) : undefined) path.unshift(x);
  const files = pathsUnder(tree, t.id);
  const runs = all.reduce((n, c) => n + c.result.runs, 0);
  const avgConf = all.length ? Math.round((all.reduce((n, c) => n + c.confidence, 0) / all.length) * 100) : null;
  const locked = all.filter((c) => c.status === "axiom").length;
  const unverified = all.filter((c) => c.verification === "accepted_without_verification" || c.verification === "unverified_edit").length;
  const flagged = all.filter((c) => c.flags.length).length;
  const noRecipe = all.filter((c) => c.status === "hypothesis" && !c.test_implementation.trim()).length;
  const untested = all.filter((c) => c.result.verdict === "untested").length;
  const failing = all.filter((c) => c.result.verdict === "fail").length;
  const pct = all.length ? Math.round((locked / all.length) * 100) : 0;
  const readiness: [boolean, string][] = [
    [!!t.functionality.trim(), "functionality stated"],
    [all.length > 0, "claims written"],
    [all.length > 0 && noRecipe === 0, "every hypothesis has a test recipe"],
    [all.length > 0 && untested === 0, "every claim has been run"],
    [failing === 0 && flagged === 0, "nothing failing or flagged"],
    [all.length > 0 && locked === all.length, "all claims locked as axioms"],
  ];

  async function addHypothesis() {
    if (!wsApi || !draft.trim()) return;
    setBusy(true);
    try {
      const c = await wsApi.createClaim(t!.id, { statement: draft.trim(), test_explanation: "", test_implementation: "" });
      say(`  ✓ added hypothesis ${c.id}: the Test Author writes its recipe next`, "success");
      setDraft("");
      setAdding(false);
      onChanged();
      onOpenClaim(c.id);
    } catch (e) {
      say(`  ✗ ${(e as Error).message}`, "error");
    } finally {
      setBusy(false);
    }
  }

  const tenetButtons = (ids: string[], empty: string) => (
    <div className="dependencies">
      {ids.length ? ids.map((id) => <button key={id} onClick={() => onSelect(id)}>{ref(id)}</button>) : <span>{empty}</span>}
    </div>
  );

  return (
    <aside className="inspector tenet-detail" aria-label="Tenet inspector">
      <button className="close-inspector" onClick={() => onSelect(null)} aria-label="Close inspector">×</button>
      <span className="eyebrow">TENET · LEVEL {t.level} · {t.is_leaf ? "LEAF: ONE BEHAVIOUR" : "FEATURE: COMPOSED OF PARTS"}</span>
      <h2>{t.name}</h2>
      <nav className="crumbs" aria-label="Ownership path">
        {path.map((p, i) => (
          <span key={p.id}>
            {i > 0 ? " › " : ""}
            {p.id === t.id ? <b>{p.name}</b> : <button className="inline-link" onClick={() => onSelect(p.id)}>{p.name}</button>}
          </span>
        ))}
      </nav>

      <h3>What it does</h3>
      <p className="prose">{t.functionality || <span className="muted">no functionality statement yet</span>}</p>
      {t.open_unknowns?.length ? (
        <div className="unknowns">
          <b>open unknowns</b>
          <ul>{t.open_unknowns.map((u) => <li key={u}>{u}</li>)}</ul>
          <em>The Intent Builder never guessed these; they drop confidence on this tenet&apos;s claims.</em>
        </div>
      ) : null}

      <h3>Claim coverage</h3>
      <div className="coverage" role="img" aria-label={`${locked} of ${all.length} claims locked`}>
        <i><b style={{ width: `${pct}%` }} /></i>
        <span>{locked}/{all.length} locked · {pct}%</span>
      </div>
      <dl className="stats">
        <div><dt>roll-up</dt><dd>{VERDICT_GLYPH[t.rollup]} {t.rollup}</dd></div>
        <div><dt>test runs</dt><dd>{runs}</dd></div>
        <div><dt>avg confidence</dt><dd>{avgConf === null ? "n/a" : `${avgConf}%`}</dd></div>
        <div><dt>unverified</dt><dd>{unverified}</dd></div>
        <div><dt>flagged</dt><dd className={flagged ? "bad" : ""}>{flagged}</dd></div>
        <div><dt>no recipe</dt><dd>{noRecipe}</dd></div>
      </dl>
      <ul className="readiness">
        {readiness.map(([ok, label]) => (
          <li key={label} className={ok ? "ok" : ""}>{ok ? "✓" : "○"} {label}</li>
        ))}
      </ul>

      <h3>Claim map</h3>
      <ClaimMap groups={groups} activeClaim={activeClaim} onOpenClaim={onOpenClaim} onOpenTenet={onSelect} />

      <h3>Claims · {claims.length}</h3>
      {ordered.length ? (
        <ul className="claim-list">
          {ordered.map((c) => (
            <li key={c.id}>
              <button className={`claim-item ${c.status === "axiom" ? "axiom" : "hyp"} ${activeClaim === c.id ? "active" : ""} ${c.flags.length ? "flagged" : ""}`} onClick={() => onOpenClaim(c.id)}>
                <span className="tag">{c.status === "axiom" ? "◆ axiom" : "◇ hypothesis"}</span>
                <span className="text">{c.statement}</span>
                <span className="meta">
                  <i className={`g v-${c.result.verdict}`}>{VERDICT_GLYPH[c.result.verdict]} {c.result.verdict}</i>
                  <i>{Math.round(c.confidence * 100)}%</i>
                  {c.dependencies.length ? <i>↳ {c.dependencies.length}</i> : null}
                  {c.flags.length ? <i className="bad">⚑</i> : null}
                  <i className="open">open →</i>
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">
          {t.is_leaf ? "no claims yet: add a hypothesis or let the Intent Builder draft them." : "no integration claims here; its parts hold the claims. They are mapped above."}
        </p>
      )}
      {wsApi ? (
        adding ? (
          <div className="add-claim">
            <label>your wording, kept verbatim as the statement</label>
            <textarea autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="one testable assertion" />
            <span>
              <button className="act go" disabled={busy || !draft.trim()} onClick={() => void addHypothesis()}>add hypothesis</button>
              <button className="act" onClick={() => { setAdding(false); setDraft(""); }}>cancel</button>
            </span>
          </div>
        ) : (
          <button className="act add" onClick={() => setAdding(true)}>+ hypothesis</button>
        )
      ) : null}

      {t.children.length ? (
        <>
          <h3>Composed of · {t.children.length}</h3>
          <ul className="parts">
            {t.children.map((id) => {
              const c = byId.get(id);
              if (!c) return null;
              return (
                <li key={id}>
                  <button onClick={() => onSelect(id)}>
                    <b>{c.name}</b>
                    <span>{firstSentence(c.functionality) || "no description"}</span>
                    <small><i className="ax">{c.axioms}A</i> <i className="hy">{c.hypotheses}H</i> · {VERDICT_GLYPH[c.rollup]} {c.rollup}{c.flagged_axioms ? ` · ⚑ ${c.flagged_axioms}` : ""}</small>
                  </button>
                </li>
              );
            })}
          </ul>
        </>
      ) : null}

      <h3>Uses (references)</h3>
      {tenetButtons(t.references, "none")}
      <h3>Used by</h3>
      {tenetButtons(t.referenced_by, "none")}
      {t.cross_cutting?.length ? (
        <>
          <h3>Cross-cutting concerns</h3>
          <div className="dependencies">{t.cross_cutting.map((c) => <span key={c}>{c}</span>)}</div>
        </>
      ) : null}

      <h3>Code footprint · {files.length} file{files.length === 1 ? "" : "s"}</h3>
      {t.code_links.length ? (
        <ul className="footprint">
          {t.code_links.map((l) => (
            <li key={l.path + (l.start_line ?? "")}>
              <code>{l.path}{l.start_line ? `:${l.start_line}${l.end_line ? `-${l.end_line}` : ""}` : ""}</code>
              {l.symbol ? <span>{l.symbol}</span> : null}
            </li>
          ))}
        </ul>
      ) : files.length ? (
        <ul className="footprint">{files.map((f) => <li key={f}><code>{f}</code><span>via parts</span></li>)}</ul>
      ) : (
        <p className="muted">no code linked yet.</p>
      )}

      {!wsApi ? <p className="muted">offline fixture: connect the backend to change anything.</p> : null}

      <button className="generate" disabled={!files.length} onClick={() => onShowInGraph(t.id)}>
        {graphNodes.length
          ? `show ${graphNodes.length} node${graphNodes.length > 1 ? "s" : ""} in codebase graph`
          : files.length ? "show in codebase graph" : "no code linked yet"}
      </button>
      <span className="muted id-line">{t.id}{t.proposed ? " · proposed, awaiting review" : ""}</span>
    </aside>
  );
}
