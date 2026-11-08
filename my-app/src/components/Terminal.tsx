"use client";

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
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
    <section className={`terminal ${minimized ? "minimized" : ""}`} aria-label="IntentFlow terminal">
      <div className="terminal-title">
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
