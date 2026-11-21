/* CIVITWIN real map — plain SVG from real coordinates (no tiles, works offline).
   Layers: Pakistan locator, tehsils (optionally shaded by literacy), district outline, OSM roads,
   every mapped settlement, demand clusters (by travel time or plan coverage), health facilities,
   optional plan flows. Wheel / buttons to zoom, drag to pan, hover for details, click a village. */
"use strict";

const GeoMap = (() => {
  const RAMPS = {
    travel: { light: ["#e8895a", "#d46a35", "#b5521f", "#8c3d14", "#5e270b"], dark: ["#9a4220", "#c2582a", "#e07a45", "#f0a072", "#f8c9a8"] },
    literacy: { light: ["#b799dd", "#9a72cb", "#7d52b4", "#5f3b93", "#42276c"], dark: ["#6542a0", "#7d5bb8", "#9877cc", "#b597dc", "#d3bdec"] },
  };
  const TRAVEL_BINS = [15, 30, 60, 120];
  const LIT_BINS = [22, 25, 28, 31]; // literacy %, lower = more need = darker
  const HOSPITAL = new Set(["AHQH", "THQH", "CH", "Type D HOSP"]);
  const MID = new Set(["RHC", "CHC", "MCHC", "MHF"]);
  const views = new WeakMap();

  const e = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n) => (n === null || n === undefined ? "n/a" : new Intl.NumberFormat("en-US").format(Math.round(n)));
  const mins = (m) => (m === null || m === undefined ? "no route" : m >= 90 ? `${Math.floor(m / 60)} h ${Math.round(m % 60)} min` : `${Math.round(m)} min`);

  function projector(geo) {
    const ring = geo.district;
    const lons = ring.map((p) => p[0]), lats = ring.map((p) => p[1]);
    const minLon = Math.min(...lons), maxLon = Math.max(...lons), minLat = Math.min(...lats), maxLat = Math.max(...lats);
    const lat0 = (minLat + maxLat) / 2, kx = Math.cos((lat0 * Math.PI) / 180);
    const S = 1000 / ((maxLon - minLon) * kx);
    const P = (lon, lat) => [(lon - minLon) * kx * S, (maxLat - lat) * S];
    const w = (maxLon - minLon) * kx * S, h = (maxLat - minLat) * S, pad = 0.06 * Math.max(w, h);
    return { P, box: [-pad, -pad, w + 2 * pad, h + 2 * pad], kmPerUnit: 111.32 / S };
  }
  const path = (P, ring, close = true) => ring.map((p, i) => `${i ? "L" : "M"}${P(p[0], p[1]).map((v) => v.toFixed(1)).join(",")}`).join("") + (close ? "Z" : "");
  const centroid = (ring) => [ring.reduce((a, p) => a + p[0], 0) / ring.length, ring.reduce((a, p) => a + p[1], 0) / ring.length];
  const bin = (v, bins) => { let i = 0; while (i < bins.length && v > bins[i]) i++; return i; };

  function nearestOpen(cid, open, minutes) {
    let best = null;
    for (const sid of open) {
      const t = minutes[`${cid}|${sid}`];
      if (t !== undefined && (!best || t < best.t)) best = { t, id: sid };
    }
    return best;
  }

  function locator(geo, c) {
    const W = 150, H = 128;
    const all = geo.pakistan.flat();
    const minLon = Math.min(...all.map((p) => p[0])), maxLon = Math.max(...all.map((p) => p[0]));
    const minLat = Math.min(...all.map((p) => p[1])), maxLat = Math.max(...all.map((p) => p[1]));
    const kx = Math.cos((((minLat + maxLat) / 2) * Math.PI) / 180);
    const s = Math.min((W - 8) / ((maxLon - minLon) * kx), (H - 8) / (maxLat - minLat));
    const P = (lon, lat) => [4 + (lon - minLon) * kx * s, 4 + (maxLat - lat) * s];
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Locator: Bajaur in Khyber Pakhtunkhwa, Pakistan">`;
    for (const pr of geo.provinces) {
      const kp = pr.name === "Khyber Pakhtunkhwa";
      for (const r of pr.rings) svg += `<path d="${path(P, r)}" fill="${kp ? c.kp : c.land}" stroke="${c.border}" stroke-width=".6"><title>${e(pr.name)}</title></path>`;
    }
    const [bx, by] = centroid(geo.district);
    const [x, y] = P(bx, by);
    svg += `<circle cx="${x}" cy="${y}" r="4.5" fill="none" stroke="${c.crit}" stroke-width="1.6"/><circle cx="${x}" cy="${y}" r="1.6" fill="${c.crit}"/>`;
    svg += `<text x="${x + 6}" y="${y - 4}" font-size="8" font-weight="700" fill="${c.ink}">Bajaur</text></svg>`;
    return svg;
  }

  function render(host, opts) {
    const { geo, dataset, minutes, run, mode = "travel", show = {}, palette: c, onPick } = opts;
    const dark = c.dark;
    const { P, box, kmPerUnit } = projector(geo);
    const prev = views.get(host);
    const vb = prev && prev.key === dataset.manifest.id ? prev.vb.slice() : box.slice();
    const thr = run?.plan?.threshold_minutes ?? opts.threshold ?? 60;
    const siteById = Object.fromEntries(geo.facilities.map((f) => [f.id, f]));
    const existing = geo.facilities.filter((f) => f.kind === "existing").map((f) => f.id);
    const chosen = new Set(run?.selected_candidate_ids || []);
    const open = existing.concat([...chosen]);
    const perCluster = {};
    if (run?.metrics) for (const pc of run.metrics.per_cluster) perCluster[pc.community_id] = pc;
    const travelRamp = RAMPS.travel[dark ? "dark" : "light"], litRamp = RAMPS.literacy[dark ? "dark" : "light"];

    let s = `<svg class="geomap-svg" viewBox="${vb.join(" ")}" role="img" aria-label="Map of Bajaur District with health facilities and settlements">`;
    // tehsils
    for (const t of geo.tehsils) {
      const fill = mode === "literacy" ? litRamp[4 - bin(t.literacy_pct, LIT_BINS)] : (dark ? "#1f2327" : "#f4efe6");
      s += `<path d="${path(P, t.ring)}" fill="${fill}" fill-opacity="${mode === "literacy" ? 0.85 : 1}" stroke="${c.border}" stroke-width="1" vector-effect="non-scaling-stroke"
        data-tip="${e(`${t.name} Tehsil\nPopulation ${fmt(t.population)} (Census 2023)\nLiteracy ${t.literacy_pct}% · area ${t.area_km2} km²`)}"/>`;
    }
    s += `<path d="${path(P, geo.district)}" fill="none" stroke="${c.ink}" stroke-width="2.2" vector-effect="non-scaling-stroke"/>`;
    if (show.roads !== false) {
      for (const r of geo.roads) {
        const major = r.class === "trunk" || r.class === "primary" || r.class === "secondary";
        s += `<path d="${path(P, r.pts, false)}" fill="none" stroke="${c.road}" stroke-width="${major ? 2.2 : 1.3}" stroke-linecap="round" vector-effect="non-scaling-stroke"${r.name ? ` data-tip="${e(`${r.name} (${r.class} road, OSM)`)}"` : ""}/>`;
      }
    }
    if (show.settlements !== false) {
      for (const st of geo.settlements) {
        const [x, y] = P(st.lon, st.lat);
        s += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="1.6" fill="${c.ink}" fill-opacity=".35"/>`;
      }
    }
    // flows
    if (run?.assignments && show.flows) {
      const pos = {};
      for (const cl of geo.clusters) pos[cl.id] = P(cl.lon, cl.lat);
      for (const f of geo.facilities) pos[f.id] = P(f.lon, f.lat);
      for (const a of run.assignments) {
        const A = pos[a.community_id], B = pos[a.site_id];
        if (!A || !B) continue;
        const within = a.minutes <= thr;
        s += `<line x1="${A[0].toFixed(1)}" y1="${A[1].toFixed(1)}" x2="${B[0].toFixed(1)}" y2="${B[1].toFixed(1)}" stroke="${within ? c.s1 : c.s2}" stroke-opacity="${within ? 0.35 : 0.7}" stroke-width="${(0.6 + Math.sqrt(a.visits) / 9).toFixed(2)}" vector-effect="non-scaling-stroke"/>`;
      }
    }
    // tehsil labels
    for (const t of geo.tehsils) {
      const [x, y] = P(...centroid(t.ring));
      s += `<text x="${x.toFixed(1)}" y="${y.toFixed(1)}" class="gm-tehsil" text-anchor="middle" fill="${c.ink}">${e(t.name.toUpperCase())}</text>`;
    }
    // clusters
    const rows = [];
    for (const cl of geo.clusters) {
      const [x, y] = P(cl.lon, cl.lat);
      const r = 3 + Math.sqrt(cl.population) / 28;
      const before = nearestOpen(cl.id, existing, minutes);
      const after = nearestOpen(cl.id, open, minutes);
      const pc = perCluster[cl.id];
      let fill;
      if (mode === "coverage" && pc) fill = c.seq[Math.min(4, Math.floor((pc.coverage_pct ?? 0) / 20))];
      else fill = travelRamp[after ? bin(after.t, TRAVEL_BINS) : 4];
      const tip = [`${cl.name} · ${cl.tehsil}`, `≈ ${fmt(cl.population)} people (estimated from Census 2023) · ${cl.members} mapped settlement${cl.members === 1 ? "" : "s"}`,
        `Nearest open facility: ${after ? `${mins(after.t)} — ${siteById[after.id]?.label || after.id}` : "no route"}`];
      if (chosen.size && before && after && after.t < before.t - 0.5) tip.push(`Before this plan: ${mins(before.t)} (${siteById[before.id]?.label || before.id})`);
      if (pc) tip.push(`Plan: ${pc.coverage_pct === null ? "n/a" : pc.coverage_pct.toFixed(0)}% of visits within ${thr} min · ${pc.unmet} unmet/week`);
      rows.push({ cl, before, after });
      s += `<circle class="gm-village" data-id="${cl.id}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r.toFixed(1)}" fill="${fill}" stroke="${c.surface}" stroke-width="1.2" vector-effect="non-scaling-stroke" data-tip="${e(tip.join("\n"))}"/>`;
    }
    // facilities
    for (const f of geo.facilities) {
      const [x, y] = P(f.lon, f.lat);
      const sel = chosen.has(f.id);
      const status = f.kind === "existing" ? "Functional (registry 2018)" : f.kind === "reactivate" ? (sel ? "Non-functional → REOPEN in this plan" : "Non-functional (registry 2018)") : (sel ? "Proposed new BHU → BUILD in this plan" : "Possible new BHU site (not chosen)");
      const tip = `${f.label}\n${f.type_name} · ${f.tehsil}\n${status}${f.beds ? `\nBeds: ${f.beds}` : ""}\nAssumed capacity ${fmt(f.capacity)} visits/week${f.cost ? ` · planning cost PKR ${fmt(f.cost)}/week` : ""}${f.gazetteer_located ? "\nLocation from catchment village (registry note)" : ""}`;
      const size = HOSPITAL.has(f.type) ? 7 : MID.has(f.type) ? 5.6 : 4.4;
      let fill = c.site, stroke = c.surface, dash = "", extra = "";
      if (f.kind === "reactivate") { fill = sel ? c.brand : c.surface; stroke = sel ? c.surface : c.crit; }
      if (f.kind === "new") { fill = sel ? c.brand : "none"; stroke = sel ? c.surface : c.brand; dash = sel ? "" : ' stroke-dasharray="3 2"'; if (!sel && !show.candidates) continue; }
      let shape;
      if (HOSPITAL.has(f.type)) shape = `<rect x="${(x - size).toFixed(1)}" y="${(y - size).toFixed(1)}" width="${2 * size}" height="${2 * size}" rx="1.5"`;
      else if (f.kind === "new") shape = `<path d="M${x - size} ${y - size / 2.6}h${size * 2 / 3}v-${size * 0.62}h${size * 2 / 3}v${size * 0.62}h${size * 2 / 3}v${size * 0.77}h-${size * 2 / 3}v${size * 0.62}h-${size * 2 / 3}v-${size * 0.62}h-${size * 2 / 3}z"`;
      else if (MID.has(f.type)) shape = `<path d="M${x} ${y - size}L${x + size} ${y}L${x} ${y + size}L${x - size} ${y}Z"`;
      else shape = `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${size}"`;
      if (f.kind === "reactivate" && !sel) extra = `<path d="M${x - 2.6} ${y - 2.6}L${x + 2.6} ${y + 2.6}M${x + 2.6} ${y - 2.6}L${x - 2.6} ${y + 2.6}" stroke="${c.crit}" stroke-width="1.4" vector-effect="non-scaling-stroke"/>`;
      s += `<g class="gm-fac" data-tip="${e(tip)}">${shape} fill="${fill}" stroke="${stroke}" stroke-width="1.6" vector-effect="non-scaling-stroke"${dash}/>${extra}`;
      if (sel) s += `<text x="${x}" y="${y - size - 4}" class="gm-tag" text-anchor="middle" fill="${c.brandInk}">${f.kind === "reactivate" ? "REOPEN" : "NEW"}</text>`;
      s += "</g>";
    }
    // town labels
    for (const st of geo.settlements.filter((x) => x.kind === "town")) {
      const [x, y] = P(st.lon, st.lat);
      s += `<text x="${(x + 6).toFixed(1)}" y="${(y - 6).toFixed(1)}" class="gm-town" fill="${c.inkStrong}">${e(st.name)}</text>`;
    }
    s += "</svg>";

    host.innerHTML = `<div class="geomap">${s}
      <div class="gm-locator" aria-hidden="false">${locator(geo, { kp: dark ? "#3a4a44" : "#d9e4dc", land: dark ? "#24282c" : "#efe9de", border: dark ? "#4a5056" : "#c8bfb0", crit: c.crit, ink: c.inkStrong })}<div class="gm-loc-cap">Pakistan · Khyber Pakhtunkhwa</div></div>
      <div class="gm-ctrls"><button type="button" data-z="in" title="Zoom in">+</button><button type="button" data-z="out" title="Zoom out">−</button><button type="button" data-z="reset" title="Reset view">⟲</button></div>
      <div class="gm-north" aria-hidden="true"><svg viewBox="0 0 20 28"><path d="M10 2 L16 20 L10 16 L4 20Z" fill="${c.inkStrong}"/><text x="10" y="27" font-size="7" text-anchor="middle" fill="${c.inkStrong}">N</text></svg></div>
      <div class="gm-scale"><i></i><span></span></div>
      <div class="gm-attr">© OpenStreetMap contributors · GeoNames · geoBoundaries · FATA Health Dept/WHO (OCHA) · PBS Census 2023 · OSRM</div></div>`;
    const svg = host.querySelector("svg.geomap-svg");
    const state = { key: dataset.manifest.id, vb };
    views.set(host, state);
    const apply = () => {
      svg.setAttribute("viewBox", state.vb.join(" "));
      const pxPerUnit = svg.clientWidth / state.vb[2];
      const target = 80 / pxPerUnit * kmPerUnit;
      const nice = [1, 2, 5, 10, 20, 50].find((k) => k >= target / 1.6) || 50;
      host.querySelector(".gm-scale i").style.width = `${(nice / kmPerUnit) * pxPerUnit}px`;
      host.querySelector(".gm-scale span").textContent = `${nice} km`;
    };
    const zoomAt = (k, cx, cy) => {
      const [x, y, w, h] = state.vb;
      const nw = Math.min(box[2] * 1.2, Math.max(box[2] / 14, w * k)), nh = nw * (h / w);
      const fx = (cx - x) / w, fy = (cy - y) / h;
      state.vb = [cx - fx * nw, cy - fy * nh, nw, nh];
      apply();
    };
    const toMap = (ev) => {
      const r = svg.getBoundingClientRect();
      return [state.vb[0] + ((ev.clientX - r.left) / r.width) * state.vb[2], state.vb[1] + ((ev.clientY - r.top) / r.height) * state.vb[3]];
    };
    svg.addEventListener("wheel", (ev) => { ev.preventDefault(); const [mx, my] = toMap(ev); zoomAt(ev.deltaY > 0 ? 1.18 : 1 / 1.18, mx, my); }, { passive: false });
    let drag = null;
    svg.addEventListener("pointerdown", (ev) => { drag = { x: ev.clientX, y: ev.clientY, vb: state.vb.slice(), moved: false }; svg.setPointerCapture(ev.pointerId); });
    svg.addEventListener("pointermove", (ev) => {
      if (!drag) return;
      const r = svg.getBoundingClientRect();
      const dx = ((ev.clientX - drag.x) / r.width) * drag.vb[2], dy = ((ev.clientY - drag.y) / r.height) * drag.vb[3];
      if (Math.abs(ev.clientX - drag.x) + Math.abs(ev.clientY - drag.y) > 3) drag.moved = true;
      state.vb = [drag.vb[0] - dx, drag.vb[1] - dy, drag.vb[2], drag.vb[3]];
      apply();
    });
    svg.addEventListener("pointerup", (ev) => {
      const wasClick = drag && !drag.moved;
      drag = null;
      if (wasClick && onPick) {
        const el = document.elementFromPoint(ev.clientX, ev.clientY)?.closest?.(".gm-village");
        if (el) onPick(el.dataset.id);
      }
    });
    host.querySelector(".gm-ctrls").addEventListener("click", (ev) => {
      const b = ev.target.closest("button[data-z]");
      if (!b) return;
      const [x, y, w, h] = state.vb;
      if (b.dataset.z === "reset") { state.vb = box.slice(); apply(); } else zoomAt(b.dataset.z === "in" ? 1 / 1.4 : 1.4, x + w / 2, y + h / 2);
    });
    requestAnimationFrame(apply);
    return { rows };
  }

  function legend(mode, c, thr, hasRun) {
    const ramp = (arr) => `<span class="scale">${arr.map((x) => `<i style="background:${x}"></i>`).join("")}</span>`;
    const dark = c.dark;
    const items = [];
    if (mode === "literacy") items.push(`<span>Tehsil literacy (Census 2023) ${ramp(RAMPS.literacy[dark ? "dark" : "light"])} ≥31% … &lt;22% (darker = greater need)</span>`);
    if (mode === "coverage" && hasRun) items.push(`<span>Village: share of visits within ${thr} min in this plan ${ramp(c.seq)} 0 → 100%</span>`);
    else items.push(`<span>Village: time to nearest open facility ${ramp(RAMPS.travel[dark ? "dark" : "light"])} ≤15 · ≤30 · ≤60 · ≤120 · &gt;120 min</span>`);
    items.push(`<span><svg width="14" height="14"><rect x="2" y="2" width="10" height="10" rx="1.5" fill="${c.site}"/></svg>hospital</span>`,
      `<span><svg width="14" height="14"><path d="M7 1L13 7L7 13L1 7Z" fill="${c.site}"/></svg>RHC / CHC</span>`,
      `<span><svg width="14" height="14"><circle cx="7" cy="7" r="4.5" fill="${c.site}"/></svg>BHU / dispensary</span>`,
      `<span><svg width="14" height="14"><circle cx="7" cy="7" r="4.5" fill="none" stroke="${c.crit}" stroke-width="1.6"/><path d="M4.5 4.5L9.5 9.5M9.5 4.5L4.5 9.5" stroke="${c.crit}" stroke-width="1.3"/></svg>non-functional</span>`,
      `<span><svg width="14" height="14"><circle cx="7" cy="7" r="4.5" fill="${c.brand}"/></svg>reopened / new in plan</span>`,
      `<span><svg width="14" height="14"><circle cx="7" cy="7" r="1.6" fill="${c.ink}" fill-opacity=".5"/></svg>mapped settlement</span>`);
    return items.join("");
  }

  return { render, legend, nearestOpen };
})();
window.GeoMap = GeoMap;
