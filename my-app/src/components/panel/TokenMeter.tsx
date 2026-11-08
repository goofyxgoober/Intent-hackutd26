"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { GraphIndex } from "@/lib/graph/model";
import type { Focus } from "@/lib/focus";

/** Assumed cost of shipping one whole source file when the backend gave no `meta.raw_tokens`. */
const EST_TOKENS_PER_FILE = 1800;

/** Ease a number toward its target so the meter counts instead of jumping. */
function useTween(target: number) {
  const [v, setV] = useState(target);
  const from = useRef(target);
  useEffect(() => {
    const start = from.current;
    const t0 = performance.now();
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / 450);
      const next = start + (target - start) * (1 - Math.pow(1 - k, 3));
      from.current = next;
      setV(next);
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target]);
  return Math.round(v);
}

const fmt = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));

/** Raw-code RAG versus Intent-graph RAG for the current focus (CONTEXT.md §7). */
export function TokenMeter({ index, focus }: { index: GraphIndex; focus: Focus }) {
  const { raw, estimated } = useMemo(() => {
    const files = new Map<string, number | undefined>();
    for (const id of focus.nodeIds) {
      const n = index.nodes.get(id);
      if (!n) continue;
      const have = n.meta?.raw_tokens;
      files.set(n.source_file, (files.get(n.source_file) ?? 0) + (have ?? 0) || undefined);
    }
    let total = 0;
    let est = false;
    for (const v of files.values()) {
      if (v) total += v;
      else {
        total += EST_TOKENS_PER_FILE;
        est = true;
      }
    }
    return { raw: total, estimated: est };
  }, [index, focus]);

  const intent = focus.tokens;
  const saved = raw > 0 ? Math.max(0, Math.round((1 - intent / raw) * 100)) : 0;
  const rawShown = useTween(raw);
  const intentShown = useTween(intent);
  const savedShown = useTween(saved);

  return (
    <span className="meter" title={`Raw files${estimated ? " (estimated)" : ""} versus the intent slice for ${focus.nodeIds.size} node${focus.nodeIds.size === 1 ? "" : "s"}`}>
      <span className="m-row"><small>raw code</small><i><u style={{ width: "100%" }} /></i><b>{estimated ? "≈" : ""}{fmt(rawShown)}</b></span>
      <span className="m-row intent"><small>intent</small><i><u style={{ width: `${raw ? Math.max(3, (intent / raw) * 100) : 100}%` }} /></i><b>{fmt(intentShown)}</b></span>
      <strong className="m-save">−{savedShown}%</strong>
    </span>
  );
}
