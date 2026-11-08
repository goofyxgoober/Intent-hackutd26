"use client";

import { useEffect, useRef } from "react";

/**
 * A ruled chalk grid that answers the hand, quietly.
 *  - one slow ripple leaves the centre every few seconds
 *  - the lines near the cursor brighten and lean toward it
 *  - moving leaves a faint trail of ripples; click, drag and scroll each send a softer or firmer ring
 * Plain WebGL (no deps), DPR-capped, paused while hidden. With reduced motion it paints one still frame.
 */

interface Props {
  color?: [number, number, number];
  cellSize?: number;
  lineWidth?: number;
  rippleStrength?: number;
  rippleSpeed?: number;
  rippleInterval?: number;
  opacity?: number;
  fade?: number;
}

const DEFAULT_COLOR: [number, number, number] = [0.9, 0.89, 0.85];
const MAX = 10;

const VERT = `attribute vec2 p; void main(){ gl_Position = vec4(p, 0.0, 1.0); }`;

const FRAG = `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
#define MAX ${MAX}
uniform vec2 uRes;
uniform float uTime;
uniform vec3 uColor;
uniform float uCell;
uniform float uLine;
uniform float uStrength;
uniform float uSpeed;
uniform float uInterval;
uniform float uOpacity;
uniform float uFade;
uniform vec3 uMouse;      // x, y (device px), presence 0..1
uniform vec4 uR[MAX];     // x, y, start time, strength

void main(){
  vec2 px = gl_FragCoord.xy;
  vec2 d0 = px - uRes * 0.5;
  float cell = uCell;

  vec2 q = px;
  float glow = 0.0;

  // idle pulse from the centre
  {
    float dist = length(d0);
    vec2 dir = dist > 0.001 ? d0 / dist : vec2(0.0);
    float age = mod(uTime, uInterval);
    float radius = age * uSpeed * uRes.y;
    float env = exp(-pow((dist - radius) / (cell * 2.6), 2.0)) * exp(-age * 0.45);
    float wave = sin((dist - radius) / (cell * 1.1)) * env;
    q -= dir * wave * uStrength * cell;
    glow += env * 0.12;
  }

  // ripples from the hand
  for (int i = 0; i < MAX; i++) {
    vec4 r = uR[i];
    float age = uTime - r.z;
    if (r.w > 0.0 && age > 0.0 && age < 6.0) {
      vec2 d = px - r.xy;
      float dist = length(d);
      vec2 dir = dist > 0.001 ? d / dist : vec2(0.0);
      float radius = age * uSpeed * 2.2 * uRes.y;
      float env = exp(-pow((dist - radius) / (cell * 1.8), 2.0)) * exp(-age * 1.1) * r.w;
      float wave = sin((dist - radius) / (cell * 0.9)) * env;
      q -= dir * wave * uStrength * cell * 0.9;
      glow += env * 0.05;
    }
  }

  // the cursor: lines lean toward it and light up softly
  vec2 dm = px - uMouse.xy;
  float md = length(dm);
  float reach = cell * 4.5;
  float near = exp(-pow(md / reach, 2.0)) * uMouse.z;
  q -= (md > 0.001 ? dm / md : vec2(0.0)) * near * cell * 0.07;
  glow += near * 0.045;

  vec2 g = abs(fract(q / cell - 0.5) - 0.5) * cell;
  float line = 1.0 - smoothstep(uLine * 0.5, uLine * 0.5 + 1.0, min(g.x, g.y));

  vec2 n = d0 / (uRes * 0.5);
  float v = mix(1.0, smoothstep(1.3, 0.2, length(n)), uFade);
  // the cursor pocket ignores the vignette so the board never looks dead under the hand
  v = max(v, near);

  float a = line * (uOpacity + glow) * v;
  gl_FragColor = vec4(uColor * a, a);
}
`;

