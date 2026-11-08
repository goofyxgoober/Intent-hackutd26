import type { GraphIndex } from "@/lib/graph/model";
import { boundaryOf, reachable, shortestPath } from "@/lib/graph/model";
import type { GraphSource } from "@/lib/api/source";
import type { RetrievalOptions } from "@/lib/retrieval/engine";
import { focusFromIds, type Focus } from "@/lib/focus";
import type { TreeView } from "@/gh/intentApi";
import { resolveTenet } from "@/lib/tenetLinks";

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
  selection: { view: "intent" | "codebase"; tenet_id: string | null; claim_id: string | null; file: string | null };
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
  ctx.print(`  ✓ ${f.nodeIds.size} intent nodes · ~${f.tokens} context tokens${f.elapsedMs !== undefined ? ` · ${f.elapsedMs.toFixed(1)}ms` : ""}`, "success");
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
    usage: "inspect <node>",
    summary: "open a node and retrieve its neighborhood",
    run(args, ctx) {
      const id = needNode(ctx, args.join(" "), this.usage);
      if (!id) return;
      const n = ctx.index!.nodes.get(id)!;
      ctx.select(id);
      ctx.print([`  ${n.name} · ${n.source_file}`, `  ${n.intent_summary}`]);
      n.business_invariants.forEach((s, i) => ctx.print(`  ${inv(i)}: ${s}`));
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
      if (!f || !f.nodeIds.size) return ctx.print("  no intent nodes matched", "error");
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
    usage: "tests <node>",
    summary: "generate invariant tests for a node",
    async run(args, ctx) {
      const id = needNode(ctx, args.join(" "), this.usage);
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
  const cmd = byName.get(verb.toLowerCase());

  if (cmd) {
    if (!cmd.offline && !ctx.index) return ctx.print("  graph not loaded yet", "error");
    try {
      await cmd.run(args, ctx, raw);
    } catch (e) {
      ctx.print(`  ${verb}: ${e instanceof Error ? e.message : String(e)}`, "error");
    }
    return;
  }

  if (args.length === 0 && !raw.endsWith("?")) {
    return ctx.print(`  command not found: ${verb}. Type "help" for available commands.`, "error");
  }

  // Natural-language question
  if (!ctx.index) return ctx.print("  graph not loaded yet", "error");
  const f = await ctx.query(raw);
  if (!f || !f.nodeIds.size) return ctx.print("  no intent nodes matched that question", "error");
  printFocus(ctx, f);
  if (!ctx.source.ask) {
    ctx.print("  agent not connected · context is ready (run `context` to view it)", "muted");
    return;
  }
  try {
    ctx.print("  asking agent…", "muted");
    const reply = await ctx.source.ask(ctx.repo, raw, `[UI SELECTION] ${JSON.stringify(ctx.selection)}\n${f.context}`);
    ctx.print(reply.answer.split("\n").map((l) => `  ${l}`));
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
