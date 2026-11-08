"use client";

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type PointerEvent as RPointerEvent, type ReactNode } from "react";
import type { Line } from "@/lib/terminal/commands";

interface Props {
  lines: Line[];
  prompt: string;
  title: string;
  open: boolean;
  minimized: boolean;
  busy: boolean;
  onOpenChange(open: boolean): void;
  onMinimizedChange(min: boolean): void;
  onSubmit(raw: string): void;
  inputRef: React.RefObject<HTMLInputElement | null>;
  selectedTenet?: { id: string; name: string } | null;
  onClearSelectedTenet?(): void;
  onFocusFile?(path: string, range?: string): void;
  onFocusTenet?(tenetId: string): void;
  onFocusClaim?(claimId: string): void;
  onOpenTenetsView?(): void;
  progressStatus?: string | null;
}

const CITATION_REGEX = /\[\[(file|tenet|claim):([^\]\s]+?)(?::(\d+-\d+))?\]\]/g;

export function Terminal({
  lines,
  prompt,
  title,
  open,
  minimized,
  busy,
  onOpenChange,
  onMinimizedChange,
  onSubmit,
  inputRef,
  selectedTenet,
  onClearSelectedTenet,
  onFocusFile,
  onFocusTenet,
  onFocusClaim,
  onOpenTenetsView,
  progressStatus,
}: Props) {
  const [command, setCommand] = useState("");
  const [history, setHistory] = useState<string[]>([]);
  const [cursor, setCursor] = useState(-1);
  const outRef = useRef<HTMLDivElement>(null);
  const rootRef = useRef<HTMLElement>(null);
  const [hovered, setHovered] = useState(true);
  const [dragging, setDragging] = useState(false);
  const leaveTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  // spring state
  const target = useRef({ x: 0, y: 0 });
  const pos = useRef({ x: 0, y: 0, vx: 0, vy: 0 });
  const raf = useRef(0);

  function paint() {
    const el = rootRef.current;
    if (!el) return;
    const p = pos.current;
    const rot = Math.max(-0.7, Math.min(0.7, p.vx * 0.04));
    const stretch = Math.min(0.005, Math.hypot(p.vx, p.vy) * 0.0004);
    el.style.transform = `translate3d(${p.x}px, ${p.y}px, 0) rotate(${rot}deg) scale(${1 + stretch}, ${1 - stretch})`;
  }

  function step() {
    const t = target.current;
    const p = pos.current;
    p.vx = (p.vx + (t.x - p.x) * 0.2) * 0.72; // spring with damping < 1 => overshoot / jiggle
    p.vy = (p.vy + (t.y - p.y) * 0.2) * 0.72;
    p.x += p.vx;
    p.y += p.vy;
    const rest = Math.abs(t.x - p.x) < 0.05 && Math.abs(t.y - p.y) < 0.05 && Math.abs(p.vx) < 0.05 && Math.abs(p.vy) < 0.05;
    if (rest) {
      p.x = t.x;
      p.y = t.y;
      p.vx = p.vy = 0;
      raf.current = 0;
    } else {
      raf.current = requestAnimationFrame(step);
    }
    paint();
  }

  function kick() {
    if (!raf.current) raf.current = requestAnimationFrame(step);
  }

  useEffect(() => () => cancelAnimationFrame(raf.current), []);
  useEffect(() => () => clearTimeout(leaveTimer.current), []);

  function startDrag(e: RPointerEvent<HTMLDivElement>) {
    if ((e.target as HTMLElement).closest("button") || e.button !== 0) return;
    const el = rootRef.current;
    const parent = el?.offsetParent as HTMLElement | null;
    if (!el || !parent) return;
    e.preventDefault();
    const sx = e.clientX - target.current.x;
    const sy = e.clientY - target.current.y;
    const r = el.getBoundingClientRect();
    const pr = parent.getBoundingClientRect();
    const baseL = r.left - pr.left - pos.current.x;
    const baseT = r.top - pr.top - pos.current.y;
    const keep = 80;
    setDragging(true);
    const move = (ev: PointerEvent) => {
      target.current.x = Math.max(keep - r.width - baseL, Math.min(ev.clientX - sx, parent.clientWidth - keep - baseL));
      target.current.y = Math.max(-baseT, Math.min(ev.clientY - sy, parent.clientHeight - 35 - baseT));
      kick();
    };
    const up = () => {
      setDragging(false);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  function enter(e: React.PointerEvent) {
    if (e.pointerType === "touch") return;
    clearTimeout(leaveTimer.current);
    setHovered(true);
  }

  function leave(e: React.PointerEvent) {
    if (e.pointerType === "touch") return;
    clearTimeout(leaveTimer.current);
    leaveTimer.current = setTimeout(() => setHovered(false), 250);
  }

  useEffect(() => {
    outRef.current?.scrollTo({ top: outRef.current.scrollHeight });
  }, [lines, minimized, progressStatus]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const raw = command.trim();
    if (!raw) return;
    setHistory((h) => [raw, ...h.filter((x) => x !== raw)].slice(0, 50));
    setCursor(-1);
    setCommand("");
    onSubmit(raw);
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      e.preventDefault();
      const next = Math.max(-1, Math.min(history.length - 1, cursor + (e.key === "ArrowUp" ? 1 : -1)));
      setCursor(next);
      setCommand(next === -1 ? "" : history[next]);
    }
  }

  function renderFormattedLine(text: string, tone?: string): ReactNode {
    // 1. Quick replies
    if (text.includes("[Open Tenets view]")) {
      return (
        <span className="quick-reply-wrapper">
          <button
            type="button"
            className="terminal-quick-reply"
            onClick={() => onOpenTenetsView?.()}
          >
            Open Tenets view ↗
          </button>
        </span>
      );
    }
    if (text.includes("[Ask as a question]")) {
      return (
        <span className="quick-reply-wrapper">
          <button
            type="button"
            className="terminal-quick-reply"
            onClick={() => onSubmit(`/ask ${command.trim() || "What does this tenet do?"}`)}
          >
            Ask as a question ↗
          </button>
        </span>
      );
    }
    if (text.includes("[Draft hypotheses]")) {
      return (
        <span className="quick-reply-wrapper">
          <button
            type="button"
            className="terminal-quick-reply"
            disabled={!selectedTenet}
            onClick={() => onSubmit("/hypothesize")}
          >
            Draft hypotheses ↗
          </button>
        </span>
      );
    }

    // 2. Route Chips (§8.4)
    if (text.trim().startsWith("Jev →")) {
      return <span className="route-chip">{text.trim()}</span>;
    }

    // 3. Citations parsing (§8.5)
    const elements: ReactNode[] = [];
    let lastIndex = 0;
    const matches = Array.from(text.matchAll(CITATION_REGEX));

    if (matches.length === 0) {
      return text || " ";
    }

    matches.forEach((m, idx) => {
      if (m.index !== undefined && m.index > lastIndex) {
        elements.push(text.slice(lastIndex, m.index));
      }
      const kind = m[1];
      const targetStr = m[2];
      const range = m[3];

      if (kind === "file") {
        elements.push(
          <button
            key={`file-${idx}`}
            type="button"
            className="citation-chip file-chip"
            onClick={() => onFocusFile?.(targetStr, range)}
            title={`Focus ${targetStr}${range ? ` lines ${range}` : ""}`}
          >
            📄 {targetStr}{range ? `:${range}` : ""}
          </button>
        );
      } else if (kind === "tenet") {
        elements.push(
          <button
            key={`tenet-${idx}`}
            type="button"
            className="citation-chip tenet-chip"
            onClick={() => onFocusTenet?.(targetStr)}
            title={`Focus tenet ${targetStr}`}
          >
            🏛️ {targetStr}
          </button>
        );
      } else if (kind === "claim") {
        elements.push(
          <button
            key={`claim-${idx}`}
            type="button"
            className="citation-chip claim-chip"
            onClick={() => onFocusClaim?.(targetStr)}
            title={`Inspect claim ${targetStr}`}
          >
            ⚡ {targetStr}
          </button>
        );
      }
      lastIndex = (m.index ?? 0) + m[0].length;
    });

    if (lastIndex < text.length) {
      elements.push(text.slice(lastIndex));
    }

    return elements;
  }

  if (!open) {
    return (
      <button className="open-terminal" onClick={() => onOpenChange(true)}>
        open terminal
      </button>
    );
  }

  return (
    <section
      ref={rootRef}
      className={`terminal ${minimized ? "minimized" : ""} ${!hovered && !dragging && !minimized ? "peek" : ""} ${dragging ? "dragging" : ""}`}
      aria-label="IntentFlow terminal"
      onPointerEnter={enter}
      onPointerLeave={leave}
    >
      <div className="terminal-title" onPointerDown={startDrag}>
        <div className="terminal-window-controls">
          <button onClick={() => onOpenChange(false)} aria-label="Close terminal" />
          <button onClick={() => onMinimizedChange(true)} aria-label="Minimize terminal" />
          <button onClick={() => onMinimizedChange(false)} aria-label="Restore terminal" />
        </div>
        <span className="terminal-title-text">{title}</span>

        {/* Selected-Tenet Pill (§8.1) */}
        <div className="terminal-target-pill">
          {selectedTenet ? (
            <span className="pill active" title={`Target tenet: ${selectedTenet.name} (${selectedTenet.id})`}>
              Target: <b>{selectedTenet.name}</b>
              <button
                type="button"
                className="pill-clear"
                onClick={(e) => {
                  e.stopPropagation();
                  onClearSelectedTenet?.();
                }}
                aria-label="Deselect tenet"
              >
                ✕
              </button>
            </span>
          ) : (
            <span className="pill empty" title="Click a tenet node in the Tenets view to enable hypothesis drafting">
              Target: none — click a tenet to draft hypotheses
            </span>
          )}
        </div>

        <button className="collapse" onClick={() => onMinimizedChange(!minimized)}>
          {minimized ? "□" : "⌄"}
        </button>
      </div>
      {!minimized ? (
        <>
          <div className="terminal-output" ref={outRef} aria-live="polite">
            {lines.map((line) => (
              <div key={line.id} className={line.tone ?? ""}>
                {renderFormattedLine(line.text, line.tone)}
              </div>
            ))}
            {/* Live Progress Stage Status Line (§3.3, §8.6) */}
            {progressStatus ? (
              <div className="terminal-progress-line muted">
                <span className="pulse-indicator">●</span> {progressStatus}
              </div>
            ) : null}
          </div>
          <form onSubmit={submit}>
            <label htmlFor="command">
              {prompt}:<b>~</b>$
            </label>
            <input
              id="command"
              ref={inputRef}
              autoComplete="off"
              spellCheck={false}
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              onKeyDown={onKey}
              placeholder={busy ? "working…" : "ask intent or execute command…"}
            />
            {/* Draft hypotheses button (§8.2) */}
            <button
              type="button"
              className="draft-hypotheses-btn"
              disabled={!selectedTenet || busy}
              onClick={() => {
                const raw = command.trim();
                onSubmit(raw ? `/hypothesize ${raw}` : "/hypothesize");
                setCommand("");
              }}
              title={selectedTenet ? `Draft hypotheses for ${selectedTenet.name}` : "Select a tenet in the Tenets view first"}
            >
              Draft hypotheses
            </button>
            <button type="submit" aria-label="Run command" disabled={busy}>
              ↵
            </button>
          </form>
        </>
      ) : null}
    </section>
  );
}
