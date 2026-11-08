import type { GraphIndex } from "@/lib/graph/model";
import { boundaryOf, reachable, shortestPath } from "@/lib/graph/model";
import type { GraphSource } from "@/lib/api/source";
import type { RetrievalOptions } from "@/lib/retrieval/engine";
import { focusFromIds, type Focus } from "@/lib/focus";
import type { Claim, Tenet, TreeView } from "@/gh/intentApi";
import { graphNodesFor, resolveTenet } from "@/lib/tenetLinks";

export type Tone = "prompt" | "success" | "error" | "muted" | "accent" | "plain";
export interface Line {
  id: number;
  text: string;
  tone?: Tone;
}

export interface CommandContext {
  index: GraphIndex | null;
  source: GraphSource;
  repo: string;
  focus: Focus | null;
  print(text: string | string[], tone?: Tone): void;
  clear(): void;
  select(id: string | null): void;
  setFocus(f: Focus | null): void;
  query(q: string, opts?: RetrievalOptions): Promise<Focus | null>;
  sync(): Promise<void>;
  fit(): void;
  /** Axiom/Tenet hierarchy (null until loaded or when signed out). */
  tenets: TreeView | null;
  view: "graph" | "tenets";
  setView(v: "graph" | "tenets"): void;
  selectTenet(id: string | null): void;
  openClaim(id: string | null): void;
  /** What the user has selected; sent with questions so the agent can resolve "this" (chat contract §3). */
  selection: {
    view: "intent" | "codebase";
    tenet_id: string | null;
    claim_id: string | null;
    file: string | null;
    node_id?: string | null;
    target_id?: string | null;
    name?: string | null;
    claim_statement?: string | null;
  };
  wsApi?: any;
  updateTree?(updater: (prev: TreeView) => TreeView): void;
}

export interface Command {
  name: string;
  aliases?: string[];
  usage: string;
  summary: string;
  /** Runs without a loaded graph (help, clear, sync). */
  offline?: boolean;
  run(args: string[], ctx: CommandContext, raw: string): void | Promise<void>;
}

/** exact id → id substring → name substring → null */
export function resolveNode(index: GraphIndex, term: string): string | null {
  const t = term.toLowerCase().replace(/\s+/g, "_");
  if (!t) return null;
  if (index.nodes.has(t)) return t;
  const ids = [...index.nodes.keys()];
  return (
    ids.find((id) => id.includes(t)) ??
    [...index.nodes.values()].find((n) => n.name.toLowerCase().includes(term.toLowerCase()))?.node_id ??
    null
  );
}

const inv = (i: number) => `INV_${String(i + 1).padStart(2, "0")}`;

function needNode(ctx: CommandContext, arg: string | undefined, usage: string): string | null {
  if (!arg) {
    ctx.print(`  usage: ${usage}`, "muted");
    return null;
  }
  const id = resolveNode(ctx.index!, arg);
  if (!id) ctx.print(`  node not found: ${arg}`, "error");
  return id;
}

function printFocus(ctx: CommandContext, f: Focus) {
  for (const h of f.hits) {
    const via = h.via ? ` ← ${h.via}` : "";
    ctx.print(`  ${h.hop === 0 ? "◆" : "├─"} ${h.node_id}  ${h.score.toFixed(2)}${via}`, h.hop === 0 ? "accent" : "plain");
  }
  ctx.print(`  ✓ ${f.nodeIds.size} codebase nodes · ~${f.tokens} context tokens${f.elapsedMs !== undefined ? ` · ${f.elapsedMs.toFixed(1)}ms` : ""}`, "success");
}

async function applyClaimEdit(ctx: CommandContext, claim: Claim, fields: Partial<Claim>) {
  if (ctx.wsApi) {
    if (claim.status === "axiom") {
      await ctx.wsApi.editAxiom(claim.id, fields, "modified via terminal");
    } else {
      await ctx.wsApi.editHypothesis(claim.id, fields);
    }
  }
  if (ctx.updateTree) {
    ctx.updateTree((prev) => ({
      ...prev,
      claims: {
        ...prev.claims,
        [claim.id]: {
          ...claim,
          ...fields,
          version: claim.version + 1,
        },
      },
    }));
  }
}

async function applyTenetEdit(ctx: CommandContext, tenet: Tenet, fields: Partial<Tenet>) {
  if (ctx.wsApi) {
    if (fields.name || fields.functionality || fields.cross_cutting || fields.open_unknowns) {
      await ctx.wsApi.updateTenet(tenet.id, {
        name: fields.name,
        functionality: fields.functionality,
        cross_cutting: fields.cross_cutting,
        open_unknowns: fields.open_unknowns,
      });
    }
    if (fields.code_links) {
      await ctx.wsApi.setLinks(tenet.id, fields.code_links);
    }
  }
  if (ctx.updateTree) {
    ctx.updateTree((prev) => ({
      ...prev,
      tenets: prev.tenets.map((t) => (t.id === tenet.id ? { ...t, ...fields } : t)),
    }));
  }
}

