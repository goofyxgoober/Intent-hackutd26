"use client";

import { useEffect, useRef } from "react";

/**
 * The living blackboard: a few dozen chalk-dust motes that drift on their own, scatter from the
 * cursor, and brighten when it moves; three slow eraser smudges; a faint violet lamp under the
 * pointer. Pure canvas, DPR-capped, paused when the tab is hidden. With reduced motion it paints
 * one still frame. The film grain on top is plain CSS (see theme.css).
 */

type Mote = { x: number; y: number; vx: number; vy: number; r: number; a: number; ph: number };
type Smudge = { x: number; y: number; r: number; sx: number; sy: number; ph: number };

const rand = (a: number, b: number) => a + Math.random() * (b - a);

export default function ChalkBoard() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    let reduced = motionQuery.matches;
    let w = 0;
    let h = 0;
    let raf = 0;
    let last = 0;
    let motes: Mote[] = [];
    let smudges: Smudge[] = [];
    // lamp = eased pointer; heat = how recently/fast the pointer moved (0..1)
    const ptr = { x: -9999, y: -9999, lx: -9999, ly: -9999, heat: 0, on: false };

    function seed() {
      const count = Math.round(Math.min(110, Math.max(36, (w * h) / 17000)));
      motes = Array.from({ length: count }, () => ({
        x: rand(0, w),
        y: rand(0, h),
        vx: rand(-4, 4),
        vy: rand(-3, 3),
        r: rand(0.5, 1.5),
        a: rand(0.05, 0.16),
        ph: rand(0, Math.PI * 2),
      }));
      smudges = Array.from({ length: 3 }, (_, i) => ({
        x: w * (0.2 + 0.3 * i),
        y: h * rand(0.25, 0.75),
        r: Math.max(w, h) * rand(0.22, 0.32),
        sx: rand(4, 9) * (i % 2 ? 1 : -1),
        sy: rand(2, 6),
        ph: rand(0, 6),
      }));
    }

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      w = window.innerWidth;
      h = window.innerHeight;
      canvas!.width = Math.round(w * dpr);
      canvas!.height = Math.round(h * dpr);
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
      seed();
      if (reduced) paint(0);
    }

    function paint(t: number) {
      ctx!.clearRect(0, 0, w, h);

      // slow eraser smudges
      for (const s of smudges) {
        const x = s.x + Math.sin(t * 0.00004 * s.sx + s.ph) * 90;
        const y = s.y + Math.cos(t * 0.00005 * s.sy + s.ph) * 60;
        const g = ctx!.createRadialGradient(x, y, 0, x, y, s.r);
        g.addColorStop(0, "rgba(214, 210, 200, 0.028)");
        g.addColorStop(1, "rgba(214, 210, 200, 0)");
        ctx!.fillStyle = g;
        ctx!.fillRect(x - s.r, y - s.r, s.r * 2, s.r * 2);
      }

      // lamp under the pointer
      if (ptr.on) {
        const r = 280;
        const g = ctx!.createRadialGradient(ptr.lx, ptr.ly, 0, ptr.lx, ptr.ly, r);
        g.addColorStop(0, `rgba(183, 109, 240, ${0.035 + ptr.heat * 0.04})`);
        g.addColorStop(1, "rgba(183, 109, 240, 0)");
        ctx!.fillStyle = g;
        ctx!.fillRect(ptr.lx - r, ptr.ly - r, r * 2, r * 2);
      }

      for (const m of motes) {
        const d = Math.hypot(m.x - ptr.lx, m.y - ptr.ly);
        const near = ptr.on && d < 190 ? 1 - d / 190 : 0;
        const twinkle = 0.75 + 0.25 * Math.sin(t * 0.0008 + m.ph);
        const alpha = Math.min(0.5, (m.a + near * (0.1 + ptr.heat * 0.22)) * twinkle);
        ctx!.fillStyle = `rgba(230, 228, 222, ${alpha})`;
        ctx!.beginPath();
        ctx!.arc(m.x, m.y, m.r + near * 0.5, 0, Math.PI * 2);
        ctx!.fill();
      }
    }

    function step(now: number) {
      raf = requestAnimationFrame(step);
      const dt = Math.min(0.05, (now - (last || now)) / 1000);
      last = now;

      ptr.lx += (ptr.x - ptr.lx) * 0.12;
      ptr.ly += (ptr.y - ptr.ly) * 0.12;
      ptr.heat *= 0.94;

      for (const m of motes) {
        // gentle wander
        m.vx += Math.sin(now * 0.0003 + m.ph) * 0.9 * dt;
        m.vy += Math.cos(now * 0.00027 + m.ph * 1.3) * 0.9 * dt;
        // scatter from the cursor
        if (ptr.on) {
          const dx = m.x - ptr.lx;
          const dy = m.y - ptr.ly;
          const d = Math.hypot(dx, dy);
          if (d < 160 && d > 0.1) {
            const f = (1 - d / 160) ** 2 * (28 + ptr.heat * 90);
            m.vx += (dx / d) * f * dt * 6;
            m.vy += (dy / d) * f * dt * 6;
          }
        }
        // ease back toward a slow drift
        m.vx *= 0.985;
        m.vy *= 0.985;
        m.x += m.vx * dt * 6;
        m.y += m.vy * dt * 6;
        if (m.x < -5) m.x = w + 5;
        else if (m.x > w + 5) m.x = -5;
        if (m.y < -5) m.y = h + 5;
        else if (m.y > h + 5) m.y = -5;
      }
      paint(now);
    }

    function start() {
      cancelAnimationFrame(raf);
      last = 0;
      if (reduced) paint(0);
      else raf = requestAnimationFrame(step);
    }

    const onMove = (e: PointerEvent) => {
      if (e.pointerType === "touch") return;
      if (!ptr.on) {
        ptr.lx = e.clientX;
        ptr.ly = e.clientY;
      }
      ptr.heat = Math.min(1, ptr.heat + Math.hypot(e.movementX, e.movementY) / 120);
      ptr.x = e.clientX;
      ptr.y = e.clientY;
      ptr.on = true;
    };
    const onLeave = () => {
      ptr.on = false;
    };
    const onVisibility = () => {
      if (document.hidden) cancelAnimationFrame(raf);
      else start();
    };
    const onMotion = () => {
      reduced = motionQuery.matches;
      start();
    };

    resize();
    start();
    window.addEventListener("resize", resize);
    window.addEventListener("pointermove", onMove, { passive: true });
    document.documentElement.addEventListener("pointerleave", onLeave);
    document.addEventListener("visibilitychange", onVisibility);
    motionQuery.addEventListener("change", onMotion);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onMove);
      document.documentElement.removeEventListener("pointerleave", onLeave);
      document.removeEventListener("visibilitychange", onVisibility);
      motionQuery.removeEventListener("change", onMotion);
    };
  }, []);

  return (
    <>
      <canvas ref={ref} className="chalkboard-dust" aria-hidden="true" />
      <div className="chalkboard-grain" aria-hidden="true" />
    </>
  );
}
