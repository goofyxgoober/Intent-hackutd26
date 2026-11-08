"use client";

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type PointerEvent as RPointerEvent } from "react";
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
}

export function Terminal({ lines, prompt, title, open, minimized, busy, onOpenChange, onMinimizedChange, onSubmit, inputRef }: Props) {
  const [command, setCommand] = useState("");
  const [history, setHistory] = useState<string[]>([]);
  const [cursor, setCursor] = useState(-1);
  const outRef = useRef<HTMLDivElement>(null);
  const rootRef = useRef<HTMLElement>(null);
  const [hovered, setHovered] = useState(true);
  const [dragging, setDragging] = useState(false);
  const leaveTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  // spring state: `target` is where the pointer wants the window, `pos` is where it visually is
  const target = useRef({ x: 0, y: 0 });
  const pos = useRef({ x: 0, y: 0, vx: 0, vy: 0 });
  const raf = useRef(0);

  function paint() {
    const el = rootRef.current;
    if (!el) return;
    const p = pos.current;
    const rot = Math.max(-2.5, Math.min(2.5, p.vx * 0.15));
    const stretch = Math.min(0.02, Math.hypot(p.vx, p.vy) * 0.0015);
    el.style.transform = `translate3d(${p.x}px, ${p.y}px, 0) rotate(${rot}deg) scale(${1 + stretch}, ${1 - stretch})`;
  }

  function step() {
    const t = target.current;
    const p = pos.current;
    p.vx = (p.vx + (t.x - p.x) * 0.18) * 0.8; // spring with damping < 1 => overshoot / jiggle
    p.vy = (p.vy + (t.y - p.y) * 0.18) * 0.8;
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
    // untransformed layout box, so we can keep the window on-screen
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
  }, [lines, minimized]);

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
        <div>
          <button onClick={() => onOpenChange(false)} aria-label="Close terminal" />
          <button onClick={() => onMinimizedChange(true)} aria-label="Minimize terminal" />
          <button onClick={() => onMinimizedChange(false)} aria-label="Restore terminal" />
        </div>
        <span>{title}</span>
        <button className="collapse" onClick={() => onMinimizedChange(!minimized)}>
          {minimized ? "□" : "⌄"}
        </button>
      </div>
      {!minimized ? (
        <>
          <div className="terminal-output" ref={outRef} aria-live="polite">
            {lines.map((line) => (
              <div key={line.id} className={line.tone ?? ""}>
                {line.text || " "}
              </div>
            ))}
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
            <button type="submit" aria-label="Run command" disabled={busy}>
              ↵
            </button>
          </form>
        </>
      ) : null}
    </section>
  );
}
