"use client";

import type { ReactNode } from "react";

/** Top bar: wordmark on the left, account controls on the right. */
export function TopBar({ right }: { right?: ReactNode }) {
  return (
    <header className="topbar">
      <a className="logo" href="/">IntentFlow</a>
      <div className="topbar-right">{right}</div>
    </header>
  );
}

/** A titled surface for logs and secondary information. */
export function Panel({ title, children, className = "" }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section className={`panel ${className}`}>
      <h2 className="panel-title">{title}</h2>
      <div className="panel-body">{children}</div>
    </section>
  );
}

/** Card with a name, an optional tag, a summary and a body. */
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
      {summary && <p className="node-summary">{summary}</p>}
      {children && <div className="node-body">{children}</div>}
    </article>
  );
}