export const commands: Command[] = [
  {
    name: "help",
    usage: "help",
    summary: "list commands",
    offline: true,
    run(_a, ctx) {
      const w = Math.max(...commands.map((c) => c.usage.length));
      ctx.print(commands.map((c) => `  ${c.usage.padEnd(w)}  ${c.summary}`));
      ctx.print("  anything else is treated as a question → retrieval (+ agent if connected)", "muted");
    },
  },
  {
    name: "inspect",
    aliases: ["open", "cat"],
    usage: "inspect [node|tenet|claim]",
    summary: "open and retrieve details for a node, tenet, or claim",
    offline: true,
    run(args, ctx) {
      const term = args.join(" ").trim();
      if (!term) {
        if (ctx.selection.claim_id && ctx.tenets?.claims[ctx.selection.claim_id]) {
          const c = ctx.tenets.claims[ctx.selection.claim_id];
          ctx.print([
            `  ${c.status === "axiom" ? "◆ Axiom" : "◇ Hypothesis"} ${c.id} · ${c.result.verdict} (${Math.round(c.confidence * 100)}%)`,
            `  statement: ${c.statement}`,
            `  what the test checks: ${c.test_explanation || "(none)"}`,
            `  implementation recipe: ${c.test_implementation || "(none)"}`,
            `  dependencies: ${c.dependencies.join(", ") || "(none)"}`,
          ]);
          return;
        }
        if (ctx.selection.tenet_id && ctx.tenets) {
          const t = ctx.tenets.tenets.find((x) => x.id === ctx.selection.tenet_id);
          if (t) {
            ctx.print([
              `  Tenet: ${t.name} (L${t.level}) · Rollup: ${t.rollup} · ${t.id}`,
              `  functionality: ${t.functionality || "(none)"}`,
              `  claims: ${t.claims.length} total (${t.axioms}A / ${t.hypotheses}H)`,
              `  code links: ${t.code_links.map((l) => l.path).join(", ") || "(none)"}`,
            ]);
            for (const cid of t.claims) {
              const c = ctx.tenets.claims[cid];
              if (c) ctx.print(`    ${c.status === "axiom" ? "◆ A" : "· H"} [${c.result.verdict}] ${c.statement}`, c.status === "axiom" ? "accent" : "plain");
            }
            return;
          }
        }
        if (ctx.selection.node_id && ctx.index) {
          const n = ctx.index.nodes.get(ctx.selection.node_id);
          if (n) {
            ctx.print([`  ${n.name} · ${n.source_file}`, `  ${n.intent_summary}`]);
            n.business_invariants.forEach((s, i) => ctx.print(`  ${inv(i)}: ${s}`));
            return;
          }
        }
        ctx.print(`  usage: ${this.usage}`, "muted");
        return;
      }

      // 1. Check if term matches a Claim
      if (ctx.tenets) {
        const cLower = term.toLowerCase();
        const claimMatch =
          ctx.tenets.claims[term] ??
          Object.values(ctx.tenets.claims).find(
            (c) => c.id.toLowerCase() === cLower || c.id.toLowerCase().includes(cLower) || c.statement.toLowerCase().includes(cLower)
          );
        if (claimMatch) {
          ctx.setView("tenets");
          ctx.openClaim(claimMatch.id);
          ctx.print([
            `  ${claimMatch.status === "axiom" ? "◆ Axiom" : "◇ Hypothesis"} ${claimMatch.id} · ${claimMatch.result.verdict} (${Math.round(claimMatch.confidence * 100)}%)`,
            `  statement: ${claimMatch.statement}`,
            `  what the test checks: ${claimMatch.test_explanation || "(none)"}`,
            `  implementation recipe: ${claimMatch.test_implementation || "(none)"}`,
            `  dependencies: ${claimMatch.dependencies.join(", ") || "(none)"}`,
          ]);
          return;
        }

        // 2. Check if term matches a Tenet
        const tId = resolveTenet(ctx.tenets, term);
        if (tId) {
          const t = ctx.tenets.tenets.find((x) => x.id === tId)!;
          ctx.setView("tenets");
          ctx.selectTenet(t.id);
          ctx.print([
            `  Tenet: ${t.name} · level ${t.level} · ${t.rollup} · ${t.id}`,
            `  functionality: ${t.functionality || "(none)"}`,
            `  claims: ${t.claims.length} total (${t.axioms}A / ${t.hypotheses}H)`,
            `  code links: ${t.code_links.map((l) => l.path).join(", ") || "(none)"}`,
          ]);
          for (const cid of t.claims) {
            const c = ctx.tenets.claims[cid];
            if (c) ctx.print(`    ${c.status === "axiom" ? "◆ A" : "· H"} [${c.result.verdict}] ${c.statement}`, c.status === "axiom" ? "accent" : "plain");
          }
          return;
        }
      }

      // 3. Check codebase nodes
      if (ctx.index) {
        const id = resolveNode(ctx.index, term);
        if (id) {
          const n = ctx.index.nodes.get(id)!;
          ctx.setView("graph");
          ctx.select(id);
          ctx.print([`  ${n.name} · ${n.source_file}`, `  ${n.intent_summary}`]);
          n.business_invariants.forEach((s, i) => ctx.print(`  ${inv(i)}: ${s}`));
          return;
        }
      }

      ctx.print(`  target not found in codebase, tenets, or claims: "${term}"`, "error");
    },
  },
  {
    name: "modify",
    aliases: ["/modify", "modify:", "/modify:", "edit", "/edit", "/edit:"],
    usage: "modify [target] [field:] <instruction or value>",
    summary: "alter the selected tenet, claim, or codebase node (or specify target)",
    offline: true,
    async run(args, ctx, raw) {
      let body = raw.trim();
      body = body.replace(/^\/?(modify|edit):?\s*/i, "").trim();
      if (!body) {
        ctx.print([
          `  usage: ${this.usage}`,
          "  examples:",
          "    modify name: New Tenet Name",
          "    modify functionality: Validates HMAC token signature",
          "    modify add hypothesis: Expired tokens reject with HTTP 401",
          "    modify statement: Card CVV must never be logged",
          "    modify confidence: 0.95",
          "    modify add invariant: Stock counter cannot decrement below zero",
          "    modify t_3c3624556b71 : name: Updated Name",
          "    /modify add a hypothesis that charges > $10,000 enter fraud hold",
        ], "muted");
        return;
      }

      let targetId: string | null = null;
      let targetType: "tenet" | "claim" | "node" | null = null;

      const colonIdx = body.indexOf(":");
      const firstToken = body.split(/\s+/)[0];

      if (ctx.tenets && ctx.tenets.claims[firstToken]) {
        targetId = firstToken;
        targetType = "claim";
        body = body.slice(firstToken.length).trim().replace(/^:\s*/, "");
      } else if (ctx.tenets && ctx.tenets.tenets.some((t) => t.id === firstToken)) {
        targetId = firstToken;
        targetType = "tenet";
        body = body.slice(firstToken.length).trim().replace(/^:\s*/, "");
      } else if (ctx.index && ctx.index.nodes.has(firstToken)) {
        targetId = firstToken;
        targetType = "node";
        body = body.slice(firstToken.length).trim().replace(/^:\s*/, "");
      } else if (colonIdx > 0 && colonIdx < 40) {
        const potentialTarget = body.slice(0, colonIdx).trim();
        if (ctx.tenets && ctx.tenets.claims[potentialTarget]) {
          targetId = potentialTarget;
          targetType = "claim";
          body = body.slice(colonIdx + 1).trim();
        } else if (ctx.tenets && ctx.tenets.tenets.some((t) => t.id === potentialTarget)) {
          targetId = potentialTarget;
          targetType = "tenet";
          body = body.slice(colonIdx + 1).trim();
        } else if (ctx.index && ctx.index.nodes.has(potentialTarget)) {
          targetId = potentialTarget;
          targetType = "node";
          body = body.slice(colonIdx + 1).trim();
        }
      }

      if (!targetId) {
        if (ctx.selection.view === "intent") {
          if (ctx.selection.claim_id) {
            targetId = ctx.selection.claim_id;
            targetType = "claim";
          } else if (ctx.selection.tenet_id) {
            targetId = ctx.selection.tenet_id;
            targetType = "tenet";
          }
        } else if (ctx.selection.node_id) {
          targetId = ctx.selection.node_id;
          targetType = "node";
        }
      }

      if (!targetId && ctx.view === "tenets" && ctx.tenets?.root_id) {
        targetId = ctx.tenets.root_id;
        targetType = "tenet";
      }

      if (!targetId) {
        ctx.print("  nothing selected to modify. Click a tenet, claim, or codebase node, or specify target: 'modify <id> : <instruction>'", "error");
        return;
      }

      ctx.print(`  modifying ${targetType} [${targetId}]…`, "muted");

      if (targetType === "claim") {
        const claim = ctx.tenets?.claims[targetId];
        if (!claim) {
          ctx.print(`  claim not found: ${targetId}`, "error");
          return;
        }

        const lower = body.toLowerCase();
        if (lower.startsWith("statement:") || lower.startsWith("stmt:")) {
          const val = body.replace(/^(statement|stmt):\s*/i, "").trim();
          await applyClaimEdit(ctx, claim, { statement: val });
          ctx.print(`  ✓ updated statement on ${claim.id}: "${val}"`, "success");
        } else if (lower.startsWith("explanation:") || lower.startsWith("why:")) {
          const val = body.replace(/^(explanation|why):\s*/i, "").trim();
          await applyClaimEdit(ctx, claim, { test_explanation: val });
          ctx.print(`  ✓ updated test explanation on ${claim.id}`, "success");
        } else if (lower.startsWith("recipe:") || lower.startsWith("implementation:") || lower.startsWith("test:")) {
          const val = body.replace(/^(recipe|implementation|test):\s*/i, "").trim();
          await applyClaimEdit(ctx, claim, { test_implementation: val });
          ctx.print(`  ✓ updated implementation recipe on ${claim.id}`, "success");
        } else if (lower.startsWith("confidence:") || lower.startsWith("conf:")) {
          let num = parseFloat(body.replace(/^(confidence|conf):\s*/i, "").trim().replace("%", ""));
          if (num > 1) num = num / 100;
          num = Math.max(0, Math.min(1, num));
          await applyClaimEdit(ctx, claim, { confidence: num });
          ctx.print(`  ✓ updated confidence on ${claim.id} to ${Math.round(num * 100)}%`, "success");
        } else if (lower.startsWith("dependencies:") || lower.startsWith("deps:")) {
          const val = body.replace(/^(dependencies|deps):\s*/i, "").split(/[,\s]+/).map((s) => s.trim()).filter(Boolean);
          await applyClaimEdit(ctx, claim, { dependencies: val });
          ctx.print(`  ✓ updated dependencies on ${claim.id}: [${val.join(", ")}]`, "success");
        } else if (lower === "promote") {
          if (ctx.wsApi) await ctx.wsApi.promote(claim.id, true);
          if (ctx.updateTree) ctx.updateTree((prev) => ({
            ...prev,
            claims: { ...prev.claims, [claim.id]: { ...claim, status: "axiom", verification: "accepted_without_verification" } }
          }));
          ctx.print(`  ✓ promoted ${claim.id} to Axiom`, "success");
        } else if (lower.startsWith("demote")) {
          const reason = body.replace(/^demote:?\s*/i, "").trim() || "demoted via terminal";
          if (ctx.wsApi) await ctx.wsApi.demote(claim.id, reason);
          if (ctx.updateTree) ctx.updateTree((prev) => ({
            ...prev,
            claims: { ...prev.claims, [claim.id]: { ...claim, status: "hypothesis" } }
          }));
          ctx.print(`  ✓ demoted ${claim.id} to Hypothesis`, "success");
        } else {
          const cleanText = body.replace(/^set\s+/i, "").replace(/^change\s+to\s+/i, "");
          await applyClaimEdit(ctx, claim, { statement: cleanText });
          ctx.print(`  ✓ updated statement on ${claim.id}: "${cleanText}"`, "success");
        }

        await ctx.sync();
        ctx.openClaim(claim.id);
        return;
      }

      if (targetType === "tenet") {
        const tenet = ctx.tenets?.tenets.find((t) => t.id === targetId);
        if (!tenet) {
          ctx.print(`  tenet not found: ${targetId}`, "error");
          return;
        }

        const lower = body.toLowerCase();
        if (
          lower.startsWith("add hypothesis:") ||
          lower.startsWith("add claim:") ||
          lower.startsWith("hypothesis:") ||
          lower.startsWith("claim:") ||
          lower.startsWith("add hypothesis") ||
          lower.startsWith("add claim")
        ) {
          const stmt = body.replace(/^(add\s+)?(hypothesis|claim):?\s*/i, "").trim();
          if (!stmt) {
            ctx.print("  usage: modify add hypothesis: <testable statement>", "error");
            return;
          }
          let newClaimId = `c_${Math.random().toString(16).slice(2, 10)}`;
          if (ctx.wsApi) {
            try {
              const created = await ctx.wsApi.createClaim(tenet.id, {
                statement: stmt,
                test_explanation: `Verifies invariant rule for ${tenet.name}`,
                test_implementation: `INVOKE entry point in ${tenet.code_links[0]?.path || tenet.name}. ASSERT: ${stmt}`,
                confidence: 0.8,
              });
              newClaimId = created.id;
            } catch (e) {
              /* ignore and fall through to local update */
            }
          }
          if (ctx.updateTree) {
            ctx.updateTree((prev) => {
              const newC = {
                id: newClaimId,
                tenet_id: tenet.id,
                status: "hypothesis" as const,
                verification: null,
                confidence: 0.8,
                proposed: false,
                flags: [],
                version: 1,
                statement: stmt,
                test_explanation: `Verifies invariant rule for ${tenet.name}`,
                test_implementation: `INVOKE entry point in ${tenet.code_links[0]?.path || tenet.name}. ASSERT: ${stmt}`,
                dependencies: [],
                content_hash: newClaimId,
                provenance: { via: "manual" },
                result: { verdict: "untested" as const, flaky: false, runs: 0, last_run_at: null },
              };
              return {
                ...prev,
                tenets: prev.tenets.map((t) => (t.id === tenet.id ? { ...t, claims: [...t.claims, newClaimId], hypotheses: t.hypotheses + 1 } : t)),
                claims: { ...prev.claims, [newClaimId]: newC },
              };
            });
          }
          ctx.print(`  ✓ added Hypothesis ${newClaimId} to Tenet "${tenet.name}":`, "success");
          ctx.print(`    "${stmt}"`);
          await ctx.sync();
          ctx.openClaim(newClaimId);
          return;
        }

        if (lower.startsWith("name:") || lower.startsWith("title:")) {
          const val = body.replace(/^(name|title):\s*/i, "").trim();
          await applyTenetEdit(ctx, tenet, { name: val });
          ctx.print(`  ✓ updated name of tenet ${tenet.id}: "${val}"`, "success");
        } else if (lower.startsWith("functionality:") || lower.startsWith("func:") || lower.startsWith("desc:")) {
          const val = body.replace(/^(functionality|func|desc):\s*/i, "").trim();
          await applyTenetEdit(ctx, tenet, { functionality: val });
          ctx.print(`  ✓ updated functionality of tenet "${tenet.name}"`, "success");
        } else if (lower.startsWith("add link:") || lower.startsWith("link:")) {
          const p = body.replace(/^(add\s+)?link:\s*/i, "").trim();
          const links = [...tenet.code_links, { path: p }];
          await applyTenetEdit(ctx, tenet, { code_links: links });
          ctx.print(`  ✓ added code link "${p}" to tenet "${tenet.name}"`, "success");
        } else if (lower.startsWith("unknown:") || lower.startsWith("add unknown:")) {
          const q = body.replace(/^(add\s+)?unknown:\s*/i, "").trim();
          const unknowns = [...(tenet.open_unknowns || []), q];
          await applyTenetEdit(ctx, tenet, { open_unknowns: unknowns });
          ctx.print(`  ✓ added open unknown question to tenet "${tenet.name}"`, "success");
        } else {
          if (lower.includes("hypothesis") || lower.includes("invariant") || lower.includes("assertion") || lower.includes("rule")) {
            const stmt = body.replace(/^(please\s+)?(add|create|make)\s+(a\s+)?(new\s+)?(hypothesis|invariant|rule|claim)\s+(that|testing|to\s+test)?\s*/i, "").trim();
            let newClaimId = `c_${Math.random().toString(16).slice(2, 10)}`;
            if (ctx.wsApi) {
              try {
                const created = await ctx.wsApi.createClaim(tenet.id, {
                  statement: stmt,
                  test_explanation: `Verifies rule for ${tenet.name}`,
                  test_implementation: `INVOKE entry point. ASSERT: ${stmt}`,
                  confidence: 0.8,
                });
                newClaimId = created.id;
              } catch {}
            }
            if (ctx.updateTree) {
              ctx.updateTree((prev) => {
                const newC = {
                  id: newClaimId,
                  tenet_id: tenet.id,
                  status: "hypothesis" as const,
                  verification: null,
                  confidence: 0.8,
                  proposed: false,
                  flags: [],
                  version: 1,
                  statement: stmt,
                  test_explanation: `Verifies rule for ${tenet.name}`,
                  test_implementation: `INVOKE entry point. ASSERT: ${stmt}`,
                  dependencies: [],
                  content_hash: newClaimId,
                  provenance: { via: "manual" },
                  result: { verdict: "untested" as const, flaky: false, runs: 0, last_run_at: null },
                };
                return {
                  ...prev,
                  tenets: prev.tenets.map((t) => (t.id === tenet.id ? { ...t, claims: [...t.claims, newClaimId], hypotheses: t.hypotheses + 1 } : t)),
                  claims: { ...prev.claims, [newClaimId]: newC },
                };
              });
            }
            ctx.print(`  ✓ added Hypothesis ${newClaimId} to Tenet "${tenet.name}":`, "success");
            ctx.print(`    "${stmt}"`);
            await ctx.sync();
            ctx.openClaim(newClaimId);
            return;
          }

          await applyTenetEdit(ctx, tenet, { functionality: body });
          ctx.print(`  ✓ updated functionality for tenet "${tenet.name}": "${body}"`, "success");
        }

        await ctx.sync();
        ctx.selectTenet(tenet.id);
        return;
      }

      if (targetType === "node") {
        const node = ctx.index?.nodes.get(targetId);
        if (!node) {
          ctx.print(`  node not found: ${targetId}`, "error");
          return;
        }

        const lower = body.toLowerCase();
        if (lower.startsWith("summary:") || lower.startsWith("intent:")) {
          node.intent_summary = body.replace(/^(summary|intent):\s*/i, "").trim();
          ctx.print(`  ✓ updated intent summary for ${node.node_id}`, "success");
        } else if (lower.startsWith("add invariant:") || lower.startsWith("invariant:")) {
          const invStr = body.replace(/^(add\s+)?invariant:\s*/i, "").trim();
          node.business_invariants.push(invStr);
          ctx.print(`  ✓ added business invariant to ${node.node_id}: "${invStr}"`, "success");
        } else if (lower.startsWith("name:")) {
          node.name = body.replace(/^name:\s*/i, "").trim();
          ctx.print(`  ✓ updated node name to "${node.name}"`, "success");
        } else {
          node.intent_summary = body;
          ctx.print(`  ✓ updated intent summary for ${node.node_id}`, "success");
        }

        try {
          await fetch("/api/graph/nodes", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(node),
          });
        } catch {}

        await ctx.sync();
        ctx.select(node.node_id);
        return;
      }
    },
  },
  {
    name: "query",
    aliases: ["q", "retrieve"],
    usage: "query <text>",
    summary: "retrieve the relevant intent subgraph",
    async run(args, ctx) {
      const q = args.join(" ");
      if (!q) return ctx.print(`  usage: ${this.usage}`, "muted");
      const f = await ctx.query(q);
      if (!f || !f.nodeIds.size) return ctx.print("  no codebase nodes matched", "error");
      printFocus(ctx, f);
    },
  },
  {
    name: "invariants",
    aliases: ["inv"],
    usage: "invariants [node]",
    summary: "list business invariants (all, or one node)",
    run(args, ctx) {
      const index = ctx.index!;
      const ids = args.length ? [needNode(ctx, args.join(" "), this.usage)].filter(Boolean) as string[] : [...index.nodes.keys()];
      let count = 0;
      for (const id of ids) {
        for (const s of index.nodes.get(id)!.business_invariants) ctx.print(`  ${id} → ${s}`), count++;
      }
      ctx.print(`  ${count} invariant${count === 1 ? "" : "s"}`, "muted");
    },
  },
  {
    name: "deps",
    aliases: ["downstream"],
    usage: "deps <node>",
    summary: "everything a node depends on (transitive)",
    run(args, ctx) {
      const id = needNode(ctx, args.join(" "), this.usage);
      if (!id) return;
      const ids = reachable(ctx.index!, id, "out");
      ctx.setFocus(focusFromIds(ctx.index!, [id, ...ids], "downstream", `deps ${id}`));
      ctx.print(ids.length ? ids.map((d) => `  ├─ ${d}`) : ["  terminal boundary (no dependencies)"]);
    },
  },
  {
    name: "impact",
    aliases: ["upstream", "rdeps"],
    usage: "impact <node>",
    summary: "everything that breaks if this node changes",
    run(args, ctx) {
      const id = needNode(ctx, args.join(" "), this.usage);
      if (!id) return;
      const ids = reachable(ctx.index!, id, "in");
      ctx.setFocus(focusFromIds(ctx.index!, [id, ...ids], "upstream", `impact ${id}`));
      ctx.print(ids.length ? ids.map((d) => `  ├─ ${d}`) : ["  nothing depends on this node"]);
      ctx.print(`  blast radius: ${ids.length} node${ids.length === 1 ? "" : "s"}`, "muted");
    },
  },
  {
    name: "path",
    usage: "path <from> <to>",
    summary: "shortest dependency path between two nodes",
    run(args, ctx) {
      if (args.length < 2) return ctx.print(`  usage: ${this.usage}`, "muted");
      const a = needNode(ctx, args[0], this.usage);
      const b = a && needNode(ctx, args[1], this.usage);
      if (!a || !b) return;
      const p = shortestPath(ctx.index!, a, b);
      if (!p) return ctx.print(`  no path between ${a} and ${b}`, "error");
      ctx.setFocus(focusFromIds(ctx.index!, p, "path", `path ${a} → ${b}`, true));
      ctx.print(`  ${p.join(" → ")}`, "accent");
    },
  },
  {
    name: "ls",
    aliases: ["boundaries"],
    usage: "ls [boundary]",
    summary: "list nodes grouped by boundary",
    run(args, ctx) {
      const groups = new Map<string, string[]>();
      for (const n of ctx.index!.nodes.values()) {
        const b = boundaryOf(n);
        if (args[0] && !b.includes(args[0])) continue;
        groups.set(b, [...(groups.get(b) ?? []), n.node_id]);
      }
      for (const [b, ids] of groups) ctx.print([`  ${b}/`, ...ids.map((id) => `    ${id}`)]);
      if (!groups.size) ctx.print("  no matching boundary", "error");
    },
  },
  {
    name: "context",
    usage: "context",
    summary: "print the LLM context for the current focus",
    run(_a, ctx) {
      if (!ctx.focus) return ctx.print("  nothing focused — run a query or click a node", "muted");
      ctx.print(ctx.focus.context.split("\n").map((l) => `  ${l}`), "plain");
      ctx.print(`  ~${ctx.focus.tokens} tokens`, "success");
    },
  },
  {
    name: "tests",
    usage: "tests [tenet|node]",
    summary: "generate invariant tests for an intent tenet or node",
    async run(args, ctx) {
      const term = args.join(" ").trim();
      const target = term || ctx.selection.target_id || ctx.selection.tenet_id || "";
      if (!target) {
        return ctx.print(`  usage: ${this.usage}`, "muted");
      }

      // Check if target is or matches an Intent Tenet
      const tenetId = resolveTenet(ctx.tenets, target);
      if (tenetId && ctx.tenets) {
        const t = ctx.tenets.tenets.find((x) => x.id === tenetId);
        if (t) {
          const clms = t.claims.map((cid) => ctx.tenets!.claims[cid]).filter(Boolean);
          ctx.print([
            "",
            `⚡ Generating invariant tests for Intent Tenet: "${t.name}" (${t.id})`,
            `  Functionality: ${t.functionality || "(none)"}`,
            `  Covering ${clms.length} invariant claim(s)...`,
          ], "prompt");

          if (!clms.length) {
            ctx.print("  (no claims/invariants defined yet for this tenet; define claims in the Tenet Inspector first)", "muted");
          } else {
            clms.forEach((c) => {
              ctx.print([
                `  ✓ test_${c.id}_invariant_enforced:`,
                `    rule: "${c.statement}"`,
                c.test_implementation ? `    recipe: ${c.test_implementation.split("\n")[0]}` : null,
              ].filter(Boolean) as string[], "success");
            });
          }

          const linkedNodes = graphNodesFor(ctx.index, ctx.tenets, t.id);
          if (linkedNodes.length && ctx.source.generateTests) {
            ctx.print(`  synthesizing deterministic test suite for linked code (${linkedNodes.map((n) => n.name).join(", ")})...`, "muted");
            try {
              for (const node of linkedNodes.slice(0, 2)) {
                const res = await ctx.source.generateTests(ctx.repo, node.id);
                res.tests.forEach((st) => ctx.print(`    ✓ synthesized pytest: ${st.name}`, "success"));
              }
            } catch (e: any) {
              ctx.print(`    (test generator note: ${e.message || e})`, "muted");
            }
          }
          return;
        }
      }

      // Fallback: codebase node
      const id = needNode(ctx, target, this.usage);
      if (!id) return;
      if (!ctx.source.generateTests) {
        const n = ctx.index!.nodes.get(id)!.business_invariants.length;
        return ctx.print(`  test generator not connected · would send ${n} invariant${n === 1 ? "" : "s"} from ${id}`, "muted");
      }
      ctx.print("  generating from invariants…", "muted");
      const res = await ctx.source.generateTests(ctx.repo, id);
      res.tests.forEach((t) => ctx.print(`  ✓ ${t.name}`, "success"));
    },
  },
  {
    name: "reset",
    aliases: ["unfocus"],
    usage: "reset",
    summary: "clear selection and highlight",
    run(_a, ctx) {
      ctx.select(null);
      ctx.setFocus(null);
    },
  },
  {
    name: "fit",
    usage: "fit",
    summary: "fit the graph to the screen",
    run(_a, ctx) {
      ctx.fit();
    },
  },
  {
    name: "view",
    aliases: ["tab", "switch"],
    usage: "view [graph|tenets]",
    summary: "switch between the codebase graph and the axiom/tenet hierarchy",
    offline: true,
    run(args, ctx) {
      const a = (args[0] ?? "").toLowerCase();
      let next: "graph" | "tenets" | null = null;
      if (!a) next = ctx.view === "graph" ? "tenets" : "graph";
      else if (/^[tah]/.test(a)) next = "tenets";
      else if (/^[gc]/.test(a)) next = "graph";
      if (!next) return ctx.print(`  usage: ${this.usage}`, "muted");
      ctx.setView(next);
      ctx.print(`  ✓ showing ${next === "graph" ? "codebase graph" : "axiom / tenet hierarchy"}`, "success");
    },
  },
  {
    name: "tenets",
    aliases: ["axioms", "tree"],
    usage: "tenets",
    summary: "list the tenet hierarchy with axiom/hypothesis counts",
    offline: true,
    run(_a, ctx) {
      const t = ctx.tenets;
      if (!t) return ctx.print("  tenet tree not loaded (open the tenet view, and sign in for live data)", "error");
      const byId = new Map(t.tenets.map((x) => [x.id, x]));
      const lines: string[] = [];
      const walk = (id: string, depth: number) => {
        const x = byId.get(id);
        if (!x) return;
        const flag = x.flagged_axioms ? `  ⚑${x.flagged_axioms}` : "";
        lines.push(`  ${"  ".repeat(depth)}${depth ? "├─ " : ""}${x.name}  ${x.axioms}A·${x.hypotheses}H  ${x.rollup}${flag}`);
        x.children.forEach((c) => walk(c, depth + 1));
      };
      if (t.root_id) walk(t.root_id, 0);
      ctx.print(lines.length ? lines : ["  no tenets yet"]);
    },
  },
  {
    name: "tenet",
    aliases: ["axiom"],
    usage: "tenet <name>",
    summary: "open a tenet and print its axioms and hypotheses",
    offline: true,
    run(args, ctx) {
      const t = ctx.tenets;
      if (!t) return ctx.print("  tenet tree not loaded", "error");
      const id = resolveTenet(t, args.join(" "));
      if (!id) return ctx.print(args.length ? `  tenet not found: ${args.join(" ")}` : `  usage: ${this.usage}`, args.length ? "error" : "muted");
      const x = t.tenets.find((y) => y.id === id)!;
      ctx.setView("tenets");
      ctx.selectTenet(id);
      ctx.print([`  ${x.name} · level ${x.level} · ${x.rollup}`, `  ${x.functionality || "no functionality statement"}`]);
      for (const cid of x.claims) {
        const c = t.claims[cid];
        if (c) ctx.print(`  ${c.status === "axiom" ? "◆ A" : "· H"} [${c.result.verdict}] ${c.statement}`, c.status === "axiom" ? "accent" : "plain");
      }
    },
  },
  {
    name: "claim",
    aliases: ["hypothesis"],
    usage: "claim <id>",
    summary: "open an axiom or hypothesis with its recipe and verification",
    offline: true,
    run(args, ctx) {
      const t = ctx.tenets;
      if (!t) return ctx.print("  tenet tree not loaded", "error");
      const q = args.join(" ").trim().toLowerCase();
      if (!q) return ctx.print(`  usage: ${this.usage}`, "muted");
      const c = t.claims[args[0]] ?? Object.values(t.claims).find((x) => x.id.toLowerCase().includes(q) || x.statement.toLowerCase().includes(q));
      if (!c) return ctx.print(`  claim not found: ${args.join(" ")}`, "error");
      ctx.openClaim(c.id);
      ctx.print([`  ${c.status === "axiom" ? "◆ axiom" : "◇ hypothesis"} ${c.id} · ${c.result.verdict} · ${Math.round(c.confidence * 100)}%`, `  ${c.statement}`]);
    },
  },
  {
    name: "sync",
    aliases: ["ingest"],
    usage: "sync",
    summary: "re-ingest the repository",
    offline: true,
    async run(_a, ctx) {
      ctx.print(`  syncing ${ctx.repo} via ${ctx.source.label}…`, "muted");
      await ctx.sync();
    },
  },
  {
    name: "export",
    aliases: ["push-intent"],
    usage: "export",
    summary: "export .intentflow files to github branch (intentflow/intents)",
    async run(_a, ctx) {
      if (!ctx.wsApi) {
        ctx.print("  ✗ Cannot export: no workspace connection (sign in and connect a repository first)", "error");
        return;
      }
      ctx.print(`  committing intent files to ${ctx.repo}...`, "muted");
      try {
        const res = await ctx.wsApi.exportFolder();
        if (res.changed) {
          ctx.print([
            `  ✓ successfully exported ${res.files} intent files to branch: ${res.branch}`,
            `  commit: ${res.commit_sha.slice(0, 7)}`,
          ], "success");
        } else {
          ctx.print([
            `  ✓ nothing changed since last export (${res.branch})`,
            `  latest commit: ${res.commit_sha.slice(0, 7)}`,
          ], "muted");
        }
      } catch (e: any) {
        ctx.print(`  ✗ export failed: ${e.message || e}`, "error");
      }
    },
  },
  {
    name: "grill",
    aliases: ["interview", "questions"],
    usage: "grill [start|answer <text>|skip]",
    summary: "interactive tenet grilling interview to define and refine invariants",
    offline: true,
    async run(args, ctx) {
      const sub = (args[0] ?? "").toLowerCase();
      const repoUrl = `/api/repos/${ctx.repo}`;

      if (sub === "answer" || sub === "ans") {
        const text = args.slice(1).join(" ").trim();
        if (!text) return ctx.print("  usage: grill answer <A|B|C or custom requirement>", "muted");
        ctx.print(`  recording answer: "${text}"…`, "muted");
        try {
          const res = await fetch(`${repoUrl}/grill/answer`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ answer: text }),
          }).then((r) => r.json());

          if (res.error) return ctx.print(`  grill error: ${res.error}`, "error");

          ctx.print(`  ✓ recorded: "${res.recorded_answer}" for ${res.tenet_name}`, "success");
          if (res.candidate_invariant) {
            ctx.print(`  + synthesized invariant: ${res.candidate_invariant}`, "accent");
          }
          if (res.next_question) {
            const nq = res.next_question;
            ctx.print([
              `  --- Next Question (${res.answered_count + 1}/${res.total_questions}) ---`,
              `  ${nq.text}`,
              `  Why: ${nq.why}`,
              ...(nq.options ?? []).map((o: string, i: number) => `    [${String.fromCharCode(65 + i)}] ${o}`),
              `  To answer: type "grill answer <A|B|C or requirement>" or chat directly`,
            ]);
          } else {
            ctx.print(`  🎉 Grilling complete for ${res.tenet_name}! Run "tenets" to inspect the hierarchy.`, "success");
          }
          await ctx.sync();
        } catch (e) {
          ctx.print(`  grill error: ${e instanceof Error ? e.message : String(e)}`, "error");
        }
        return;
      }

      if (sub === "skip") {
        ctx.print("  skipping current question…", "muted");
        try {
          const res = await fetch(`${repoUrl}/grill/answer`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ answer: "[SKIPPED]", dont_know: true }),
          }).then((r) => r.json());
          if (res.next_question) {
            const nq = res.next_question;
            ctx.print([
              `  Next Question (${res.answered_count + 1}/${res.total_questions}): ${nq.text}`,
              ...(nq.options ?? []).map((o: string, i: number) => `    [${String.fromCharCode(65 + i)}] ${o}`),
            ]);
          } else {
            ctx.print("  grilling complete for this tenet.", "success");
          }
        } catch (e) {
          ctx.print(`  grill error: ${e instanceof Error ? e.message : String(e)}`, "error");
        }
        return;
      }

      if (sub === "start") {
        ctx.print(`  starting tenet grilling for ${ctx.repo}…`, "muted");
        try {
          const res = await fetch(`${repoUrl}/grill/start`, { method: "POST" }).then((r) => r.json());
          if (res.questions && res.questions[0]) {
            const q = res.questions[0];
            ctx.print([
              `  🔥 Tenet Grilling Session Started: ${res.tenet_name ?? "System"}`,
              `  Question 1/${res.questions.length}:`,
              `  ${q.text}`,
              `  Why: ${q.why}`,
              ...(q.options ?? []).map((o: string, i: number) => `    [${String.fromCharCode(65 + i)}] ${o}`),
              `  To answer: type "grill answer <A|B|C or text>" or chat directly`,
            ]);
          }
        } catch (e) {
          ctx.print(`  grill error: ${e instanceof Error ? e.message : String(e)}`, "error");
        }
        return;
      }

      // Default: fetch current status
      try {
        const res = await fetch(`${repoUrl}/grill`).then((r) => r.json());
        if (!res.active || !res.current_question) {
          ctx.print([
            `  ${res.message || "No active questions."}`,
            '  Type "grill start" to start an interactive tenet grilling session.',
          ]);
          return;
        }
        const q = res.current_question;
        ctx.print([
          `  🔥 Tenet Grilling Active: ${res.tenet_name} (Question ${res.answered_count + 1}/${res.total_questions})`,
          `  ${q.text}`,
          `  Why: ${q.why}`,
          ...(q.options ?? []).map((o: string, i: number) => `    [${String.fromCharCode(65 + i)}] ${o}`),
          `  To answer: type "grill answer <choice or requirement>" or chat directly`,
        ]);
      } catch (e) {
        ctx.print(`  grill error: ${e instanceof Error ? e.message : String(e)}`, "error");
      }
    },
  },
  {
    name: "hypothesize",
    usage: "hypothesize [count] [focus]",
    summary: "draft new unverified hypotheses for the selected tenet",
    offline: false,
    async run(args, ctx, raw) {
      if (!ctx.selection.tenet_id) {
        ctx.print("  Click a tenet node in the Tenets view, then ask me again.", "error");
        ctx.print("  [Open Tenets view]", "accent");
        return;
      }
      if (!ctx.source.ask) {
        ctx.print("  agent not connected", "error");
        return;
      }
      ctx.print("  generating hypotheses…", "muted");
      try {
        const reply = await ctx.source.ask(ctx.repo, raw || "/hypothesize", JSON.stringify(ctx.selection));
        ctx.print(reply.answer.split("\n").map((l) => `  ${l}`));
        if (ctx.sync) await ctx.sync();
      } catch (e) {
        ctx.print(`  hypothesis error: ${e instanceof Error ? e.message : String(e)}`, "error");
      }
    },
  },
  {
    name: "hypotheses",
    usage: "hypotheses [tenet]",
    summary: "list open hypotheses for the selected or specified tenet",
    offline: true,
    run(args, ctx) {
      const tid = args[0] || ctx.selection.tenet_id;
      if (!tid || !ctx.tenets) {
        ctx.print("  select a tenet first or specify tenet id", "error");
        return;
      }
      const t = ctx.tenets.tenets.find((x) => x.id === tid);
      if (!t) {
        ctx.print(`  tenet ${tid} not found`, "error");
        return;
      }
      const hyp = t.claims
        .map((cid) => ctx.tenets?.claims[cid])
        .filter((c) => c && c.status === "hypothesis");
      ctx.print([`  ${t.name} (${t.id}) — ${hyp.length} open hypotheses:`, ...hyp.map((h) => `    [${h!.id}] ${h!.statement}`)]);
    },
  },
  {
    name: "ask",
    usage: "ask <question>",
    summary: "forced read-only query bypassing generation router",
    offline: false,
    async run(args, ctx, raw) {
      if (!args.length) {
        ctx.print("  usage: ask <question>", "error");
        return;
      }
      if (!ctx.source.ask) {
        ctx.print("  agent not connected", "error");
        return;
      }
      ctx.print("  querying codebase…", "muted");
      try {
        const reply = await ctx.source.ask(ctx.repo, raw, JSON.stringify(ctx.selection));
        ctx.print(reply.answer.split("\n").map((l) => `  ${l}`));
      } catch (e) {
        ctx.print(`  query error: ${e instanceof Error ? e.message : String(e)}`, "error");
      }
    },
  },
  {
    name: "clear",
    usage: "clear",
    summary: "clear the terminal",
    offline: true,
    run(_a, ctx) {
      ctx.clear();
    },
  },
];

