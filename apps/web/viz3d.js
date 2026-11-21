/* CIVITWIN 3D — a small dependency-free 3D renderer on Canvas 2D (offline).
   Perspective projection, shaded prisms, spheres, 3D polylines with flowing particles,
   ground layer, labels, drag-to-rotate, zoom, auto-rotate, hover picking, grow-in intro.
   The animation loop only runs while the canvas is on screen and the tab is visible. */
"use strict";

const Viz3D = (() => {
  const REDUCE = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const ease = (t) => 1 - Math.pow(1 - clamp(t, 0, 1), 3);
  const norm = (v) => { const l = Math.hypot(...v) || 1; return v.map((x) => x / l); };
  const LIGHT = norm([-0.45, 0.85, 0.35]);

  function rgb(c) {
    if (Array.isArray(c)) return c;
    const s = String(c).trim();
    if (s.startsWith("rgb")) { const m = s.match(/[\d.]+/g).map(Number); return [m[0], m[1], m[2]]; }
    let h = s.replace("#", "");
    if (h.length === 3) h = h.split("").map((x) => x + x).join("");
    const n = parseInt(h, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  const rgba = (c, a = 1) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`;
  const shade = (c, k) => (k >= 1 ? c.map((v) => v + (255 - v) * (k - 1)) : c.map((v) => v * k));

  function hull(points) {
    const p = points.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    if (p.length < 3) return p;
    const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    const lower = [], upper = [];
    for (const q of p) { while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], q) <= 0) lower.pop(); lower.push(q); }
    for (let i = p.length - 1; i >= 0; i--) { const q = p[i]; while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], q) <= 0) upper.pop(); upper.push(q); }
    return lower.slice(0, -1).concat(upper.slice(0, -1));
  }
  function inPoly(pt, poly) {
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [xi, yi] = poly[i], [xj, yj] = poly[j];
      if ((yi > pt[1]) !== (yj > pt[1]) && pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }
  const bez = (a, c, b, t) => { const u = 1 - t; return [0, 1, 2].map((k) => u * u * a[k] + 2 * u * t * c[k] + t * t * b[k]); };

  const registry = new WeakMap();
  const ICON = (n) => `<svg class="icon sm" aria-hidden="true"><use href="#i-${n}"/></svg>`;

  class Scene {
    constructor(host, opts = {}) {
      registry.get(host)?.destroy();
      registry.set(host, this);
      Scene.all = (Scene.all || []).filter((x) => !x.dead).concat(this); // for diagnostics
      this.o = { height: 460, yaw: -0.62, pitch: 0.9, zoom: 1, radius: 60, minPitch: 0.22, maxPitch: 1.48,
        autoRotate: !REDUCE, labels: true, label: "3D chart", halo: "#0b1324", spin: 0.11, center: [0, 0, 0], ...opts };
      this.yawBase = this.o.yaw; this.pitch = this.o.pitch; this.zoom = this.o.zoom;
      this.spinOffset = 0; this.introDone = REDUCE; this.auto = this.o.autoRotate; this.showLabels = this.o.labels;
      this.items = []; this.ground = []; this.hoverId = null; this.mouse = null; this.drag = null;
      this.t0 = performance.now(); this.last = this.t0; this.time = 0; this.visible = true; this.raf = 0;

      host.innerHTML = "";
      const wrap = document.createElement("div");
      wrap.className = "viz3d";
      wrap.innerHTML = `<canvas tabindex="0" role="img" aria-label="${this.o.label.replace(/"/g, "&quot;")}"></canvas>
        <div class="ctrls">
          <button type="button" data-a="spin" aria-pressed="${this.auto}" title="Auto-rotate">${ICON("refresh")}</button>
          <button type="button" data-a="labels" aria-pressed="${this.showLabels}" title="Labels">${ICON("tag")}</button>
          <button type="button" data-a="in" title="Zoom in">${ICON("zin")}</button>
          <button type="button" data-a="out" title="Zoom out">${ICON("zout")}</button>
          <button type="button" data-a="reset" title="Reset view">${ICON("target")}</button>
        </div><div class="hint">Drag to rotate · double-click to reset</div>`;
      host.appendChild(wrap);
      this.wrap = wrap;
      this.canvas = wrap.querySelector("canvas");
      this.ctx = this.canvas.getContext("2d");
      wrap.querySelector(".ctrls").addEventListener("click", (e) => {
        const b = e.target.closest("button[data-a]");
        if (!b) return;
        const a = b.dataset.a;
        if (a === "spin") { this.auto = !this.auto; b.setAttribute("aria-pressed", String(this.auto)); }
        if (a === "labels") { this.showLabels = !this.showLabels; b.setAttribute("aria-pressed", String(this.showLabels)); }
        if (a === "in") this.zoom = clamp(this.zoom * 1.18, 0.5, 3);
        if (a === "out") this.zoom = clamp(this.zoom / 1.18, 0.5, 3);
        if (a === "reset") this.reset();
        this.kick();
      });
      const c = this.canvas;
      c.addEventListener("pointerdown", (e) => { this.drag = { x: e.clientX, y: e.clientY, moved: false }; c.setPointerCapture(e.pointerId); });
      c.addEventListener("pointermove", (e) => {
        const r = c.getBoundingClientRect();
        this.mouse = [e.clientX - r.left, e.clientY - r.top, e.clientX, e.clientY];
        if (this.drag) {
          const dx = e.clientX - this.drag.x, dy = e.clientY - this.drag.y;
          if (Math.abs(dx) + Math.abs(dy) > 2) this.drag.moved = true;
          this.yawBase += dx * 0.008; this.pitch = clamp(this.pitch + dy * 0.006, this.o.minPitch, this.o.maxPitch);
          this.drag.x = e.clientX; this.drag.y = e.clientY;
          if (this.drag.moved && this.auto) { this.auto = false; wrap.querySelector('[data-a="spin"]').setAttribute("aria-pressed", "false"); }
        }
        this.kick();
      });
      c.addEventListener("pointerup", () => { this.drag = null; });
      c.addEventListener("pointerleave", () => { this.mouse = null; this.hoverId = null; window.CivTip?.hide(); this.kick(); });
      c.addEventListener("dblclick", () => { this.reset(); this.kick(); });
      c.addEventListener("keydown", (e) => {
        const k = e.key;
        if (k === "ArrowLeft") this.yawBase -= 0.12; else if (k === "ArrowRight") this.yawBase += 0.12;
        else if (k === "ArrowUp") this.pitch = clamp(this.pitch + 0.08, this.o.minPitch, this.o.maxPitch);
        else if (k === "ArrowDown") this.pitch = clamp(this.pitch - 0.08, this.o.minPitch, this.o.maxPitch);
        else if (k === "+" || k === "=") this.zoom = clamp(this.zoom * 1.15, 0.5, 3);
        else if (k === "-") this.zoom = clamp(this.zoom / 1.15, 0.5, 3);
        else return;
        e.preventDefault(); this.kick();
      });
      this.ro = new ResizeObserver(() => { this.resize(); this.kick(); });
      this.ro.observe(wrap);
      this.io = new IntersectionObserver((ents) => { this.visible = ents[0].isIntersecting; this.kick(); });
      this.io.observe(wrap);
      this.onVis = () => this.kick();
      document.addEventListener("visibilitychange", this.onVis);
      this.resize();
      this.kick();
    }

    reset() { this.yawBase = this.o.yaw; this.spinOffset = 0; this.pitch = this.o.pitch; this.zoom = this.o.zoom; }

    destroy() {
      cancelAnimationFrame(this.raf); this.raf = 0;
      this.ro?.disconnect(); this.io?.disconnect();
      document.removeEventListener("visibilitychange", this.onVis);
      this.dead = true;
    }

    setData({ items = [], ground = [] }, { regrow = true } = {}) {
      this.items = items; this.ground = ground;
      if (regrow) this.t0 = performance.now();
      this.kick();
    }

    resize() {
      const w = this.wrap.clientWidth || 600;
      const h = typeof this.o.height === "function" ? this.o.height(w) : this.o.height;
      const dpr = Math.min(window.devicePixelRatio || 1, 1.75);
      this.w = w; this.h = h;
      this.canvas.width = Math.round(w * dpr); this.canvas.height = Math.round(h * dpr);
      this.canvas.style.height = `${h}px`;
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    animating() {
      const el = performance.now() - this.t0;
      return !REDUCE && (this.auto || el < 2600 || this.items.some((i) => i.flow || i.pulse));
    }

    kick() {
      if (this.dead || this.raf) return;
      this.raf = requestAnimationFrame((t) => this.frame(t));
    }

    frame(now) {
      this.raf = 0;
      if (this.dead) return;
      if (!this.canvas.isConnected) { this.destroy(); return; }
      const dt = Math.min(0.05, (now - this.last) / 1000);
      this.last = now; this.time += dt;
      const el = (now - this.t0) / 1000;
      const intro = REDUCE ? 1 : ease(el / 1.7);
      if (this.auto && !this.drag && !REDUCE) this.spinOffset += dt * this.o.spin;
      this.yaw = this.yawBase + this.spinOffset - (1 - intro) * 0.9;
      this.draw(el);
      if (this.visible && !document.hidden && (this.animating() || this.drag)) this.kick();
    }

    project() {
      const cy = Math.cos(this.yaw), sy = Math.sin(this.yaw), cp = Math.cos(this.pitch), sp = Math.sin(this.pitch);
      const R = this.o.radius, D = R * 3.4;
      const s = (Math.min(this.w, this.h * 1.5) / (2 * R)) * 0.98 * this.zoom;
      const ox = this.w / 2, oy = this.h / 2 + this.h * 0.06;
      const [cx0, cy0, cz0] = this.o.center;
      this.view = [sy * cp, sp, cy * cp];
      return (x, y, z) => {
        x -= cx0; y -= cy0; z -= cz0;
        const x1 = x * cy - z * sy, z1 = x * sy + z * cy;
        const vy = z1 * sp - y * cp, depth = z1 * cp + y * sp;
        const f = D / (D - depth);
        return [ox + x1 * s * f, oy + vy * s * f, depth, s * f];
      };
    }

    draw(el) {
      const ctx = this.ctx, W = this.w, H = this.h;
      ctx.clearRect(0, 0, W, H);
      const P = this.project();
      const V = this.view;
      const halo = this.o.halo;

      // ground layer (never occludes)
      for (const g of this.ground) {
        if (g.type === "poly") {
          ctx.beginPath();
          g.pts.forEach(([x, z], i) => { const p = P(x, 0, z); i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]); });
          ctx.closePath();
          if (g.fill) { ctx.fillStyle = g.fill; ctx.fill(); }
          if (g.stroke) { ctx.strokeStyle = g.stroke; ctx.lineWidth = g.width || 1; ctx.setLineDash(g.dash || []); ctx.stroke(); ctx.setLineDash([]); }
        } else if (g.type === "line") {
          const a = P(g.a[0], g.y || 0, g.a[1]), b = P(g.b[0], g.y || 0, g.b[1]);
          ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]);
          ctx.strokeStyle = g.color; ctx.lineWidth = g.width || 1; ctx.lineCap = "round"; ctx.setLineDash(g.dash || []); ctx.stroke(); ctx.setLineDash([]);
        } else if (g.type === "text") {
          const p = P(g.x, g.y || 0, g.z);
          this.text(p[0], p[1], g.text, g.color, g.size || 10, g.weight || 500, halo, g.align || "center");
        }
      }

      const list = [];
      const picks = [];
      const appear = (it) => ease((el - (it.delay || 0)) / (it.dur || 0.9));

      for (const it of this.items) {
        if (it.type === "prism") {
          const g = REDUCE ? 1 : appear(it);
          if (g <= 0.001) continue;
          const n = it.sides || 8, rot = it.rot || 0, r = it.r;
          const y0 = it.y0 * g, y1 = Math.max(it.y1 * g, y0 + 0.01);
          const base = [], top = [];
          for (let k = 0; k < n; k++) {
            const a = rot + (2 * Math.PI * k) / n;
            const x = it.x + r * Math.cos(a), z = it.z + r * Math.sin(a);
            base.push(P(x, y0, z)); top.push(P(x, y1, z));
          }
          const col = rgb(it.color), alpha = it.alpha ?? 1;
          const hov = this.hoverId !== null && it.id === this.hoverId;
          for (let k = 0; k < n; k++) {
            const m = rot + (2 * Math.PI * (k + 0.5)) / n;
            const nx = Math.cos(m), nz = Math.sin(m);
            if (nx * V[0] + nz * V[2] <= 0.0) continue;
            const lit = 0.5 + 0.5 * Math.max(0, nx * LIGHT[0] + nz * LIGHT[2]);
            const k2 = (k + 1) % n;
            const pts = [base[k], base[k2], top[k2], top[k]];
            list.push({ d: (base[k][2] + top[k2][2]) / 2, pts, fill: rgba(shade(col, lit * (hov ? 1.25 : 1)), alpha), edge: hov ? it.hi : null, glow: it.glow });
          }
          if (it.cap !== false) {
            list.push({ d: top.reduce((s, p) => s + p[2], 0) / n + 0.01, pts: top, fill: rgba(shade(col, hov ? 1.35 : 1.12), alpha), edge: hov ? it.hi : it.capEdge, glow: it.glow });
          }
          if (it.pick && it.tip) picks.push({ id: it.id, tip: it.tip, poly: hull(base.concat(top).map((p) => [p[0], p[1]])), d: top[0][2] });
          if (it.label && this.showLabels) {
            const lp = P(it.x, y1 + (it.labelLift ?? 1.6), it.z);
            list.push({ d: 1e6 + lp[2], label: it.label, x: lp[0], y: lp[1], color: it.labelColor, size: it.labelSize || 10, weight: it.labelWeight || 600, pill: it.labelPill });
          }
        } else if (it.type === "line") {
          const a = it.flow ? clamp((el - (it.delay ?? 1.0)) / 0.6, 0, 1) : (REDUCE ? 1 : appear({ delay: it.delay || 0, dur: 0.6 }));
          if (a <= 0) continue;
          const pts = it.pts.map((q) => P(q[0], q[1], q[2]));
          for (let i = 0; i < pts.length - 1; i++) {
            list.push({ d: (pts[i][2] + pts[i + 1][2]) / 2, seg: [pts[i], pts[i + 1]], stroke: rgba(rgb(it.color), (it.alpha ?? 1) * a), width: it.width || 1 });
          }
          if (it.flow && !REDUCE && a > 0.5) {
            const f = it.flow;
            for (let j = 0; j < f.n; j++) {
              const u = ((this.time * f.speed + j / f.n + (it.phase || 0)) % 1 + 1) % 1;
              const idx = u * (it.pts.length - 1), i0 = Math.floor(idx), t = idx - i0;
              const q0 = it.pts[i0], q1 = it.pts[Math.min(i0 + 1, it.pts.length - 1)];
              const q = [0, 1, 2].map((k) => q0[k] + (q1[k] - q0[k]) * t);
              const p = P(q[0], q[1], q[2]);
              list.push({ d: p[2] + 0.02, dot: p, r: Math.max(1.4, (f.size || 0.5) * p[3]), fill: f.color, glow: true });
            }
          }
          if (it.pick && it.tip && pts.length > 1) picks.push({ id: it.id, tip: it.tip, line: pts, d: pts[Math.floor(pts.length / 2)][2] - 50 });
        } else if (it.type === "dot") {
          const g = REDUCE ? 1 : appear(it);
          if (g <= 0) continue;
          const p = P(it.x, it.y * g, it.z);
          const hov = this.hoverId !== null && it.id === this.hoverId;
          list.push({ d: p[2], dot: p, r: Math.max(2, it.r * p[3]) * (hov ? 1.35 : 1), fill: it.color, ball: true, ring: it.ring, alpha: it.alpha ?? 1 });
          if (it.stem) {
            const b = P(it.x, 0, it.z);
            list.push({ d: p[2] - 0.5, seg: [b, p], stroke: it.stem, width: 1 });
          }
          if (it.pick && it.tip) picks.push({ id: it.id, tip: it.tip, circle: [p[0], p[1], Math.max(6, it.r * p[3] + 3)], d: p[2] });
        } else if (it.type === "ring") {
          if (REDUCE) continue;
          const ph = (this.time * 0.6 + (it.phase || 0)) % 1;
          const rr = it.r * (0.6 + ph * 1.6);
          const pts = [];
          for (let k = 0; k <= 32; k++) { const a = (2 * Math.PI * k) / 32; pts.push(P(it.x + rr * Math.cos(a), 0.05, it.z + rr * Math.sin(a))); }
          list.push({ d: -1e6, ringPts: pts, stroke: rgba(rgb(it.color), 0.7 * (1 - ph)), width: 2 });
        } else if (it.type === "label") {
          if (!this.showLabels && !it.always) continue;
          const g = REDUCE ? 1 : appear(it);
          if (g < 0.6) continue;
          const p = P(it.x, it.y * g, it.z);
          list.push({ d: 1e6 + p[2], label: it.text, x: p[0], y: p[1], color: it.color, size: it.size || 10, weight: it.weight || 600, pill: it.pill });
        }
      }

      list.sort((a, b) => a.d - b.d);
      for (const o of list) {
        if (o.pts) {
          ctx.beginPath();
          o.pts.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])));
          ctx.closePath();
          if (o.glow) { ctx.shadowColor = o.glow; ctx.shadowBlur = 14; }
          ctx.fillStyle = o.fill; ctx.fill();
          ctx.shadowBlur = 0;
          ctx.lineWidth = o.edge ? 1.6 : 0.6;
          ctx.strokeStyle = o.edge || o.fill; ctx.stroke();
        } else if (o.seg) {
          ctx.beginPath(); ctx.moveTo(o.seg[0][0], o.seg[0][1]); ctx.lineTo(o.seg[1][0], o.seg[1][1]);
          ctx.strokeStyle = o.stroke; ctx.lineWidth = o.width; ctx.lineCap = "round"; ctx.stroke();
        } else if (o.ringPts) {
          ctx.beginPath(); o.ringPts.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])));
          ctx.strokeStyle = o.stroke; ctx.lineWidth = o.width; ctx.stroke();
        } else if (o.dot) {
          const [x, y] = o.dot;
          ctx.globalAlpha = o.alpha ?? 1;
          if (o.ball) {
            const c = rgb(o.fill);
            const gr = ctx.createRadialGradient(x - o.r * 0.35, y - o.r * 0.4, o.r * 0.1, x, y, o.r);
            gr.addColorStop(0, rgba(shade(c, 1.45))); gr.addColorStop(0.7, rgba(c)); gr.addColorStop(1, rgba(shade(c, 0.7)));
            if (o.ring) { ctx.beginPath(); ctx.arc(x, y, o.r + 1.6, 0, 7); ctx.fillStyle = o.ring; ctx.fill(); }
            ctx.beginPath(); ctx.arc(x, y, o.r, 0, 7); ctx.fillStyle = gr; ctx.fill();
          } else {
            ctx.shadowColor = o.fill; ctx.shadowBlur = o.glow ? 8 : 0;
            ctx.beginPath(); ctx.arc(x, y, o.r, 0, 7); ctx.fillStyle = o.fill; ctx.fill();
            ctx.shadowBlur = 0;
          }
          ctx.globalAlpha = 1;
        } else if (o.label !== undefined) {
          if (o.pill) {
            ctx.font = `${o.weight} ${o.size}px system-ui, sans-serif`;
            const w = ctx.measureText(o.label).width + 12, h = o.size + 7;
            ctx.fillStyle = o.pill; ctx.beginPath(); ctx.roundRect(o.x - w / 2, o.y - h + 2, w, h, h / 2); ctx.fill();
            ctx.fillStyle = o.color || "#fff"; ctx.textAlign = "center"; ctx.textBaseline = "alphabetic";
            ctx.fillText(o.label, o.x, o.y - 2.5);
          } else this.text(o.x, o.y, o.label, o.color, o.size, o.weight, halo);
        }
      }

      // hover picking against the current projection
      let hit = null;
      if (this.mouse && !this.drag) {
        const [mx, my] = this.mouse;
        for (const p of picks) {
          let ok = false;
          if (p.poly) ok = inPoly([mx, my], p.poly);
          else if (p.circle) ok = Math.hypot(mx - p.circle[0], my - p.circle[1]) <= p.circle[2];
          else if (p.line) {
            for (let i = 0; i < p.line.length - 1 && !ok; i++) {
              const [ax, ay] = p.line[i], [bx, by] = p.line[i + 1];
              const L2 = (bx - ax) ** 2 + (by - ay) ** 2 || 1;
              const t = clamp(((mx - ax) * (bx - ax) + (my - ay) * (by - ay)) / L2, 0, 1);
              ok = Math.hypot(mx - (ax + t * (bx - ax)), my - (ay + t * (by - ay))) < 5;
            }
          }
          if (ok && (!hit || p.d > hit.d)) hit = p;
        }
      }
      const newId = hit ? hit.id : null;
      if (newId !== this.hoverId) { this.hoverId = newId; if (!this.animating()) this.kick(); }
      if (hit && this.mouse) window.CivTip?.show(hit.tip, this.mouse[2], this.mouse[3]);
      else if (this.mouse) window.CivTip?.hide();
      this.canvas.style.cursor = this.drag ? "grabbing" : hit ? "pointer" : "grab";
    }

    text(x, y, s, color, size, weight, halo, align = "center") {
      const ctx = this.ctx;
      ctx.font = `${weight} ${size}px system-ui, -apple-system, "Segoe UI", sans-serif`;
      ctx.textAlign = align; ctx.textBaseline = "middle";
      ctx.lineWidth = 3; ctx.strokeStyle = halo; ctx.lineJoin = "round"; ctx.strokeText(s, x, y);
      ctx.fillStyle = color; ctx.fillText(s, x, y);
    }
  }

  return { Scene, rgb, rgba, shade, bez, REDUCE };
})();
window.Viz3D = Viz3D;
