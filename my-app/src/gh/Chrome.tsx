"use client";

import type { ReactNode } from "react";

/** Top bar: "8090 / INTENTFLOW  legacy-monolith → functional intent map". */
export function TopBar({ right }: { right?: ReactNode }) {
  return (
    <header className="topbar">
      <div className="topbar-left">
        <span className="logo">8090</span>
        <span className="slash">/</span>
        <span className="product">INTENTFLOW</span>
        <span className="crumb">
          legacy-monolith <span className="arrow">→</span> <b>functional intent map</b>
        </span>
      </div>
      <div className="topbar-right">{right}</div>
    </header>
  );
}

/** Pipeline breadcrumb: 01 → 02 → 03, with the active stage in purple. */
export function Stages({ active }: { active: 1 | 2 | 3 }) {
  const stages = ["raw ast tangle", "functional intent graph", "modern branch merge"];
  return (
    <nav className="stages hand">
      {stages.map((s, i) => (
        <span key={s} className="stage-wrap">
          {i > 0 && <span className="stage-arrow">→</span>}
          <span className={i + 1 === active ? "stage active" : "stage"}>
            0{i + 1}. {s}
          </span>
        </span>
      ))}
    </nav>
  );
}

/** Footer status bar crediting each subsystem. */
export function StatusBar({ sync }: { sync: string }) {
  return (
    <footer className="statusbar">
      <div>
        <span className="dim">annotation:</span> LLM, two-pass (Indra)
        <span className="sep">·</span>
        <span className="dim">import edges:</span> pattern matching
        <span className="sep">·</span>
        <span className="dim">views:</span> Vishjit
        <span className="sep">·</span>
        <span className="dim">github sync:</span> {sync}
      </div>
      <div className="hand quote">“142 files distilled into 8 functional invariant boundaries”</div>
    </footer>
  );
}

/** Konsole-style window with traffic lights. */
export function Terminal({
  title = "~ : zsh — Konsole (Nemotron 70B RAG)",
  children,
  footer,
  className = "",
}: {
  title?: string;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`terminal ${className}`}>
      <div className="terminal-bar">
        <span className="dots">
          <i className="r" />
          <i className="y" />
          <i className="g" />
        </span>
        <span className="terminal-title">{title}</span>
        <span className="chev">⌄</span>
      </div>
      <div className="terminal-body">{children}</div>
      {footer && <div className="terminal-foot">{footer}</div>}
    </section>
  );
}

/** Intent node card: mono title, path tag, handwritten summary, mono details. */
export function NodeCard({
  name,
  tag,
  tagTone,
  summary,
  children,
  className = "",
}: {
  name: string;
  tag?: ReactNode;
  tagTone?: "ok" | "muted" | "warn";
  summary?: string;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <article className={`node ${className}`}>
      <div className="node-head">
        <span className="node-name">{name}</span>
        {tag && <span className={`node-tag ${tagTone ?? ""}`}>{tag}</span>}
      </div>
      {summary && <p className="node-summary hand">{summary}</p>}
      {children && <div className="node-body">{children}</div>}
    </article>
  );
}

export const PROMPT = "ayaan@intentflow:~$";
