"use client";

import { useEffect, useRef, useState } from "react";

/** The one place that defines the words. Panels and nodes use the same labels. */
export const TERMS = {
  axiom: { glyph: "◆", name: "Axiom", state: "locked", def: "A rule a human confirmed. Tests are generated from it, and no agent may change it without your review." },
  hypothesis: { glyph: "◇", name: "Hypothesis", state: "proposed", def: "A rule the Intent Builder inferred from the code, or you wrote. It may be wrong. Edit it freely until its test passes." },
} as const;

const STEPS = ["Hypothesis", "Test recipe", "Test passes", "You promote", "Axiom"];

export function Guide() {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("pointerdown", away);
    window.addEventListener("keydown", esc);
    return () => {
      window.removeEventListener("pointerdown", away);
      window.removeEventListener("keydown", esc);
    };
  }, [open]);

  return (
    <div className="guide" ref={box}>
      <button className={`tb-ghost ${open ? "on" : ""}`} onClick={() => setOpen(!open)} aria-expanded={open} aria-haspopup="dialog">
        <b aria-hidden>?</b> Guide
      </button>
      {open ? (
        <div className="guide-pop" role="dialog" aria-label="How tenets, axioms and hypotheses work">
          <h3>How a rule becomes true</h3>
          <p>A <b>tenet</b> is one thing the system must do. Each tenet holds <b>claims</b>, and every claim is one of two kinds.</p>
          <div className="guide-cards">
            {(["axiom", "hypothesis"] as const).map((k) => (
              <div key={k} className={`guide-card ${k}`}>
                <span>{TERMS[k].glyph} {TERMS[k].name} <em>{TERMS[k].state}</em></span>
                <p>{TERMS[k].def}</p>
              </div>
            ))}
          </div>
          <ol className="guide-steps" aria-label="Lifecycle of a claim">
            {STEPS.map((s, i) => (
              <li key={s} style={{ ["--i" as string]: i }} className={i === STEPS.length - 1 ? "end" : ""}>{s}</li>
            ))}
          </ol>
          <p className="guide-keys"><span>✓ pass</span><span>✗ fail</span><span>↻ stale</span><span>? unsure</span><span>· never run</span></p>
        </div>
      ) : null}
    </div>
  );
}
