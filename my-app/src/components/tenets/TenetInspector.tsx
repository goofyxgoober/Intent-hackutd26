"use client";

import { useMemo, useState } from "react";
import type { Claim, Tenet, TreeView, workspaceApi } from "@/gh/intentApi";
import { VERDICT_GLYPH } from "@/lib/claimStyle";
import { claimGroups, pathsUnder } from "@/lib/tenetLinks";
import { ClaimMap } from "./ClaimMap";
import { TERMS } from "@/components/panel/Guide";
import { Block, CopyChip, Panel, Ring } from "@/components/panel/Panel";

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
  const [tab, setTab] = useState<"overview" | "claims" | "structure" | "code">("overview");
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

  const chips = (ids: string[], empty: string) =>
    ids.length ? (
      <div className="pn-chips">
        {ids.map((id) => (
          <button key={id} onClick={() => onSelect(id)}><b>{ref(id)}</b></button>
        ))}
      </div>
    ) : (
      <p className="pn-empty">{empty}</p>
    );

  const readyCount = readiness.filter(([ok]) => ok).length;
  const stats: [string, string | number, string?][] = [
    ["roll-up", `${VERDICT_GLYPH[t.rollup]} ${t.rollup}`],
    ["test runs", runs],
    ["confidence", avgConf === null ? "n/a" : `${avgConf}%`],
    ["unverified", unverified, unverified ? "warn" : ""],
    ["flagged", flagged, flagged ? "bad" : ""],
    ["no recipe", noRecipe, noRecipe ? "warn" : ""],
  ];

  return (
    <Panel
      tone="tenet"
      label="Tenet inspector"
      eyebrow={<>L{t.level} · {t.is_leaf ? "leaf behaviour" : "feature"} · <span className={`pn-roll v-${t.rollup}`}>{VERDICT_GLYPH[t.rollup]} {t.rollup}</span></>}
      title={t.name}
      sub={
        path.length > 1 ? (
          <nav className="pn-crumbs" aria-label="Ownership path">
            {path.map((p, i) => (
              <span key={p.id}>
                {i > 0 ? <i aria-hidden>›</i> : null}
                {p.id === t.id ? <b>{p.name}</b> : <button onClick={() => onSelect(p.id)}>{p.name}</button>}
              </span>
            ))}
          </nav>
        ) : (
          <CopyChip text={t.id} />
        )
      }
      tabs={[
        { id: "overview", label: "Overview" },
        { id: "claims", label: "Claims", count: claims.length, alert: failing + flagged > 0 },
        { id: "structure", label: "Structure", count: t.children.length + t.references.length + t.referenced_by.length },
        { id: "code", label: "Code", count: files.length },
      ]}
      tab={tab}
      onTab={(x) => setTab(x as typeof tab)}
      onClose={() => onSelect(null)}
      footer={
        <button className="pn-cta" disabled={!files.length} onClick={() => onShowInGraph(t.id)}>
          <span>
            {graphNodes.length
              ? `Show ${graphNodes.length} node${graphNodes.length > 1 ? "s" : ""} in codebase graph`
              : files.length ? "Show in codebase graph" : "No code linked yet"}
          </span>
          <i aria-hidden>→</i>
        </button>
      }
    >
      {tab === "overview" ? (
        <>
          <p className="pn-lead">{t.functionality || <span className="pn-empty">No functionality statement yet.</span>}</p>
          {t.open_unknowns?.length ? (
            <div className="pn-unknowns">
              <b>Open unknowns</b>
              <ul>{t.open_unknowns.map((u) => <li key={u}>{u}</li>)}</ul>
              <small>The Intent Builder never guessed these; they lower confidence on this tenet&apos;s claims.</small>
            </div>
          ) : null}

          <div className="pn-hero">
            <Ring value={all.length ? locked / all.length : 0} label={`${pct}%`} sub="locked" />
            <dl className="pn-stats">
              {stats.map(([k, v, tone]) => (
                <div key={k} className={tone}>
                  <dd>{v}</dd>
                  <dt>{k}</dt>
                </div>
              ))}
            </dl>
          </div>

          <Block title="Ready to lock?" aside={`${readyCount}/${readiness.length}`}>
            <ul className="pn-checks">
              {readiness.map(([ok, label], i) => (
                <li key={label} className={ok ? "ok" : ""} style={{ ["--i" as string]: i }}>
                  <i aria-hidden>{ok ? "✓" : ""}</i>
                  {label}
                </li>
              ))}
            </ul>
          </Block>
        </>
      ) : null}

      {tab === "claims" ? (
        <>
          <div className="pn-terms">
            {(["axiom", "hypothesis"] as const).map((k) => (
              <div key={k} className={k}>
                <b>{TERMS[k].glyph} {TERMS[k].name} · {TERMS[k].state}</b>
                <span>{TERMS[k].def}</span>
              </div>
            ))}
          </div>
          <Block title="Claim map">
            <ClaimMap groups={groups} activeClaim={activeClaim} onOpenClaim={onOpenClaim} onOpenTenet={onSelect} />
          </Block>
          <Block title="All claims" aside={claims.length}>
            {ordered.length ? (
              <ul className="pn-claims">
                {ordered.map((c) => (
                  <li key={c.id}>
                    <button className={`${c.status === "axiom" ? "ax" : "hy"} ${activeClaim === c.id ? "active" : ""} ${c.flags.length ? "flagged" : ""}`} onClick={() => onOpenClaim(c.id)}>
                      <span className="kind">{c.status === "axiom" ? "◆ Axiom · locked" : "◇ Hypothesis · proposed"}</span>
                      <span className="text">{c.statement}</span>
                      <span className="meta">
                        <i className={`g v-${c.result.verdict}`}>{VERDICT_GLYPH[c.result.verdict]} {c.result.verdict}</i>
                        <i>{Math.round(c.confidence * 100)}%</i>
                        {c.dependencies.length ? <i>↳ {c.dependencies.length}</i> : null}
                        {c.flags.length ? <i className="bad">⚑</i> : null}
                        <i className="go">open →</i>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="pn-empty">
                {t.is_leaf ? "No claims yet. Add a hypothesis or let the Intent Builder draft them." : "No integration claims here; its parts hold the claims."}
              </p>
            )}
            {wsApi ? (
              adding ? (
                <div className="pn-add">
                  <label htmlFor="pn-draft">Your wording, kept verbatim</label>
                  <textarea id="pn-draft" autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="One testable assertion" />
                  <span>
                    <button className="pn-ghost go" disabled={busy || !draft.trim()} onClick={() => void addHypothesis()}>Add hypothesis</button>
                    <button className="pn-ghost" onClick={() => { setAdding(false); setDraft(""); }}>Cancel</button>
                  </span>
                </div>
              ) : (
                <button className="pn-dashed" onClick={() => setAdding(true)}>+ New hypothesis</button>
              )
            ) : (
              <p className="pn-note">Offline fixture: connect the backend to change anything.</p>
            )}
          </Block>
        </>
      ) : null}

      {tab === "structure" ? (
        <>
          {t.children.length ? (
            <Block title="Composed of" aside={t.children.length}>
              <ul className="pn-parts">
                {t.children.map((id) => {
                  const c = byId.get(id);
                  if (!c) return null;
                  return (
                    <li key={id}>
                      <button onClick={() => onSelect(id)}>
                        <b>{c.name}</b>
                        <span>{firstSentence(c.functionality) || "No description"}</span>
                        <small>
                          <i className="ax">◆ {c.axioms} locked</i>
                          <i className="hy">◇ {c.hypotheses} proposed</i>
                          <i>{VERDICT_GLYPH[c.rollup]} {c.rollup}</i>
                          {c.flagged_axioms ? <i className="bad">⚑ {c.flagged_axioms}</i> : null}
                        </small>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </Block>
          ) : null}
          <Block title="Uses" aside={t.references.length || undefined}>{chips(t.references, "Depends on no other tenet.")}</Block>
          <Block title="Used by" aside={t.referenced_by.length || undefined}>{chips(t.referenced_by, "No tenet depends on this one.")}</Block>
          {t.cross_cutting?.length ? (
            <Block title="Cross-cutting concerns">
              <div className="pn-chips ext">{t.cross_cutting.map((c) => <span key={c}>{c}</span>)}</div>
            </Block>
          ) : null}
        </>
      ) : null}

      {tab === "code" ? (
        <Block title="Code footprint" aside={`${files.length} file${files.length === 1 ? "" : "s"}`}>
          {t.code_links.length ? (
            <ul className="pn-files">
              {t.code_links.map((l) => (
                <li key={l.path + (l.start_line ?? "")}>
                  <CopyChip text={l.path}>{l.path}{l.start_line ? `:${l.start_line}${l.end_line ? `-${l.end_line}` : ""}` : ""}</CopyChip>
                  {l.symbol ? <span>{l.symbol}</span> : null}
                </li>
              ))}
            </ul>
          ) : files.length ? (
            <ul className="pn-files">{files.map((f) => <li key={f}><CopyChip text={f} /><span>via parts</span></li>)}</ul>
          ) : (
            <p className="pn-empty">No code linked yet.</p>
          )}
          <p className="pn-note">{t.id}{t.proposed ? " · proposed, awaiting review" : ""}</p>
        </Block>
      ) : null}
    </Panel>
  );
}