export default function RippleGrid({
  color = DEFAULT_COLOR,
  cellSize = 56,
  lineWidth = 1,
  rippleStrength = 0.05,
  rippleSpeed = 0.1,
  rippleInterval = 9,
  opacity = 0.06,
  fade = 0.75,
}: Props) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const gl = canvas.getContext("webgl", { premultipliedAlpha: true, antialias: false, alpha: true });
    if (!gl) return;

    const compile = (type: number, src: string) => {
      const s = gl.createShader(type)!;
      gl.shaderSource(s, src);
      gl.compileShader(s);
      return s;
    };
    const prog = gl.createProgram()!;
    gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      console.warn("RippleGrid shader failed:", gl.getProgramInfoLog(prog));
      return;
    }
    gl.useProgram(prog);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, "p");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

    const u = (name: string) => gl.getUniformLocation(prog, name);
    const uRes = u("uRes");
    const uTime = u("uTime");
    const uCell = u("uCell");
    const uLine = u("uLine");
    const uMouse = u("uMouse");
    const uR = u("uR");
    gl.uniform3f(u("uColor"), ...color);
    gl.uniform1f(u("uStrength"), rippleStrength);
    gl.uniform1f(u("uSpeed"), rippleSpeed);
    gl.uniform1f(u("uInterval"), rippleInterval);
    gl.uniform1f(u("uOpacity"), opacity);
    gl.uniform1f(u("uFade"), fade);

    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const t0 = performance.now() - 1500;
    const now = () => (performance.now() - t0) / 1000;

    let dpr = 1;
    let w = 1;
    let h = 1;
    let raf = 0;
    let last = 0;
    let busyUntil = 0;

    // ripples from the hand, newest overwrites oldest
    const rip = new Float32Array(MAX * 4);
    let slot = 0;
    const spawn = (x: number, y: number, strength: number) => {
      const i = slot++ % MAX;
      rip[i * 4] = x * dpr;
      rip[i * 4 + 1] = (h - y) * dpr; // GL origin is bottom-left
      rip[i * 4 + 2] = now();
      rip[i * 4 + 3] = strength;
      busyUntil = performance.now() + 3500;
    };

    // eased cursor
    const m = { x: -9999, y: -9999, tx: -9999, ty: -9999, on: 0, target: 0 };
    const lastTrail = { x: 0, y: 0, t: 0 };
    let lastWheel = 0;
    let down = false;

    function draw() {
      const s = motion.matches ? 0 : now();
      gl!.uniform1f(uTime, s);
      gl!.uniform4fv(uR, rip);
      gl!.uniform3f(uMouse, m.x * dpr, (h - m.y) * dpr, m.on);
      gl!.clearColor(0, 0, 0, 0);
      gl!.clear(gl!.COLOR_BUFFER_BIT);
      gl!.drawArrays(gl!.TRIANGLES, 0, 3);
    }

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      w = window.innerWidth;
      h = window.innerHeight;
      canvas.width = Math.max(1, Math.round(w * dpr));
      canvas.height = Math.max(1, Math.round(h * dpr));
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.uniform2f(uRes, canvas.width, canvas.height);
      gl.uniform1f(uCell, cellSize * dpr);
      gl.uniform1f(uLine, lineWidth * dpr);
      draw();
    };

    const loop = (t: number) => {
      raf = requestAnimationFrame(loop);
      const active = t < busyUntil || Math.abs(m.on - m.target) > 0.01;
      if (t - last < (active ? 15 : 33)) return;
      last = t;
      m.x += (m.tx - m.x) * 0.14;
      m.y += (m.ty - m.y) * 0.14;
      m.on += (m.target - m.on) * 0.08;
      draw();
    };
    const start = () => {
      cancelAnimationFrame(raf);
      if (motion.matches || document.hidden) draw();
      else raf = requestAnimationFrame(loop);
    };

    const onMove = (e: PointerEvent) => {
      if (motion.matches || e.pointerType === "touch") return;
      if (m.target === 0) {
        m.x = e.clientX;
        m.y = e.clientY;
      }
      m.tx = e.clientX;
      m.ty = e.clientY;
      m.target = 1;
      busyUntil = Math.max(busyUntil, performance.now() + 600);
      // a light trail: one small ring every ~150px of travel (closer together while dragging)
      const t = performance.now();
      const gap = down ? 70 : 150;
      if (Math.hypot(e.clientX - lastTrail.x, e.clientY - lastTrail.y) > gap && t - lastTrail.t > 120) {
        spawn(e.clientX, e.clientY, down ? 0.5 : 0.22);
        lastTrail.x = e.clientX;
        lastTrail.y = e.clientY;
        lastTrail.t = t;
      }
    };
    const onDown = (e: PointerEvent) => {
      if (motion.matches) return;
      down = true;
      spawn(e.clientX, e.clientY, 0.8);
    };
    const onUp = (e: PointerEvent) => {
      if (motion.matches) return;
      if (down) spawn(e.clientX, e.clientY, 0.3); // a soft settle when the hand lets go
      down = false;
    };
    const onWheel = (e: WheelEvent) => {
      if (motion.matches) return;
      const t = performance.now();
      if (t - lastWheel < 260) return;
      lastWheel = t;
      spawn(e.clientX, e.clientY, 0.3);
    };
    const onLeave = () => {
      m.target = 0;
    };

    resize();
    start();
    window.addEventListener("resize", resize);
    window.addEventListener("pointermove", onMove, { passive: true, capture: true });
    window.addEventListener("pointerdown", onDown, { passive: true, capture: true });
    window.addEventListener("pointerup", onUp, { passive: true, capture: true });
    window.addEventListener("wheel", onWheel, { passive: true, capture: true });
    document.documentElement.addEventListener("pointerleave", onLeave);
    document.addEventListener("visibilitychange", start);
    motion.addEventListener("change", start);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onMove, true);
      window.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("pointerup", onUp, true);
      window.removeEventListener("wheel", onWheel, true);
      document.documentElement.removeEventListener("pointerleave", onLeave);
      document.removeEventListener("visibilitychange", start);
      motion.removeEventListener("change", start);
    };
  }, [color, cellSize, lineWidth, rippleStrength, rippleSpeed, rippleInterval, opacity, fade]);

  return <canvas ref={ref} className="ripple-grid" aria-hidden="true" />;
}