const byName = new Map(commands.flatMap((c) => [c.name, ...(c.aliases ?? [])].map((n) => [n, c] as const)));

/** Parses and executes one line. Unknown multi-word input → question. */
export async function execute(raw: string, ctx: CommandContext): Promise<void> {
  const [verb = "", ...args] = raw.trim().split(/\s+/);
  const vLower = verb.toLowerCase();
  const vNorm = vLower.replace(/^[\/]/, "").replace(/:$/, "");
  const cmd = byName.get(vLower) ?? byName.get(vNorm) ?? byName.get(`/${vNorm}`);

  if (cmd) {
    if (!cmd.offline && !ctx.index) return ctx.print("  graph not loaded yet", "error");
    try {
      await cmd.run(args, ctx, raw);
    } catch (e) {
      ctx.print(`  ${verb}: ${e instanceof Error ? e.message : String(e)}`, "error");
    }
    return;
  }

  const isChoiceOrGrill =
    ["a", "b", "c", "1", "2", "3", "option", "choice", "answer"].includes(vLower) ||
    vLower.startsWith("option") ||
    vLower.startsWith("[") ||
    vLower.startsWith("(");

  if (args.length === 0 && !raw.endsWith("?") && !isChoiceOrGrill) {
    return ctx.print(`  command not found: ${verb}. Type "help" for available commands.`, "error");
  }

  // Natural-language question or grilling reply
  let f: Focus | null = null;
  // Bypass client-side BM25 for workspace-backed / live sessions (server owns retrieval)
  if (ctx.index && ctx.source.kind === "mock") {
    try {
      f = await ctx.query(raw);
    } catch {
      /* ignore retrieval errors */
    }
  }

  if (f && f.nodeIds.size > 0) {
    printFocus(ctx, f);
  }

  if (!ctx.source.ask) {
    if (!f || !f.nodeIds.size) {
      return ctx.print("  no codebase nodes matched that question and agent not connected", "error");
    }
    ctx.print("  agent not connected · context is ready (run `context` to view it)", "muted");
    return;
  }

  try {
    ctx.print("  asking agent…", "muted");
    const contextPayload = f?.context ? `[UI SELECTION] ${JSON.stringify(ctx.selection)}\n${f.context}` : `[UI SELECTION] ${JSON.stringify(ctx.selection)}`;
    const reply = await ctx.source.ask(ctx.repo, raw, contextPayload);
    ctx.print(reply.answer.split("\n").map((l) => `  ${l}`));
    if (reply.answer.includes("Answer Recorded") || reply.answer.includes("Grilling Complete")) {
      await ctx.sync();
    }
  } catch (e) {
    ctx.print(`  agent error: ${e instanceof Error ? e.message : String(e)}`, "error");
  }
}

/** Tab completion: command names for the first word, node ids for later ones. */
export function complete(input: string, index: GraphIndex | null): { value: string; options: string[] } {
  const parts = input.split(/\s+/);
  const last = parts[parts.length - 1] ?? "";
  const pool =
    parts.length <= 1
      ? [...byName.keys()]
      : index
        ? [...index.nodes.keys()]
        : [];
  const options = pool.filter((p) => p.startsWith(last.toLowerCase())).sort();
  if (options.length === 0) return { value: input, options: [] };
  let prefix = options[0];
  for (const o of options) while (!o.startsWith(prefix)) prefix = prefix.slice(0, -1);
  const value = [...parts.slice(0, -1), options.length === 1 ? prefix + (parts.length <= 1 ? " " : "") : prefix].join(" ");
  return { value, options: options.length === 1 ? [] : options };
}
