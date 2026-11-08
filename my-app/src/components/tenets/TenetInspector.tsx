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
  updateTree?(updater: (prev: TreeView) => TreeView): void;
  onGenerateTests?(tenetId: string): void;
}

const firstSentence = (s: string) => (s.match(/^.*?[.!?](\s|$)/)?.[0] ?? s).trim();

export function TenetInspector({ tree, tenetId, wsApi, graphNodes, activeClaim, onSelect, onOpenClaim, onShowInGraph, onChanged, say, updateTree, onGenerateTests }: Props) {
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");
  const [draftExplanation, setDraftExplanation] = useState("");
  const [draftImplementation, setDraftImplementation] = useState("");
  const [draftConfidence, setDraftConfidence] = useState(0.8);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<"overview" | "claims" | "structure" | "code" | "edit">("overview");
  const t = tree.tenets.find((x) => x.id === tenetId);
  const byId = useMemo(() => new Map(tree.tenets.map((x) => [x.id, x])), [tree.tenets]);

  // Tenet edit form state
  const [editName, setEditName] = useState(t?.name ?? "");
  const [editFunc, setEditFunc] = useState(t?.functionality ?? "");
  const [editParent, setEditParent] = useState(t?.parent_id ?? "");
  const [editCross, setEditCross] = useState<string[]>(t?.cross_cutting || []);
  const [editUnknowns, setEditUnknowns] = useState<string[]>(t?.open_unknowns || []);
  const [editLinks, setEditLinks] = useState(t?.code_links || []);
  const [newCross, setNewCross] = useState("");
  const [newUnknown, setNewUnknown] = useState("");
  const [newLinkPath, setNewLinkPath] = useState("");

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

  async function saveTenetEdits() {
    setBusy(true);
    try {
      if (wsApi) {
        await wsApi.updateTenet(t!.id, {
          name: editName,
          functionality: editFunc,
          cross_cutting: editCross,
          open_unknowns: editUnknowns,
        });
        if (editParent !== (t!.parent_id ?? "") && editParent) {
          await wsApi.moveTenet(t!.id, editParent);
        }
        await wsApi.setLinks(t!.id, editLinks);
      }
      if (updateTree) {
        updateTree((prev) => ({
          ...prev,
          tenets: prev.tenets.map((x) =>
            x.id === t!.id
              ? {
                  ...x,
                  name: editName,
                  functionality: editFunc,
                  parent_id: editParent || null,
                  cross_cutting: editCross,
                  open_unknowns: editUnknowns,
                  code_links: editLinks,
                }
              : x
          ),
        }));
      }
      say(`  ✓ updated Tenet "${editName}"`, "success");
      onChanged();
      setTab("overview");
    } catch (e) {
      say(`  ✗ ${(e as Error).message}`, "error");
    } finally {
      setBusy(false);
    }
  }

  async function deleteCurrentTenet() {
    if (!confirm(`Delete Tenet "${t!.name}"?`)) return;
    setBusy(true);
    try {
      if (wsApi) {
        await wsApi.deleteTenet(t!.id);
      }
      if (updateTree) {
        updateTree((prev) => ({
          ...prev,
          tenets: prev.tenets.filter((x) => x.id !== t!.id),
        }));
      }
      say(`  ✓ deleted Tenet "${t!.name}"`, "success");
      onSelect(null);
      onChanged();
    } catch (e) {
      say(`  ✗ ${(e as Error).message}`, "error");
    } finally {
      setBusy(false);
    }
  }

  async function addHypothesis() {
    if (!draft.trim()) return;
    setBusy(true);
    try {
      let claimId = `c_${Math.random().toString(16).slice(2, 10)}`;
      if (wsApi) {
        const c = await wsApi.createClaim(t!.id, {
          statement: draft.trim(),
          test_explanation: draftExplanation.trim(),
          test_implementation: draftImplementation.trim(),
          confidence: draftConfidence,
        });
        claimId = c.id;
      }
      if (updateTree) {
        updateTree((prev) => {
          const newC: Claim = {
            id: claimId,
            tenet_id: t!.id,
            status: "hypothesis",
            verification: null,
            confidence: draftConfidence,
            proposed: false,
            flags: [],
            version: 1,
            statement: draft.trim(),
            test_explanation: draftExplanation.trim(),
            test_implementation: draftImplementation.trim(),
            dependencies: [],
            content_hash: claimId,
            provenance: { via: "manual" },
            result: { verdict: "untested", flaky: false, runs: 0, last_run_at: null },
          };
          return {
            ...prev,
            tenets: prev.tenets.map((x) =>
              x.id === t!.id ? { ...x, claims: [...x.claims, claimId], hypotheses: x.hypotheses + 1 } : x
            ),
            claims: { ...prev.claims, [claimId]: newC },
          };
        });
      }
      say(`  ✓ added hypothesis ${claimId}: "${draft.trim()}"`, "success");
      setDraft("");
      setDraftExplanation("");
      setDraftImplementation("");
      setAdding(false);
      onChanged();
      onOpenClaim(claimId);
    } catch (e) {
      say(`  ✗ ${(e as Error).message}`, "error");
    } finally {
      setBusy(false);
    }
  }

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
        { id: "edit", label: "✎ Edit" },
      ]}
      tab={tab}
      onTab={(x) => setTab(x as typeof tab)}
      onClose={() => onSelect(null)}
      footer={
        <div style={{ display: "flex", flexDirection: "column", gap: "8px", width: "100%" }}>
          <button
            className="pn-cta"
            onClick={() => onGenerateTests?.(t.id)}
            title="Generate invariant tests for this intent tenet"
          >
            <span>Generate invariant tests</span>
            <i aria-hidden>→</i>
          </button>
          {files.length ? (
            <button
              className="pn-ghost"
              onClick={() => onShowInGraph(t.id)}
              style={{ width: "100%", textAlign: "center" }}
            >
              {graphNodes.length
                ? `Show ${graphNodes.length} node${graphNodes.length > 1 ? "s" : ""} in codebase graph →`
                : "Show in codebase graph →"}
            </button>
          ) : null}
        </div>
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
            {adding ? (
              <div className="pn-add" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <label htmlFor="pn-draft">Statement (assertion)</label>
                <textarea id="pn-draft" autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="One testable assertion" />
                <label>What the test checks</label>
                <input
                  type="text"
                  style={{ width: "100%", padding: "4px 8px", background: "rgba(0,0,0,0.2)", border: "1px solid var(--border)", borderRadius: 4, color: "inherit" }}
                  value={draftExplanation}
                  onChange={(e) => setDraftExplanation(e.target.value)}
                  placeholder="Why this matters"
                />
                <label>Implementation recipe</label>
                <textarea
                  value={draftImplementation}
                  onChange={(e) => setDraftImplementation(e.target.value)}
                  placeholder="INVOKE entry point. ASSERT expected outcome."
                />
                <label>Confidence: {Math.round(draftConfidence * 100)}%</label>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={draftConfidence}
                  onChange={(e) => setDraftConfidence(parseFloat(e.target.value))}
                />
                <span>
                  <button className="pn-ghost go" disabled={busy || !draft.trim()} onClick={() => void addHypothesis()}>Add hypothesis</button>
                  <button className="pn-ghost" onClick={() => { setAdding(false); setDraft(""); }}>Cancel</button>
                </span>
              </div>
            ) : (
              <button className="pn-dashed" onClick={() => setAdding(true)}>+ New hypothesis</button>
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

      {tab === "edit" ? (
        <div className="pn-edit-tenet" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div>
            <label style={{ fontSize: 11, textTransform: "uppercase", color: "var(--text-dim)", display: "block", marginBottom: 4 }}>
              Tenet Name
            </label>
            <input
              type="text"
              style={{ width: "100%", padding: "6px 8px", background: "rgba(0,0,0,0.2)", border: "1px solid var(--border)", borderRadius: 4, color: "inherit" }}
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
            />
          </div>

          <div>
            <label style={{ fontSize: 11, textTransform: "uppercase", color: "var(--text-dim)", display: "block", marginBottom: 4 }}>
              Functionality Statement
            </label>
            <textarea
              rows={4}
              style={{ width: "100%", padding: "6px 8px", background: "rgba(0,0,0,0.2)", border: "1px solid var(--border)", borderRadius: 4, color: "inherit" }}
              value={editFunc}
              onChange={(e) => setEditFunc(e.target.value)}
            />
          </div>

          <div>
            <label style={{ fontSize: 11, textTransform: "uppercase", color: "var(--text-dim)", display: "block", marginBottom: 4 }}>
              Parent Tenet (Structure)
            </label>
            <select
              style={{ width: "100%", padding: "6px 8px", background: "rgba(0,0,0,0.2)", border: "1px solid var(--border)", borderRadius: 4, color: "inherit" }}
              value={editParent}
              onChange={(e) => setEditParent(e.target.value)}
              disabled={!t.parent_id}
            >
              {!t.parent_id && <option value="">Root Tenet (cannot be moved)</option>}
              {tree.tenets
                .filter((x) => x.id !== t.id && !x.code_links.length)
                .map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.name} ({x.id})
                  </option>
                ))}
            </select>
          </div>

          <div>
            <label style={{ fontSize: 11, textTransform: "uppercase", color: "var(--text-dim)", display: "block", marginBottom: 4 }}>
              Cross-Cutting Concerns ({editCross.length})
            </label>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 6 }}>
              {editCross.map((c) => (
                <span key={c} style={{ background: "rgba(255,255,255,0.08)", padding: "2px 8px", borderRadius: 12, fontSize: 12, display: "inline-flex", alignItems: "center", gap: 6 }}>
                  {c}
                  <button type="button" onClick={() => setEditCross(editCross.filter((x) => x !== c))} style={{ background: "none", border: "none", color: "inherit", cursor: "pointer" }}>×</button>
                </span>
              ))}
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              <input
                type="text"
                placeholder="Add concern (e.g. security, auth)"
                style={{ flex: 1, padding: "4px 8px", background: "rgba(0,0,0,0.2)", border: "1px solid var(--border)", borderRadius: 4, color: "inherit" }}
                value={newCross}
                onChange={(e) => setNewCross(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && newCross.trim()) {
                    e.preventDefault();
                    if (!editCross.includes(newCross.trim())) setEditCross([...editCross, newCross.trim()]);
                    setNewCross("");
                  }
                }}
              />
              <button
                type="button"
                className="pn-ghost"
                onClick={() => {
                  if (newCross.trim() && !editCross.includes(newCross.trim())) {
                    setEditCross([...editCross, newCross.trim()]);
                    setNewCross("");
                  }
                }}
              >
                Add
              </button>
            </div>
          </div>

          <div>
            <label style={{ fontSize: 11, textTransform: "uppercase", color: "var(--text-dim)", display: "block", marginBottom: 4 }}>
              Open Unknowns ({editUnknowns.length})
            </label>
            <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 6 }}>
              {editUnknowns.map((u, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", background: "rgba(255,255,255,0.04)", padding: "4px 8px", borderRadius: 4, fontSize: 12 }}>
                  <span>{u}</span>
                  <button type="button" onClick={() => setEditUnknowns(editUnknowns.filter((_, idx) => idx !== i))} style={{ background: "none", border: "none", color: "inherit", cursor: "pointer" }}>×</button>
                </div>
              ))}
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              <input
                type="text"
                placeholder="Add open architectural question..."
                style={{ flex: 1, padding: "4px 8px", background: "rgba(0,0,0,0.2)", border: "1px solid var(--border)", borderRadius: 4, color: "inherit" }}
                value={newUnknown}
                onChange={(e) => setNewUnknown(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && newUnknown.trim()) {
                    e.preventDefault();
                    setEditUnknowns([...editUnknowns, newUnknown.trim()]);
                    setNewUnknown("");
                  }
                }}
              />
              <button
                type="button"
                className="pn-ghost"
                onClick={() => {
                  if (newUnknown.trim()) {
                    setEditUnknowns([...editUnknowns, newUnknown.trim()]);
                    setNewUnknown("");
                  }
                }}
              >
                Add
              </button>
            </div>
          </div>

          <div>
            <label style={{ fontSize: 11, textTransform: "uppercase", color: "var(--text-dim)", display: "block", marginBottom: 4 }}>
              Code Links ({editLinks.length})
            </label>
            <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 6 }}>
              {editLinks.map((l, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", background: "rgba(255,255,255,0.04)", padding: "4px 8px", borderRadius: 4, fontSize: 12 }}>
                  <code>{l.path}</code>
                  <button type="button" onClick={() => setEditLinks(editLinks.filter((_, idx) => idx !== i))} style={{ background: "none", border: "none", color: "inherit", cursor: "pointer" }}>×</button>
                </div>
              ))}
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              <input
                type="text"
                placeholder="File path e.g. src/auth/session.py"
                style={{ flex: 1, padding: "4px 8px", background: "rgba(0,0,0,0.2)", border: "1px solid var(--border)", borderRadius: 4, color: "inherit" }}
                value={newLinkPath}
                onChange={(e) => setNewLinkPath(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && newLinkPath.trim()) {
                    e.preventDefault();
                    setEditLinks([...editLinks, { path: newLinkPath.trim() }]);
                    setNewLinkPath("");
                  }
                }}
              />
              <button
                type="button"
                className="pn-ghost"
                onClick={() => {
                  if (newLinkPath.trim()) {
                    setEditLinks([...editLinks, { path: newLinkPath.trim() }]);
                    setNewLinkPath("");
                  }
                }}
              >
                Add Link
              </button>
            </div>
          </div>

          <div style={{ display: "flex", gap: 8, marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
            <button className="pn-ghost go" style={{ flex: 1, fontWeight: "bold" }} disabled={busy || !editName.trim()} onClick={() => void saveTenetEdits()}>
              Save Tenet
            </button>
            <button className="pn-ghost" onClick={() => setTab("overview")}>
              Cancel
            </button>
            {t.parent_id && (
              <button className="pn-ghost bad" style={{ color: "var(--red)" }} onClick={() => void deleteCurrentTenet()}>
                Delete Tenet
              </button>
            )}
          </div>
        </div>
      ) : null}
    </Panel>
  );
}
