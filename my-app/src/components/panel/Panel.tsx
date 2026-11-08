"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";

export interface PanelTab {
  id: string;
  label: string;
  /** small count shown beside the label */
  count?: number | string;
  /** tint the count (something needs attention) */
  alert?: boolean;
}

interface Props {
  label: string;
  tone?: "node" | "tenet";
  eyebrow: ReactNode;
  title: string;
  /** line under the title: path, breadcrumbs, id chip */
  sub?: ReactNode;
  tabs: PanelTab[];
  tab: string;
  onTab(id: string): void;
  onClose(): void;
  /** left/right stepper in the header (codebase view) */
  step?: { onPrev(): void; onNext(): void; position: string };
  footer?: ReactNode;
  children: ReactNode;
}

/**
 * The shell shared by the codebase and tenet panels: a fixed header (what am I looking at),
 * a tab strip (what do I want to know), a scrolling body, and a pinned action footer.
 * Esc closes, ←/→ move along the tab strip, and the body re-animates when the tab changes.
 */
export function Panel({ label, tone = "node", eyebrow, title, sub, tabs, tab, onTab, onClose, step, footer, children }: Props) {
  const uid = useId();
  const root = useRef<HTMLElement>(null);

  useEffect(() => {
    function key(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      if (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return;
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);

  function tabKey(e: React.KeyboardEvent) {
    const i = tabs.findIndex((t) => t.id === tab);
    const next = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : null;
    if (next === null) return;
    e.preventDefault();
    const to = tabs[(next + tabs.length) % tabs.length];
    onTab(to.id);
    root.current?.querySelector<HTMLElement>(`[data-tab="${to.id}"]`)?.focus();
  }

  return (
    <aside ref={root} className={`pn pn-${tone}`} aria-label={label}>
      <header className="pn-head">
        <div className="pn-top">
          <span className="pn-eyebrow">{eyebrow}</span>
          <span className="pn-top-actions">
            {step ? (
              <span className="pn-step" role="group" aria-label="Step through nodes">
                <button onClick={step.onPrev} aria-label="Previous node" title="Previous node">‹</button>
                <small>{step.position}</small>
                <button onClick={step.onNext} aria-label="Next node" title="Next node">›</button>
              </span>
            ) : null}
            <button className="pn-close" onClick={onClose} aria-label="Close panel" title="Close (Esc)">×</button>
          </span>
        </div>
        <h2 className="pn-title">{title}</h2>
        {sub ? <div className="pn-sub">{sub}</div> : null}
      </header>

      <div className="pn-tabs" role="tablist" aria-label={`${label} sections`} onKeyDown={tabKey}>
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            id={`${uid}-${t.id}`}
            data-tab={t.id}
            aria-selected={tab === t.id}
            aria-controls={`${uid}-body`}
            tabIndex={tab === t.id ? 0 : -1}
            className={tab === t.id ? "on" : ""}
            onClick={() => onTab(t.id)}
          >
            {t.label}
            {t.count !== undefined ? <em className={t.alert ? "alert" : ""}>{t.count}</em> : null}
          </button>
        ))}
      </div>

      <div className="pn-body" role="tabpanel" id={`${uid}-body`} aria-labelledby={`${uid}-${tab}`} key={tab}>
        {children}
      </div>

      {footer ? <footer className="pn-foot">{footer}</footer> : null}
    </aside>
  );
}

/** A labelled block inside a tab. */
export function Block({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="pn-block">
      <h3>
        {title}
        {aside ? <small>{aside}</small> : null}
      </h3>
      {children}
    </section>
  );
}

/** A click-to-copy mono chip (paths, ids). */
export function CopyChip({ text, children }: { text: string; children?: ReactNode }) {
  const ref = useRef<HTMLButtonElement>(null);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      const el = ref.current;
      if (!el) return;
      el.dataset.copied = "1";
      setTimeout(() => el && delete el.dataset.copied, 1100);
    } catch {
      /* clipboard blocked */
    }
  }
  return (
    <button ref={ref} className="pn-copy" onClick={() => void copy()} title="Click to copy">
      <code>{children ?? text}</code>
      <span aria-hidden>⧉</span>
    </button>
  );
}

/** Circular progress with a hand-written centre. */
export function Ring({ value, label, sub }: { value: number; label: string; sub: string }) {
  const r = 30;
  const c = 2 * Math.PI * r;
  return (
    <div className="pn-ring" role="img" aria-label={`${label} ${sub}`}>
      <svg viewBox="0 0 72 72" width="72" height="72">
        <circle cx="36" cy="36" r={r} className="track" />
        <circle cx="36" cy="36" r={r} className="arc" strokeDasharray={c} strokeDashoffset={c * (1 - Math.max(0, Math.min(1, value)))} />
      </svg>
      <b>{label}</b>
      <small>{sub}</small>
    </div>
  );
}
