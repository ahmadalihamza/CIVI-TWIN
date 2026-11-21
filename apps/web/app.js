/* CIVITWIN AI — offline dashboard. No external scripts, fonts or CDNs. */
"use strict";

const API = "/api/v1";
const PUBLIC_DEMO = document.documentElement.hasAttribute("data-public-demo");
const STORE_KEY = "civitwin.session.v1";
const KINDS = ["baseline", "greedy", "optimized"];
const KIND_LABEL = { baseline: "Baseline", greedy: "Greedy benchmark", optimized: "Optimized plan" };
const KIND_DESC = { baseline: "existing sites only", greedy: "simple heuristic", optimized: "lexicographic solver" };
const TERMINAL = new Set(["COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT", "NO_SOLUTION", "INTERRUPTED", "INVALID"]);
const VIEWS = {
  overview: ["Map & plan", "Bajaur District, Khyber Pakhtunkhwa"],
  data: ["Data & sources", "Where every number comes from"],
  plan: ["Scenario builder", "Describe, review and confirm a plan"],
  results: ["Comparison", "Baseline, greedy and optimized plans on identical inputs"],
  stress: ["Stress lab", "How each plan's sites hold up when demand and travel change"],
  report: ["Report", "Printable summary with hashes, audit and exports"],
  about: ["Our approach", "Why we built CIVITWIN and how we keep it honest"],
};
const THEME_KEY = "civitwin.theme";
function C() {
  const cs = getComputedStyle(document.documentElement);
  const v = (n) => cs.getPropertyValue(n).trim();
  return {
    dark: document.documentElement.dataset.theme === "dark",
    s1: v("--series-1"), s2: v("--series-2"), base: v("--series-base"), seq: [1, 2, 3, 4, 5].map((i) => v(`--seq-${i}`)),
    surface: v("--chart-surface"), grid: v("--chart-grid"), axis: v("--chart-axis"), ink: v("--chart-ink"), inkStrong: v("--chart-ink-strong"),
    site: v("--site-existing"), road: v("--road"), brand: v("--brand"), brandInk: v("--brand-ink"), crit: v("--crit"), critInk: v("--crit-ink"),
    warn: v("--warn"), warnInk: v("--warn-ink"), card: v("--card"),
  };
}

const S = {
  system: null, dataset: null, minutes: {}, scenario: null, reviewed: null, running: false,
  runs: { baseline: null, greedy: null, optimized: null },
  comparison: null, expl: {}, stress: null, mapKind: "optimized", mapMode: "3d", showAssign: true, lang: "en",
  sortBy: "gain", parse: null, impact: {}, tradeoff: {}, journeyPick: null,
  datasets: [], dsInfo: null, geo: null, coord: {}, mapLayer: "travel", deskWhen: "plan",
  layers: { roads: true, settlements: true, candidates: false, flows: false },
};

/* ---------- helpers ---------- */
const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const nf0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
const num = (v) => (v === null || v === undefined ? "n/a" : nf0.format(v));
const pct = (v) => (v === null || v === undefined ? "n/a" : `${nf1.format(v)}%`);
const mins = (v) => (v === null || v === undefined ? "n/a" : `${nf1.format(v)} min`);
const pkr = (v) => (v === null || v === undefined ? "n/a" : `PKR ${nf0.format(v)}`);
const pkrShort = (v) => (v === null || v === undefined ? "n/a" : v >= 100000 ? `PKR ${nf1.format(v / 100000)} lakh` : `PKR ${nf0.format(v)}`);
const short = (h) => (h ? `${h.slice(0, 12)}…` : "—");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const icon = (name, cls = "") => `<svg class="icon ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;

let inflight = 0;
function progress(d) { inflight = Math.max(0, inflight + d); $("topProgress").classList.toggle("on", inflight > 0); }
async function api(path, opts = {}) {
  if (PUBLIC_DEMO) throw new Error("This published demo is read-only.");
  progress(1);
  let res;
  try { res = await fetch(API + path, { ...opts, headers: { "Content-Type": "application/json", ...(opts.headers || {}) } }); }
  finally { progress(-1); }
  let body = null;
  try { body = await res.json(); } catch { body = null; }
  if (!res.ok) {
    const err = new Error((body && body.message) || `${res.status} ${res.statusText}`);
    err.status = res.status; err.body = body;
    throw err;
  }
  return body;
}

function showError(msg) {
  const el = $("globalError");
  if (!msg) { el.hidden = true; el.innerHTML = ""; return; }
  el.hidden = false; el.innerHTML = `${icon("alert")}<div>${esc(msg)}</div>`;
}

function toast(msg, kind = "info") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = `${icon(kind === "ok" ? "check" : kind === "err" ? "alert" : "info")}<div>${esc(msg)}</div>`;
  $("toasts").appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

function statusPill(status) {
  const s = status || "—";
  let cls = "run", ic = "clock";
  if (s === "COMPLETED") { cls = "ok"; ic = "check"; }
  else if (["FAILED", "NO_SOLUTION", "TIMED_OUT", "INTERRUPTED", "INVALID"].includes(s)) { cls = "bad"; ic = "x"; }
  else if (s === "CANCELLED") { cls = "warn"; ic = "alert"; }
  const label = { NO_SOLUTION: "No solution", TIMED_OUT: "Timed out" }[s] || s.charAt(0) + s.slice(1).toLowerCase().replace(/_/g, " ");
  return `<span class="status ${cls}">${icon(ic)}${esc(label)}</span>`;
}

function deltaBadge(d, better, fmtFn, eps = 0.05) {
  if (d === null || d === undefined || Number.isNaN(d)) return "";
  // below display precision counts as no change (avoids a red "+0.0")
  if (Math.abs(d) < eps) return `<span class="delta flat">→ no change</span>`;
  const good = better === "up" ? d > 0 : better === "down" ? d < 0 : null;
  const cls = good === null ? "flat" : good ? "good" : "bad";
  return `<span class="delta ${cls}">${icon(d > 0 ? "up" : "down", "sm")}${d > 0 ? "+" : "−"}${esc(fmtFn(Math.abs(d)))}</span>`;
}

const FMT = { pct, num: (v) => num(Math.round(v)), pkr: (v) => pkr(Math.round(v)), mins, pp: (v) => `${nf1.format(v)} pp`, int: (v) => nf0.format(Math.round(v)) };
function countSpan(v, kind) {
  if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
  return `<span data-count="${v}" data-fmt="${kind}">${esc(FMT[kind](v))}</span>`;
}
function animateCounts(root) {
  root.querySelectorAll("[data-count]").forEach((el, i) => {
    const to = Number(el.dataset.count), f = FMT[el.dataset.fmt] || num;
    if (Viz3D.REDUCE || document.hidden || !Number.isFinite(to)) { el.textContent = f(to); return; }
    const t0 = performance.now() + i * 40, dur = 1100;
    // never leave a partial number on screen: timers still run if frames are paused
    setTimeout(() => { el.textContent = f(to); }, dur + i * 40 + 400);
    const step = (now) => {
      const p = Math.max(0, Math.min(1, (now - t0) / dur));
      el.textContent = f(to * (1 - Math.pow(1 - p, 3)));
      if (p < 1) requestAnimationFrame(step);
    };
    el.textContent = f(0);
    requestAnimationFrame(step);
  });
}

function saveSession() {
  localStorage.setItem(STORE_KEY, JSON.stringify({
    dataset_id: S.dataset?.manifest?.id || null,
    scenario_id: S.scenario?.scenario_id || null,
    runs: Object.fromEntries(KINDS.map((k) => [k, S.runs[k]?.run_id || null])),
    stress_id: S.stress?.stress_run_id || null,
  }));
}

/* ---------- tooltip layer ---------- */
(function tooltip() {
  const tip = $("tooltip");
  let current = null;
  const place = (x, y) => {
    const r = tip.getBoundingClientRect();
    let left = x + 14, top = y + 14;
    if (left + r.width > innerWidth - 8) left = x - r.width - 14;
    if (top + r.height > innerHeight - 8) top = y - r.height - 14;
    tip.style.left = `${Math.max(8, left)}px`; tip.style.top = `${Math.max(8, top)}px`;
  };
  const show = (el, x, y) => { current = el; tip.textContent = el.getAttribute("data-tip"); tip.classList.add("on"); place(x, y); };
  const hide = () => { current = null; tip.classList.remove("on"); };
  window.CivTip = {
    show(text, x, y) { tip.textContent = text; tip.classList.add("on"); place(x, y); },
    hide() { if (!current) tip.classList.remove("on"); },
  };
  document.addEventListener("mouseover", (e) => { const el = e.target.closest?.("[data-tip]"); if (el) show(el, e.clientX, e.clientY); else if (current) hide(); });
  document.addEventListener("mousemove", (e) => { if (current) place(e.clientX, e.clientY); });
  document.addEventListener("focusin", (e) => { const el = e.target.closest?.("[data-tip]"); if (el) { const r = el.getBoundingClientRect(); show(el, r.right, r.top); } });
  document.addEventListener("focusout", hide);
  document.addEventListener("scroll", hide, true);
})();

/* ---------- routing & shell ---------- */
function route() {
  const v = (location.hash || "#overview").slice(1).split("/")[0];
  const view = Object.hasOwn(VIEWS, v) && !(PUBLIC_DEMO && v === "plan") ? v : "overview";
  for (const k of Object.keys(VIEWS)) $(`view-${k}`).hidden = k !== view;
  document.querySelectorAll("#mainNav a").forEach((a) => {
    if (a.dataset.view === view) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  $("pageTitle").textContent = VIEWS[view][0];
  $("pageSub").textContent = VIEWS[view][1];
  document.title = `${VIEWS[view][0]} · CIVITWIN AI`;
  if (view === "results") $("navResultsBadge").hidden = true;
  closeNav();
}
function closeNav() { $("app").classList.remove("nav-open"); $("menuBtn").setAttribute("aria-expanded", "false"); }
$("menuBtn").addEventListener("click", () => { const open = $("app").classList.toggle("nav-open"); $("menuBtn").setAttribute("aria-expanded", String(open)); });
$("scrim").addEventListener("click", closeNav);
window.addEventListener("hashchange", () => { route(); window.scrollTo(0, 0); $("main").focus({ preventScroll: true }); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeNav(); });

/* ---------- theme ---------- */
function themeIcon() {
  const dark = document.documentElement.dataset.theme === "dark";
  $("themeBtn").innerHTML = icon(dark ? "sun" : "moon");
  $("themeBtn").setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
}
$("themeBtn").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.body.classList.add("theming");
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem(THEME_KEY, next); } catch { /* private mode */ }
  themeIcon();
  setTimeout(() => document.body.classList.remove("theming"), 450);
  if (S.dataset) { renderData(); renderResults(); renderStress(); renderDesk(); }
});
themeIcon();

/* ---------- init ---------- */
async function init() {
  route();
  if (PUBLIC_DEMO) {
    try { await initPublicDemo(); }
    catch (e) {
      $("dotApi").className = "dot warn"; $("sfApi").textContent = "unavailable";
      showError(`Could not load the published demo (${e.message}).`);
    }
    return;
  }
  try {
    S.system = await api("/system");
    $("sfApi").textContent = "online";
    $("sfSolver").textContent = S.system.solver_version.replace("ortools-cpsat", "OR-Tools CP-SAT").replace("scipy-highs", "HiGHS");
    $("sfAi").textContent = S.system.ai_model_enabled ? "enabled" : "off · offline parser";
    const list = await api("/datasets");
    S.datasets = list;
    let want = null;
    try { want = localStorage.getItem(DS_KEY); } catch { want = null; }
    const pick = list.find((d) => d.id === want) || list.find((d) => d.id === "bajaur-real-walk-v1") || list[0];
    S.dsInfo = pick;
    setDataset(await api(`/datasets/${encodeURIComponent(pick.id)}`));
    S.geo = pick.has_map ? await api(`/datasets/${encodeURIComponent(pick.id)}/geo`) : null;
    setChrome();
    renderData(); renderExamples(); renderPresets(); setForm(defaultsPlan()); renderSummary(); renderFlow(); renderRunStatus();
    renderDesk();
    await restoreSession();
    renderResults(); renderStress(); renderReport(); renderDesk();
  } catch (e) {
    $("dotApi").className = "dot warn"; $("sfApi").textContent = "offline";
    showError(`Could not reach the local API (${e.message}). Start it with: python -m civitwin_api`);
  }
}

function setDataset(dataset) {
  S.dataset = dataset;
  S.minutes = Object.fromEntries(dataset.travel.minutes.map((t) => [`${t.community_id}|${t.site_id}`, t.minutes]));
}

async function initPublicDemo() {
  const response = await fetch("snapshot.json");
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const { info, dataset, runs, comparison, expl, stress, impact, tradeoff } = await response.json();
  setDataset(dataset);
  S.datasets = [info];
  S.dsInfo = info;
  Object.assign(S, { runs, comparison, expl, stress });
  const optimized = runs.optimized;
  S.impact[optimized.run_id] = impact;
  S.tradeoff[optimized.plan_hash] = tradeoff;
  $("sfApi").textContent = "Read-only demo";
  $("sfSolver").textContent = optimized.engine.solver_version;
  $("sfAi").textContent = "off";
  $("stressStatus").textContent = `Build-time results · seed ${stress.seed} · ${stress.case_count} cases`;
  setChrome();
  const docs = document.createElement("a");
  docs.href = "https://github.com/ahmadalihamza/CIVI-TWIN#windows-powershell";
  docs.textContent = "Run locally to create scenarios";
  $("noticeText").append(" ", docs);
  renderData(); renderResults(); renderStress(); renderReport(); renderDesk();
}

const DS_KEY = "civitwin.dataset";
const DS_NAMES = { "bajaur-real-walk-v1": "Bajaur · on foot (real data)", "bajaur-real-v1": "Bajaur · by vehicle (real data)", "demo-bajaur-v1": "Demo district (synthetic)" };
function isReal() { return S.dataset && !S.dataset.manifest.is_synthetic; }
function setChrome() {
  const sel = $("dsSelect");
  sel.innerHTML = S.datasets.map((d) => `<option value="${esc(d.id)}" ${d.id === S.dataset.manifest.id ? "selected" : ""}>${esc(DS_NAMES[d.id] || d.district_label)}</option>`).join("");
  sel.onchange = () => {
    try { localStorage.setItem(DS_KEY, sel.value); localStorage.removeItem(STORE_KEY); } catch { /* ignore */ }
    location.hash = "#overview"; location.reload();
  };
  const real = isReal();
  $("dataBadge").innerHTML = real ? `${icon("db", "sm")}REAL PUBLIC DATA` : `${icon("flask", "sm")}SYNTHETIC DATA`;
  $("dataBadge").title = real ? "Real sources with stated assumptions — see Data & sources" : "All data in this view is fictional";
  $("noticeText").textContent = real
    ? `Real public data: OpenStreetMap, GeoNames, the FATA Health Department/WHO facility registry (2018) and the 2023 census. Population split, utilisation, capacity and costs are stated assumptions. Travel is ${S.dsInfo.travel_mode === "foot" ? "on foot" : "by vehicle"}. Advisory planning — not an approved allocation.`
    : PUBLIC_DEMO ? "Published read-only demo. Fictional data, one modeled week. Results were computed and audited during the build."
      : "Demo district with fictional data — not real district statistics. Time horizon: one modeled week.";
  $("footData").textContent = real ? "real public data with stated assumptions" : "synthetic demonstration";
  $("pageSub").textContent = real ? `Bajaur District, Khyber Pakhtunkhwa · ${S.dsInfo.travel_mode === "foot" ? "travel on foot" : "travel by vehicle"}` : "Demo district (synthetic)";
  VIEWS.overview[1] = $("pageSub").textContent;
}
function defaultsPlan() {
  const d = S.dsInfo?.default_plan || { budget_pkr: 300000, max_new_units: 2, threshold_minutes: 45 };
  return { dataset_version_id: S.dataset.manifest.id, budget_pkr: d.budget_pkr, max_new_units: d.max_new_units, threshold_minutes: d.threshold_minutes,
    demand_multiplier_pct: 100, equity_min_pct: 0, policy: "coverage_first", seed: 2026, min_coverage_pct: null };
}
const siteName = (id) => S.dataset?.sites.find((x) => x.id === id)?.label || id;
const placeName = (id) => { const c = S.dataset?.communities.find((x) => x.id === id); return c ? c.label.replace(/\s*\(.*\)$/, "") : id; };

function dsStats() {
  const ds = S.dataset;
  const cands = ds.sites.filter((s) => s.type === "candidate");
  const costs = cands.map((s) => s.fixed_cost_pkr);
  const demand = ds.communities.reduce((a, c) => a + c.demand_visits_per_week, 0);
  const capacity = ds.sites.filter((s) => s.type === "existing").reduce((a, s) => a + s.capacity_per_week, 0);
  return { clusters: ds.communities.length, existing: ds.sites.length - cands.length, candidates: cands.length,
    eligible: cands.filter((s) => s.eligible).length, demand, capacity, costMin: Math.min(...costs), costMax: Math.max(...costs) };
}

function renderTiles() {
  if (!$("dsTiles")) return;
  const st = dsStats();
  const tile = (ic, lbl, val, meta) => `<div class="tile"><div class="lbl">${icon(ic, "sm")}${esc(lbl)}</div><div class="val">${val}</div><div class="meta">${meta}</div></div>`;
  $("dsTiles").innerHTML = [
    tile("users", "Community clusters", countSpan(st.clusters, "int"), "aggregate, fictional"),
    tile("target", "Weekly demand", `${countSpan(st.demand, "int")}<small>visits</small>`, "requested outpatient visits"),
    tile("building", "Existing sites", countSpan(st.existing, "int"), `${num(st.capacity)} visits/week capacity`),
    tile("plus", "Candidate zones", `${countSpan(st.candidates, "int")}<small>${st.eligible} eligible</small>`, `${pkrShort(st.costMin)}–${nf1.format(st.costMax / 100000)} lakh / week`),
    tile("coins", "Capacity vs demand", countSpan((100 * st.capacity) / st.demand, "pct"), "existing capacity ÷ demand"),
  ].join("");
  animateCounts($("dsTiles"));
}

async function renderRecent() {
  if (!$("recentRuns")) return;
  try {
    const runs = await api("/runs?limit=8");
    $("recentRuns").innerHTML = runs.length
      ? `<div class="table-wrap"><table><thead><tr><th>Run</th><th>Plan</th><th>Status</th><th>Created (UTC)</th></tr></thead><tbody>${
        runs.map((r) => `<tr><td class="mono">${esc(r.id)}</td><td>${esc(KIND_LABEL[r.kind] || r.kind)}</td><td>${statusPill(r.status)}</td><td class="muted">${esc(r.created_at.replace("T", " ").replace("Z", ""))}</td></tr>`).join("")
      }</tbody></table></div>`
      : emptyState("clock", "No runs yet", "Runs you start will be listed here.", `<a class="btn primary sm" href="#plan">Start a scenario</a>`);
  } catch { $("recentRuns").innerHTML = `<div class="card-b muted">Could not load runs.</div>`; }
}

function emptyState(ic, title, text, action = "") {
  return `<div class="empty"><div class="em-ic">${icon(ic, "lg")}</div><h3>${esc(title)}</h3><p class="small">${esc(text)}</p>${action}</div>`;
}

function bars3d(rows, { h = 230 } = {}) {
  const c = C();
  const W = 440, H = h, base = H - 30, top = 30, bw = 70, gap = 48, dx = 18, dy = -11, x0 = 46;
  const y = (v) => base - ((base - top) * Math.max(0, Math.min(100, v || 0))) / 100;
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(`3D bar chart of coverage: ${rows.map((r) => `${r.label} ${r.text}`).join(", ")}`)}">`;
  s += `<polygon points="${x0},${base} ${x0 + dx},${base + dy} ${W - 6},${base + dy} ${W - 6 - dx},${base}" fill="${c.grid}" opacity=".6"/>`;
  for (const t of [0, 25, 50, 75, 100]) {
    s += `<line x1="${x0 + dx}" y1="${y(t) + dy}" x2="${W - 6}" y2="${y(t) + dy}" stroke="${c.grid}"/>`;
    s += `<text x="${x0 + dx - 6}" y="${y(t) + dy + 4}" text-anchor="end" font-size="10.5" fill="${c.ink}">${t}%</text>`;
  }
  rows.forEach((r, i) => {
    const x = x0 + 26 + i * (bw + gap), yt = y(r.value), col = Viz3D.rgb(r.color);
    const front = Viz3D.rgba(col), side = Viz3D.rgba(Viz3D.shade(col, 0.68)), topf = Viz3D.rgba(Viz3D.shade(col, 1.3));
    const gid = `g3d${i}${Math.round(Math.random() * 1e6)}`;
    s += `<defs><linearGradient id="${gid}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${topf}"/><stop offset=".35" stop-color="${front}"/><stop offset="1" stop-color="${Viz3D.rgba(Viz3D.shade(col, 0.85))}"/></linearGradient></defs>`;
    s += `<g data-tip="${esc(r.tip || "")}"><g class="grow-y" style="animation-delay:${0.1 + i * 0.15}s">`;
    s += `<polygon points="${x + bw},${yt} ${x + bw + dx},${yt + dy} ${x + bw + dx},${base + dy} ${x + bw},${base}" fill="${side}"/>`;
    s += `<rect x="${x}" y="${yt}" width="${bw}" height="${Math.max(base - yt, 0.5)}" fill="url(#${gid})"/>`;
    s += `<polygon points="${x},${yt} ${x + dx},${yt + dy} ${x + bw + dx},${yt + dy} ${x + bw},${yt}" fill="${topf}"/></g>`;
    s += `<text class="fade-in" style="animation-delay:${0.7 + i * 0.15}s" x="${x + bw / 2 + dx / 2}" y="${yt + dy - 9}" text-anchor="middle" font-size="15" font-weight="700" fill="${c.inkStrong}">${esc(r.text)}</text>`;
    s += `<text x="${x + bw / 2}" y="${base + 20}" text-anchor="middle" font-size="12" fill="${c.ink}">${esc(r.label)}</text></g>`;
  });
  return `${s}</svg>`;
}

function coverageRows() {
  const c = C();
  return KINDS.filter((k) => S.runs[k]?.status === "COMPLETED").map((k) => {
    const m = S.runs[k].metrics;
    return { label: k === "optimized" ? "Optimized" : k === "greedy" ? "Greedy" : "Baseline", value: m.coverage_pct.value, text: pct(m.coverage_pct.value),
      color: k === "baseline" ? c.base : k === "greedy" ? c.s2 : c.s1,
      tip: `${KIND_LABEL[k]}\n${num(m.within_threshold_visits.value)} of ${num(m.total_demand.value)} weekly visits within ${S.runs[k].plan.threshold_minutes} min\nNew sites: ${S.runs[k].selected_candidate_ids.join(", ") || "none"}` };
  });
}

function renderLatest() {
  if (!$("latestBox")) return;
  const o = S.runs.optimized;
  if (!o || o.status !== "COMPLETED") {
    $("latestBox").innerHTML = emptyState("target", "No scenario yet", "Describe a plan, confirm it, and the comparison appears here.", `<a class="btn primary sm" href="#plan">${icon("play", "sm")}Start a scenario</a>`);
    return;
  }
  const p = o.plan;
  const b = S.runs.baseline;
  const d = b?.status === "COMPLETED" ? o.metrics.coverage_pct.value - b.metrics.coverage_pct.value : null;
  $("latestBox").innerHTML = `<div class="row between" style="margin-bottom:.4rem"><div><div class="big" style="font-size:2.3rem;font-weight:720">${countSpan(o.metrics.coverage_pct.value, "pct")}</div>
      <div class="small muted">of weekly visits within ${p.threshold_minutes} min · optimized plan</div></div>${d !== null ? deltaBadge(d, "up", (v) => `${nf1.format(v)} pp vs baseline`) : ""}</div>
    ${bars3d(coverageRows(), { h: 210 })}
    <p class="tiny muted mt-h">${pkr(p.budget_pkr)}/week · up to ${p.max_new_units} new units · ${p.policy.replace("_", " ")} · new sites: ${esc(o.selected_candidate_ids.join(", ") || "none")}</p>`;
  animateCounts($("latestBox"));
}

/* ---------- data explorer ---------- */
function renderData() {
  const ds = S.dataset, m = ds.manifest;
  $("manifestBox").innerHTML = `<dl class="kv">
      <dt>Dataset</dt><dd>${esc(m.id)}</dd><dt>Version</dt><dd>${esc(m.version)}</dd>
      <dt>Data type</dt><dd><span class="status warn">${icon("flask")}Synthetic</span></dd>
      <dt>Source date</dt><dd>${esc(m.source_date)}</dd><dt>Source</dt><dd>${esc(m.source_url ?? "generated, seed " + (m.generator?.seed ?? "—"))}</dd>
      <dt>License</dt><dd>${esc(m.license.split(" ")[0])}</dd>
      <dt>Travel model</dt><dd>Dijkstra, rounded once</dd><dt>Unreachable pairs</dt><dd>${ds.travel.unreachable_pairs}</dd></dl>
    <div class="small muted mt-1" style="margin-bottom:.3rem">SHA-256</div><div class="hashbox">${esc(m.sha256)}</div>
    ${ds.validation_warnings.length ? ds.validation_warnings.map((w) => `<div class="alert warn">${icon("alert", "sm")}${esc(w)}</div>`).join("") : `<div class="alert ok">${icon("check", "sm")}<div>Validation passed — no warnings.</div></div>`}`;
  $("assumptionsBox").innerHTML = `<ul class="small" style="margin:0;padding-left:1.1rem;color:var(--ink-2)">${m.assumptions.map((a) => `<li style="margin-bottom:.3rem">${esc(a)}</li>`).join("")}</ul>
    <details class="mt-h"><summary class="small" style="cursor:pointer;color:var(--series-1);font-weight:600">Provenance records (${ds.provenance.length})</summary>
    <div class="table-wrap mt-h"><table><thead><tr><th>Entity</th><th>Field</th><th>Method</th></tr></thead><tbody>${
      ds.provenance.map((p) => `<tr data-tip="${esc(p.caveat)}"><td>${esc(p.entity)}</td><td>${esc(p.field)}</td><td>${esc(p.method)}</td></tr>`).join("")}</tbody></table></div></details>`;

  const near = (cid, type) => {
    let best = null;
    for (const s of ds.sites) {
      if (type === "candidate" && (s.type !== "candidate" || !s.eligible)) continue;
      if (type === "existing" && s.type !== "existing") continue;
      const t = S.minutes[`${cid}|${s.id}`];
      if (t !== undefined && (best === null || t < best.t)) best = { t, id: s.id };
    }
    return best;
  };
  const maxD = Math.max(...ds.communities.map((c) => c.demand_visits_per_week));
  const nearCell = (b) => (b ? `<td class="num">${b.t} <span class="muted tiny">${esc(b.id)}</span></td>` : `<td class="num muted">unreachable</td>`);
  $("commTable").innerHTML = `<table><thead><tr><th>Cluster</th><th>Zone</th><th>Demand / week</th><th class="num">Nearest existing (min)</th><th class="num">Nearest candidate (min)</th></tr></thead><tbody>${
    ds.communities.map((c) => `<tr><td><b>${esc(c.id)}</b></td><td class="muted">${esc(c.zone_class)}</td>
      <td><span class="meter"><i style="width:${(100 * c.demand_visits_per_week) / maxD}%"></i></span>${c.demand_visits_per_week}</td>${nearCell(near(c.id, "existing"))}${nearCell(near(c.id, "candidate"))}</tr>`).join("")
  }</tbody></table>`;
  const maxC = Math.max(...ds.sites.map((s) => s.capacity_per_week));
  $("siteTable").innerHTML = `<table><thead><tr><th>Site</th><th>Type</th><th>Capacity / week</th><th class="num">Cost (PKR / week)</th><th>Eligible</th></tr></thead><tbody>${
    ds.sites.map((s) => `<tr><td><b>${esc(s.id)}</b></td><td class="muted">${s.type === "existing" ? "existing" : "candidate"}</td>
      <td><span class="meter"><i style="width:${(100 * s.capacity_per_week) / maxC}%"></i></span>${s.capacity_per_week}</td>
      <td class="num">${s.type === "candidate" ? nf0.format(s.fixed_cost_pkr) : "—"}</td>
      <td>${s.type === "existing" ? `<span class="muted">open</span>` : s.eligible ? `<span class="status ok">${icon("check")}Yes</span>` : `<span class="status bad">${icon("x")}No</span>`}</td></tr>`).join("")
  }</tbody></table>`;
  if (S.geo) {
    $("dataMapTitle").textContent = "Bajaur District — real map";
    $("dataMapDesc").textContent = "Tehsils, roads and settlements from OpenStreetMap/GeoNames; facilities from the FATA Health Department/WHO registry";
    const host = $("dataMap");
    host.innerHTML = `<div class="geomap-host" id="dataGeo"></div><div class="legend">${GeoMap.legend("travel", geoPalette(), 0, false)}</div>`;
    GeoMap.render($("dataGeo"), { geo: S.geo, dataset: S.dataset, minutes: S.minutes, run: null, mode: "travel", show: { roads: true, settlements: true, candidates: true }, palette: geoPalette() });
  } else {
    $("dataMapTitle").textContent = "3D network";
    $("dataMapDesc").textContent = "Column height = weekly demand · schematic positions, not real coordinates";
    mountMap($("dataMap"), null, { title: "3D schematic network: column height is weekly demand" });
  }
}

/* ---------- map ---------- */
function covColor(p, c = C()) {
  if (p === null || p === undefined) return c.axis;
  return c.seq[Math.min(4, Math.floor(p / 20))];
}

function geoPalette() { const c = C(); return { ...c, border: c.axis }; }
function mountMap(container, run, { showAssign = true, mode = "3d", title = "" } = {}) {
  if (mode === "2d" && S.geo) {
    container.innerHTML = `<div class="geomap-host"></div><div class="legend">${GeoMap.legend("coverage", geoPalette(), run?.plan?.threshold_minutes, !!run)}</div>`;
    GeoMap.render(container.querySelector(".geomap-host"), { geo: S.geo, dataset: S.dataset, minutes: S.minutes, run, mode: "coverage", show: { roads: true, settlements: false, flows: showAssign }, palette: geoPalette() });
    return;
  }
  if (mode === "2d") { container.innerHTML = mapSvg(run, { showAssign, title }); return; }
  container.innerHTML = `<div class="m3"></div><div class="legend">${map3dLegend(run, showAssign)}</div>`;
  map3d(container.querySelector(".m3"), run, { showAssign, title });
}

function map3dLegend(run, showAssign) {
  const c = C();
  const sw = (col, a = 1) => `<span class="sw" style="background:${col};opacity:${a}"></span>`;
  const out = [];
  if (run) {
    out.push(`<span>${sw(c.s1)}visits within ${run.plan.threshold_minutes} min</span>`, `<span>${sw(c.s2)}served beyond threshold</span>`, `<span>${sw(c.base, 0.5)}unmet demand</span>`);
    if (showAssign) out.push(`<span><i class="ln" style="background:${c.s1}"></i>flow within threshold</span><span><i class="ln" style="background:${c.s2}"></i>flow beyond threshold</span>`);
  } else out.push(`<span>${sw(c.s1)}weekly demand (column height)</span>`);
  out.push(`<span>${sw(c.site)}existing site</span>`, `<span>${sw(c.brand)}opened candidate</span>`, `<span><span class="sw" style="border:1.5px dashed ${c.brand}"></span>candidate not opened</span>`, `<span>${sw(c.axis)}ineligible</span>`);
  return out.join("");
}

function map3d(host, run, { showAssign = true, title = "" } = {}) {
  const c = C(), ds = S.dataset;
  const pos = {};
  const geoMode = !!S.geo;
  let G = (x, y) => [x - 50, y - 40];
  if (geoMode) {  // real lon/lat -> ~110 x 90 world units, north away from the viewer
    const ring = S.geo.district, lons = ring.map((q) => q[0]), lats = ring.map((q) => q[1]);
    const cx = (Math.min(...lons) + Math.max(...lons)) / 2, cy = (Math.min(...lats) + Math.max(...lats)) / 2;
    const kx = Math.cos((cy * Math.PI) / 180), sc = 100 / ((Math.max(...lons) - Math.min(...lons)) * kx);
    G = (lon, lat) => [(lon - cx) * kx * sc, (cy - lat) * sc];
  }
  for (const n of ds.nodes) pos[n.id] = G(n.display_x, n.display_y);
  const nodeOf = {};
  for (const cm of ds.communities) nodeOf[cm.id] = cm.node_id;
  for (const st of ds.sites) nodeOf[st.id] = st.node_id;
  const ground = [];
  if (geoMode) {
    ground.push({ type: "poly", pts: S.geo.district.map((q) => G(q[0], q[1])), fill: c.dark ? "rgba(38,42,46,.7)" : "rgba(255,253,249,.92)", stroke: c.inkStrong, width: 1.6 });
    for (const t of S.geo.tehsils) ground.push({ type: "poly", pts: t.ring.map((q) => G(q[0], q[1])), stroke: c.axis, width: 1 });
    for (const r of S.geo.roads) for (let k = 1; k < r.pts.length; k++) ground.push({ type: "line", a: G(...r.pts[k - 1]), b: G(...r.pts[k]), color: c.road, width: 1.6 });
  } else {
    ground.push({ type: "poly", pts: [[-55, -45], [55, -45], [55, 45], [-55, 45]], fill: c.dark ? "rgba(38,42,46,.62)" : "rgba(255,253,249,.88)", stroke: c.axis, width: 1 });
    for (let x = -50; x <= 50; x += 10) ground.push({ type: "line", a: [x, -45], b: [x, 45], color: c.grid, width: 0.6 });
    for (let z = -40; z <= 40; z += 10) ground.push({ type: "line", a: [-55, z], b: [55, z], color: c.grid, width: 0.6 });
    for (const e of ds.edges) if (pos[e.from_node] && pos[e.to_node]) ground.push({ type: "line", a: pos[e.from_node], b: pos[e.to_node], color: c.road, width: 2.4 });
  }

  const items = [];
  const maxD = Math.max(...ds.communities.map((x) => x.demand_visits_per_week), 1);
  const HPV = geoMode ? 20 / maxD : 0.17;
  const cov = {};
  if (run?.metrics) for (const pc of run.metrics.per_cluster) cov[pc.community_id] = pc;
  const thr = run?.plan?.threshold_minutes;
  const siteH = {};
  ds.communities.forEach((cm, i) => {
    const [x, z] = pos[cm.node_id];
    const r = geoMode ? 0.7 + Math.sqrt(cm.demand_visits_per_week / maxD) * 2.2 : 2.0 + Math.sqrt(cm.demand_visits_per_week) / 5.6;
    const delay = 0.2 + i * 0.035;
    const pc = cov[cm.id];
    if (pc) {
      const segs = [[pc.within_threshold, c.s1, 1], [pc.served - pc.within_threshold, c.s2, 1], [pc.unmet, c.base, 0.42]].filter((sg) => sg[0] > 0);
      const tip = `Cluster ${cm.id} · ${pct(pc.coverage_pct)} within ${thr} min\n${pc.within_threshold} within · ${pc.served - pc.within_threshold} beyond · ${pc.unmet} unmet\nDemand ${pc.demand} visits/week`;
      let acc = 0;
      segs.forEach(([v, col, a], k) => {
        const last = k === segs.length - 1;
        items.push({ type: "prism", id: cm.id, x, z, r, sides: 12, y0: acc * HPV, y1: (acc + v) * HPV, color: col, alpha: a, cap: last, delay, pick: true, tip, hi: c.inkStrong,
          label: last ? (pc.coverage_pct < 1 ? `! ${cm.id}` : cm.id) : null, labelColor: c.inkStrong, labelSize: 10, labelPill: last && pc.coverage_pct < 1 ? c.crit : null });
        acc += v;
      });
    } else {
      items.push({ type: "prism", id: cm.id, x, z, r, sides: 12, y0: 0, y1: cm.demand_visits_per_week * HPV, color: c.s1, delay, pick: true, hi: c.inkStrong,
        tip: `Cluster ${cm.id} · ${cm.zone_class}\nDemand ${cm.demand_visits_per_week} visits/week`, label: cm.id, labelColor: c.inkStrong, labelSize: 10 });
    }
  });
  const sel = new Set(run?.selected_candidate_ids || []);
  ds.sites.forEach((st, i) => {
    const [x, z] = pos[st.node_id];
    const delay = 0.1 + i * 0.04;
    if (st.type === "existing") {
      siteH[st.id] = 4.4;
      items.push({ type: "prism", id: st.id, x, z, r: 2.9, sides: 4, rot: Math.PI / 4, y0: 0, y1: 4.4, color: c.site, delay, pick: true, hi: c.brand,
        tip: `${st.id} · existing site\nCapacity ${st.capacity_per_week} visits/week`, label: st.id, labelColor: c.inkStrong, labelSize: 10.5, labelWeight: 750 });
    } else if (sel.has(st.id)) {
      siteH[st.id] = 6.5;
      items.push({ type: "prism", id: st.id, x, z, r: 3, sides: 6, y0: 0, y1: 6.5, color: c.brand, glow: c.brand, delay: delay + 0.4, pick: true, hi: c.inkStrong,
        tip: `${st.id} · candidate zone OPENED\nCapacity ${st.capacity_per_week}/week · ${pkr(st.fixed_cost_pkr)}/week`, label: `NEW ${st.id}`, labelPill: c.brand, labelColor: c.dark ? "#10201b" : "#ffffff", labelSize: 10, labelWeight: 800, labelLift: 3 });
      items.push({ type: "ring", x, z, r: 4.2, color: c.brand, pulse: true, phase: i * 0.13 });
    } else {
      siteH[st.id] = 0.6;
      const hex = [];
      for (let k = 0; k < 6; k++) { const a = (Math.PI * 2 * k) / 6; hex.push([x + 3 * Math.cos(a), z + 3 * Math.sin(a)]); }
      ground.push({ type: "poly", pts: hex, stroke: st.eligible ? c.brand : c.axis, width: 1.4, dash: st.eligible ? [4, 3] : [], fill: st.eligible ? null : c.grid });
      ground.push({ type: "text", x, z: z + 5.4, text: st.eligible ? st.id : `${st.id} ✕`, color: c.ink, size: 10, weight: 600 });
      items.push({ type: "prism", id: st.id, x, z, r: 2.2, sides: 6, y0: 0, y1: 0.35, color: st.eligible ? c.grid : c.axis, alpha: 0.9, delay, pick: true, hi: c.brand,
        tip: `${st.id} · candidate zone\nCapacity ${st.capacity_per_week}/week · ${pkr(st.fixed_cost_pkr)}/week\n${st.eligible ? "Not opened in this plan" : "Not eligible"}` });
    }
  });
  if (run?.assignments && showAssign) {
    const light = c.dark ? "#9ec5f4" : c.s1;
    run.assignments.forEach((asg, i) => {
      const A = pos[nodeOf[asg.community_id]], B = pos[nodeOf[asg.site_id]];
      const d = Math.hypot(B[0] - A[0], B[1] - A[1]);
      const a = [A[0], 0.8, A[1]], b = [B[0], siteH[asg.site_id] || 1, B[1]];
      const mid = [(A[0] + B[0]) / 2, 5 + d * 0.33, (A[1] + B[1]) / 2];
      const pts = Array.from({ length: 15 }, (_, k) => Viz3D.bez(a, mid, b, k / 14));
      const within = asg.minutes <= thr;
      items.push({ type: "line", id: `${asg.community_id}>${asg.site_id}`, pts, color: within ? light : c.s2, alpha: within ? 0.5 : 0.9, width: 0.9 + Math.sqrt(asg.visits) / 4.2,
        delay: 1.2 + i * 0.01, phase: i * 0.17, pick: true,
        tip: `${asg.community_id} → ${asg.site_id}\n${asg.visits} visits/week · ${asg.minutes} min${within ? "" : `\nBeyond the ${thr}-minute threshold`}`,
        flow: { n: 1 + Math.round(asg.visits / 45), speed: 0.3, color: within ? light : c.s2, size: 0.55 } });
    });
  }
  const scene = new Viz3D.Scene(host, { height: (w) => Math.max(330, Math.min(560, w * 0.7)), radius: 67, yaw: -0.55, pitch: 0.92,
    label: title || "3D coverage map", halo: c.dark ? "#141618" : "#fffdf9" });
  scene.setData({ items, ground });
  return scene;
}

function mapSvg(run, { showAssign = false, title = "" } = {}) {
  const c = C();
  const ds = S.dataset;
  const W = 820, H = 660, pad = 22, k = 8;
  const pos = {};
  for (const n of ds.nodes) pos[n.id] = [pad + n.display_x * k, pad + n.display_y * k];
  const nodeOf = {};
  for (const cm of ds.communities) nodeOf[cm.id] = cm.node_id;
  for (const s2 of ds.sites) nodeOf[s2.id] = s2.node_id;
  const cov = {};
  if (run?.metrics) for (const pc of run.metrics.per_cluster) cov[pc.community_id] = pc;
  const sel = new Set(run?.selected_candidate_ids || []);
  const thr = run?.plan?.threshold_minutes;
  const onBrand = c.dark ? "#10201b" : "#ffffff";
  let s = `<svg class="map" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(title)}" style="background:${c.surface}"><title>${esc(title)}</title>`;
  for (const e of ds.edges) {
    const a = pos[e.from_node], b = pos[e.to_node];
    if (a && b) s += `<line class="fade-in" x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="${c.road}" stroke-width="2" stroke-linecap="round"/>`;
  }
  if (run?.assignments && showAssign) {
    for (const asg of run.assignments) {
      const a = pos[nodeOf[asg.community_id]], b = pos[nodeOf[asg.site_id]];
      const within = asg.minutes <= thr;
      const len = Math.hypot(b[0] - a[0], b[1] - a[1]).toFixed(1);
      s += `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="${within ? c.ink : c.s2}" stroke-opacity="${within ? 0.4 : 0.9}" stroke-width="${(1.2 + Math.sqrt(asg.visits) / 2.6).toFixed(2)}" stroke-linecap="round" stroke-dasharray="${len}" stroke-dashoffset="${len}" style="animation:dash 1.1s var(--ease) .3s forwards" data-tip="${esc(`${asg.community_id} → ${asg.site_id}\n${asg.visits} visits/week · ${asg.minutes} min${within ? "" : `\nBeyond the ${thr}-minute threshold`}`)}"/>`;
    }
  }
  ds.communities.forEach((cm, i) => {
    const [x, y] = pos[cm.node_id];
    const r = 7 + Math.sqrt(cm.demand_visits_per_week) / 1.5;
    const pc = cov[cm.id];
    const p = pc ? pc.coverage_pct : null;
    const tipTxt = pc ? `Cluster ${cm.id}\n${pct(p)} within ${thr} min (${pc.within_threshold} of ${pc.demand} visits)\nServed ${pc.served} · unmet ${pc.unmet}` : `Cluster ${cm.id}\nDemand ${cm.demand_visits_per_week} visits/week · ${cm.zone_class}`;
    s += `<g data-tip="${esc(tipTxt)}" class="fade-in" style="animation-delay:${(i * 0.02).toFixed(2)}s"><circle cx="${x}" cy="${y}" r="${r + 2}" fill="${c.surface}"/><circle cx="${x}" cy="${y}" r="${r}" fill="${run ? covColor(p, c) : c.s1}"/>`;
    if (run && p !== null && p < 1) s += `<circle cx="${x + r * 0.72}" cy="${y - r * 0.72}" r="6" fill="${c.crit}" stroke="${c.surface}" stroke-width="2"/><text x="${x + r * 0.72}" y="${y - r * 0.72 + 3.5}" text-anchor="middle" font-size="9" font-weight="800" fill="#fff">!</text>`;
    s += `<text x="${x}" y="${y + r + 13}" text-anchor="middle" font-size="11" font-weight="600" fill="${c.ink}">${esc(cm.id)}</text></g>`;
  });
  for (const st of ds.sites) {
    const [x, y] = pos[st.node_id];
    if (st.type === "existing") {
      s += `<g data-tip="${esc(`${st.id} · existing site\nCapacity ${st.capacity_per_week} visits/week`)}"><rect x="${x - 11}" y="${y - 11}" width="22" height="22" rx="5" fill="${c.surface}"/><rect x="${x - 9}" y="${y - 9}" width="18" height="18" rx="4" fill="${c.site}"/>`;
      s += `<path d="M${x - 4} ${y}h8M${x} ${y - 4}v8" stroke="${c.surface}" stroke-width="2" stroke-linecap="round"/><text x="${x}" y="${y - 15}" text-anchor="middle" font-size="11" font-weight="700" fill="${c.inkStrong}">${esc(st.id)}</text></g>`;
    } else {
      const chosen = sel.has(st.id);
      const d = `M ${x} ${y - 13} L ${x + 13} ${y} L ${x} ${y + 13} L ${x - 13} ${y} Z`;
      const tipTxt = `${st.id} · candidate zone\nCapacity ${st.capacity_per_week}/week · ${pkr(st.fixed_cost_pkr)}/week\n${!st.eligible ? "Not eligible" : chosen ? "OPENED in this plan" : "Not opened"}`;
      s += `<g data-tip="${esc(tipTxt)}"><path d="${d}" fill="${!st.eligible ? c.grid : chosen ? c.brand : c.surface}" stroke="${!st.eligible ? c.axis : c.brand}" stroke-width="2" ${chosen || !st.eligible ? "" : 'stroke-dasharray="4 3"'}/>`;
      if (!st.eligible) s += `<path d="M ${x - 5} ${y - 5} L ${x + 5} ${y + 5} M ${x + 5} ${y - 5} L ${x - 5} ${y + 5}" stroke="${c.ink}" stroke-width="2" stroke-linecap="round"/>`;
      if (chosen) s += `<rect x="${x - 17}" y="${y - 31}" width="34" height="15" rx="7.5" fill="${c.brand}"/><text x="${x}" y="${y - 20.5}" text-anchor="middle" font-size="9.5" font-weight="800" fill="${onBrand}">NEW</text>`;
      s += `<text x="${x}" y="${y + 26}" text-anchor="middle" font-size="11" font-weight="700" fill="${chosen ? c.brandInk : c.ink}">${esc(st.id)}</text></g>`;
    }
  }
  s += "</svg>";
  const legend = [
    `<span><span class="sw" style="background:${c.site}"></span>existing site</span>`,
    `<span><span class="sw" style="background:${c.brand}"></span>opened (NEW)</span>`,
    `<span><span class="sw" style="border:1.5px dashed ${c.brand}"></span>candidate, not opened</span>`,
    `<span><span class="sw" style="background:${c.grid};border:1px solid ${c.axis}"></span>ineligible</span>`,
  ];
  if (run) {
    legend.push(`<span>coverage <span class="scale">${c.seq.map((col) => `<i style="background:${col}"></i>`).join("")}</span> 0 → 100%</span>`);
    legend.push(`<span><span class="sw" style="background:${c.crit};border-radius:50%"></span>no visits within threshold</span>`);
    if (showAssign) legend.push(`<span><i class="ln" style="background:${c.ink};opacity:.5"></i>assigned within threshold</span><span><i class="ln" style="background:${c.s2}"></i>assigned beyond threshold</span>`);
  } else legend.push(`<span><span class="sw" style="background:${c.s1};border-radius:50%"></span>cluster (size = weekly demand)</span>`);
  return `<div class="chart-wrap">${s}</div><div class="legend">${legend.join("")}</div>`;
}

/* ---------- scenario builder ---------- */
const EXAMPLES = [
  "Budget Rs 3 lakh per week, 2 new units, within 45 minutes",
  "بجٹ ۳ لاکھ روپے، دو نئے مراکز، ۴۵ منٹ",
  "Equity first, 4.5 lakh, 3 new sites, 60 minutes",
  "Demand increases by 20%, 5 lakh budget, 3 new clinics",
  "Every cluster at least 10%, 7 lakh budget, 5 new units",
];
function renderExamples() {
  $("examples").innerHTML = EXAMPLES.map((t, i) => `<button type="button" class="example" data-i="${i}" dir="auto">${esc(t)}</button>`).join("");
  $("examples").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-i]");
    if (!b) return;
    $("askText").value = EXAMPLES[Number(b.dataset.i)];
    parseRequest();
  });
  const st = dsStats();
  $("f_units").max = st.eligible;
  $("f_units_hint").textContent = `${st.eligible} eligible candidate zones available`;
  $("f_budget_hint").textContent = `Each candidate zone costs ${pkr(st.costMin)}–${nf0.format(st.costMax)} per week.`;
}

const FIELD_IDS = { budget_pkr: "f_budget", max_new_units: "f_units", threshold_minutes: "f_threshold", demand_multiplier_pct: "f_demand",
  equity_min_pct: "f_equity", seed: "f_seed", min_coverage_pct: "f_mincov" };
const PAIRS = [["f_budget_r", "f_budget"], ["f_threshold_r", "f_threshold"], ["f_demand_r", "f_demand"], ["f_equity_r", "f_equity"], ["f_mincov_r", "f_mincov"]];

function setFill(r) { const span = Number(r.max) - Number(r.min); r.style.setProperty("--fill", `${span ? (100 * (Number(r.value) - Number(r.min))) / span : 0}%`); }
function syncRanges() {
  for (const [rid, nid] of PAIRS) {
    const r = $(rid), v = Number($(nid).value);
    if (!Number.isNaN(v)) r.value = Math.max(Number(r.min), Math.min(Number(r.max), v));
    setFill(r);
  }
  setFill($("s_count_r"));
  const p = readForm();
  $("pv_budget").textContent = Number.isFinite(p.budget_pkr) ? pkrShort(p.budget_pkr) : "—";
  $("pv_threshold").textContent = Number.isFinite(p.threshold_minutes) ? `${p.threshold_minutes} min` : "—";
  $("pv_demand").textContent = Number.isFinite(p.demand_multiplier_pct) ? `${p.demand_multiplier_pct}%` : "—";
  $("pv_equity").textContent = Number.isFinite(p.equity_min_pct) ? (p.equity_min_pct ? `${p.equity_min_pct}%` : "off") : "—";
  $("pv_mincov").textContent = Number.isFinite(p.min_coverage_pct) ? `${p.min_coverage_pct}%` : "—";
}

function setForm(p) {
  $("f_budget").value = p.budget_pkr; $("f_units").value = p.max_new_units; $("f_threshold").value = p.threshold_minutes;
  $("f_demand").value = p.demand_multiplier_pct; $("f_equity").value = p.equity_min_pct; $("f_seed").value = p.seed;
  $("f_mincov").value = p.min_coverage_pct ?? 60;
  document.querySelectorAll('input[name="policy"]').forEach((r) => { r.checked = r.value === p.policy; });
  $("minCovField").hidden = p.policy !== "cost_efficient";
  clearFieldErrors(); syncRanges();
}

function readForm() {
  const int = (id) => { const v = $(id).value.trim(); return v === "" ? NaN : Number(v); };
  const policy = document.querySelector('input[name="policy"]:checked')?.value || "coverage_first";
  return {
    dataset_version_id: S.dataset.manifest.id,
    budget_pkr: int("f_budget"), max_new_units: int("f_units"), threshold_minutes: int("f_threshold"),
    demand_multiplier_pct: int("f_demand"), equity_min_pct: int("f_equity"), policy, seed: int("f_seed"),
    min_coverage_pct: policy === "cost_efficient" ? int("f_mincov") : null,
  };
}

function clearFieldErrors() {
  for (const k of Object.keys(FIELD_IDS)) { const e = $(`e_${k}`); if (e) e.textContent = ""; $(FIELD_IDS[k]).removeAttribute("aria-invalid"); }
  $("formErr").hidden = true; $("formErr").innerHTML = "";
}

function clientValidate(p) {
  const bounds = { budget_pkr: [0, 100000000], max_new_units: [0, dsStats().eligible], threshold_minutes: [1, 240],
    demand_multiplier_pct: [1, 300], equity_min_pct: [0, 100], seed: [0, 2147483647] };
  if (p.policy === "cost_efficient") bounds.min_coverage_pct = [0, 100];
  const errs = {};
  for (const [k, [lo, hi]] of Object.entries(bounds)) {
    const v = p[k];
    if (!Number.isInteger(v)) errs[k] = "Enter a whole number.";
    else if (v < lo || v > hi) errs[k] = `Must be between ${nf0.format(lo)} and ${nf0.format(hi)}.`;
  }
  return errs;
}

function showFieldErrors(errs) {
  clearFieldErrors();
  const general = [];
  for (const [k, msg] of Object.entries(errs)) {
    const e = $(`e_${k}`);
    if (e) { e.textContent = msg; $(FIELD_IDS[k]).setAttribute("aria-invalid", "true"); } else general.push(msg);
  }
  if (general.length) { $("formErr").hidden = false; $("formErr").innerHTML = `${icon("alert", "sm")}<div>${general.map(esc).join("<br>")}</div>`; }
}

function invalidateReview() {
  if (S.reviewed) { S.reviewed = null; renderFlow(); }
  renderSummary();
}

function wireForm() {
  for (const [rid, nid] of PAIRS) {
    $(rid).addEventListener("input", () => { $(nid).value = $(rid).value; syncRanges(); invalidateReview(); });
    $(nid).addEventListener("input", () => { syncRanges(); invalidateReview(); });
  }
  document.querySelectorAll(".stepper button").forEach((b) => b.addEventListener("click", () => {
    const inp = $("f_units");
    const v = Math.max(0, Math.min(Number(inp.max), (Number(inp.value) || 0) + Number(b.dataset.step)));
    inp.value = v; invalidateReview();
  }));
  $("f_units").addEventListener("input", invalidateReview);
  $("f_seed").addEventListener("input", invalidateReview);
  document.querySelectorAll('input[name="policy"]').forEach((r) => r.addEventListener("change", () => {
    $("minCovField").hidden = readForm().policy !== "cost_efficient"; syncRanges(); invalidateReview();
  }));
  $("planForm").addEventListener("submit", (e) => { e.preventDefault(); reviewPlan(readForm()); });
  $("resetBtn").addEventListener("click", () => { setForm(defaultsPlan()); S.parse = null; $("parseOut").innerHTML = ""; invalidateReview(); toast("Form reset to the default plan."); });
  $("parseBtn").addEventListener("click", parseRequest);
  $("askText").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) parseRequest(); });
  $("s_count_r").addEventListener("input", () => { $("s_count").value = $("s_count_r").value; $("pv_count").textContent = $("s_count_r").value; setFill($("s_count_r")); });
  $("stressBtn").addEventListener("click", runStressSuite);
}

const FIELD_LABEL = { budget_pkr: "Budget", max_new_units: "New units", threshold_minutes: "Threshold", demand_multiplier_pct: "Demand",
  equity_min_pct: "Equity floor", policy: "Policy", seed: "Seed", min_coverage_pct: "Coverage target" };
function fieldValue(k, v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (k === "budget_pkr") return `${pkr(v)} / week`;
  if (k === "threshold_minutes") return `${v} min`;
  if (k === "equity_min_pct") return v ? `${v}% per cluster` : "off";
  if (["demand_multiplier_pct", "min_coverage_pct"].includes(k)) return `${v}%`;
  if (k === "policy") return { coverage_first: "Coverage first", equity_first: "Equity first", cost_efficient: "Cost efficient" }[v] || v;
  return String(v);
}

async function parseRequest() {
  const text = $("askText").value.trim();
  if (!text) { $("parseOut").innerHTML = `<div class="alert info">${icon("info", "sm")}<div>Type a request first, or pick an example.</div></div>`; return; }
  const btn = $("parseBtn"); btn.disabled = true;
  try {
    const out = await api("/plans/parse", { method: "POST", body: JSON.stringify({ text, dataset_version_id: S.dataset.manifest.id }) });
    S.parse = out;
    const rec = Object.entries(out.recognized).map(([k, v]) => `<span class="tag ok" data-tip="${esc(`Read from: “${v.text}”`)}">${icon("check", "sm")}${esc(FIELD_LABEL[k] || k)}: ${esc(fieldValue(k, v.value))}</span>`).join("");
    const defs = out.defaults_used.map((k) => `<span class="tag def">${esc(FIELD_LABEL[k] || k)}: ${esc(fieldValue(k, out.draft[k]))}</span>`).join("");
    const warns = out.warnings.map((w) => `<div class="alert warn">${icon("alert", "sm")}<div>${esc(w)}</div></div>`).join("");
    const errs = out.field_errors.map((e) => `<div class="alert err">${icon("x", "sm")}<div>${esc(FIELD_LABEL[e.field] || e.field)}: ${esc(e.message)}</div></div>`).join("");
    const lang = out.language === "ur" ? "Urdu" : out.language === "mixed" ? "Mixed" : "English";
    $("parseOut").innerHTML = `<div class="mt-1"><div class="small" style="font-weight:650;margin-bottom:.35rem">Understood · ${esc(lang)}</div>${rec || '<span class="muted small">nothing recognised</span>'}</div>
      ${defs ? `<div class="mt-h"><div class="small muted" style="margin-bottom:.3rem">Defaults used</div>${defs}</div>` : ""}${warns}${errs}
      <div class="source-note">${icon("info", "sm")}<span>Parser ${esc(out.parser)} · AI model used: ${out.ai_model_used ? "yes" : "no"}. Values were copied into the form below — check them, then review the plan.</span></div>`;
    setForm(out.draft);
    invalidateReview();
    if (out.field_errors.length) { const fe = {}; for (const e of out.field_errors) fe[e.field] = e.message; showFieldErrors(fe); }
    else toast(`Request read (${lang}). Review the plan when ready.`, "ok");
  } catch (e) {
    $("parseOut").innerHTML = `<div class="alert err">${icon("alert", "sm")}<div>Could not read the request (${esc(e.message)}). Use the form instead.</div></div>`;
  } finally { btn.disabled = false; }
}

async function createScenario(plan) {
  const errs = clientValidate(plan);
  if (Object.keys(errs).length) { const e = new Error("Fix the highlighted fields."); e.fieldErrors = errs; throw e; }
  try {
    return await api("/scenarios", { method: "POST", body: JSON.stringify({ plan }) });
  } catch (e) {
    if (e.body?.field_errors?.length) { const fe = {}; for (const f of e.body.field_errors) fe[f.field] = f.message; e.fieldErrors = fe; }
    else if (e.body?.message) e.fieldErrors = { _: e.body.message };
    throw e;
  }
}

function renderSummary() {
  if (!S.dataset) return;
  const p = S.reviewed ? S.reviewed.plan : readForm();
  const defs = new Set(S.parse && !S.reviewed ? S.parse.defaults_used : []);
  const keys = ["budget_pkr", "max_new_units", "threshold_minutes", "demand_multiplier_pct", "equity_min_pct", "policy"].concat(p.policy === "cost_efficient" ? ["min_coverage_pct"] : []);
  let html = `<dl class="kv">${keys.map((k) => `<dt>${esc(FIELD_LABEL[k])}</dt><dd>${esc(fieldValue(k, p[k]))}${defs.has(k) ? '<span class="tag def">default</span>' : ""}</dd>`).join("")}
    <dt>Dataset</dt><dd>${esc(p.dataset_version_id)}</dd></dl>`;
  if (S.reviewed) {
    html += `<div class="small muted mt-1" style="margin-bottom:.3rem">Plan hash you are confirming</div><div class="hashbox">${esc(S.reviewed.plan_hash)}</div>`;
    if (p.equity_min_pct > 0) html += `<div class="alert warn">${icon("alert", "sm")}<div>The ${p.equity_min_pct}% equity floor is a hard rule. If any cluster cannot meet it, the run is reported as infeasible — never relaxed.</div></div>`;
    html += `<p class="tiny muted mt-h">Confirming runs the <b>baseline</b>, <b>greedy benchmark</b> and <b>optimized</b> plan with these exact inputs.</p>`;
  }
  $("summaryBox").innerHTML = html;
  $("summaryState").textContent = S.running ? "Running…" : S.reviewed ? "Reviewed — ready to confirm" : "Not reviewed yet";
  const busy = S.running ? '<span class="spin"></span>' : "";
  $("summaryActions").innerHTML = S.reviewed
    ? `<div class="row"><button class="btn primary" id="confirmBtn" style="flex:1" ${S.running ? "disabled" : ""}>${busy || icon("play", "sm")}Confirm &amp; run</button><button class="btn" id="editBtn" ${S.running ? "disabled" : ""}>Edit</button></div>`
    : `<button class="btn dark block" id="reviewBtn">${icon("hash", "sm")}Review plan</button>`;
  $("confirmBtn")?.addEventListener("click", () => confirmAndRun(S.reviewed));
  $("editBtn")?.addEventListener("click", () => { S.reviewed = null; renderSummary(); renderFlow(); $("f_budget").focus(); });
  $("reviewBtn")?.addEventListener("click", () => reviewPlan(readForm()));
}

function renderFlow() {
  const done = (k) => S.runs[k] && TERMINAL.has(S.runs[k].status);
  const hasRuns = KINDS.some((k) => S.runs[k]);
  const allDone = KINDS.every((k) => !S.runs[k] || done(k)) && hasRuns;
  const steps = [
    ["Describe", true],
    ["Review", Boolean(S.reviewed) || hasRuns],
    ["Confirm & run", hasRuns && !S.reviewed],
    ["Results", allDone && !S.reviewed && !S.running],
  ];
  const active = steps.findIndex(([, d]) => !d);
  $("flow").innerHTML = steps.map(([label, d], i) => {
    const cls = d && (active === -1 || i < active) ? "done" : i === active ? "active" : "";
    return `${i ? `<div class="bar ${cls === "done" ? "done" : ""}"></div>` : ""}<div class="st ${cls}"><span class="n">${cls === "done" ? icon("check", "sm") : i + 1}</span>${esc(label)}</div>`;
  }).join("");
}

async function reviewPlan(plan) {
  showError(null);
  try {
    const scn = await createScenario(plan);
    S.reviewed = scn;
    clearFieldErrors(); renderSummary(); renderFlow();
    $("confirmBtn")?.focus();
  } catch (e) {
    if (e.fieldErrors) showFieldErrors(e.fieldErrors);
    toast(e.message, "err");
  }
}

async function confirmAndRun(scn, { stay = false } = {}) {
  if (S.running) return;
  S.running = true; renderSummary();
  try {
    const confirmed = await api(`/scenarios/${scn.scenario_id}/confirm`, { method: "POST", body: JSON.stringify({ plan_hash: scn.plan_hash }) });
    S.scenario = confirmed; S.reviewed = null;
    S.runs = { baseline: null, greedy: null, optimized: null };
    S.comparison = null; S.expl = {}; S.stress = null;
    saveSession(); renderFlow(); renderRunStatus();
    const submitted = {};
    for (const kind of ["baseline", "optimized", "greedy"]) {
      submitted[kind] = await api(`/scenarios/${confirmed.scenario_id}/runs`, {
        method: "POST", headers: { "Idempotency-Key": `${confirmed.scenario_id}-${kind}` },
        body: JSON.stringify({ kind, plan_hash: confirmed.plan_hash }),
      });
      S.runs[kind] = submitted[kind];
    }
    saveSession(); renderRunStatus();
    await Promise.all(Object.values(submitted).map((r) => pollRun(r.run_id)));
    S.running = false;
    await afterRuns();
    const o = S.runs.optimized;
    if (o?.status === "COMPLETED") toast(`Plan solved and audited: ${pct(o.metrics.coverage_pct.value)} of visits within ${o.plan.threshold_minutes} min.`, "ok");
    else toast(`Optimized plan: ${o?.status || "not run"}. See the diagnostic.`, "err");
    if (!stay) location.hash = "#results";
  } catch (e) {
    toast(`Run failed to start: ${e.message}`, "err");
  } finally { S.running = false; renderSummary(); renderFlow(); }
}

async function pollRun(runId) {
  let delay = 1000;
  const t0 = Date.now();
  for (;;) {
    await sleep(delay);
    const run = await api(`/runs/${runId}`);
    S.runs[run.kind] = run;
    renderRunStatus(t0);
    if (TERMINAL.has(run.status)) return run;
    delay = Math.min(delay * 1.5, 5000);
  }
}

function trackFor(r) {
  const s = r.status, stage = r.stage;
  const bad = ["FAILED", "NO_SOLUTION", "TIMED_OUT", "INTERRUPTED", "CANCELLED"].includes(s);
  if (s === "COMPLETED") return ["ok", "ok", "ok", "ok"];
  if (bad) return s === "NO_SOLUTION" || s === "TIMED_OUT" ? ["ok", "bad", "", ""] : ["ok", "bad", "bad", "bad"];
  if (s === "QUEUED") return ["pulse", "", "", ""];
  if (s === "AUDITING" || stage === "auditing") return ["on", "on", "pulse", ""];
  return ["on", "pulse", "", ""];
}

function renderRunStatus(t0) {
  const items = KINDS.map((k) => S.runs[k]).filter(Boolean);
  if (!items.length) { $("runStatus").innerHTML = `<p class="small muted" style="margin:0">Runs start after you confirm a reviewed plan.</p>`; return; }
  $("runStatus").innerHTML = `<div class="runs">${items.map((r) => {
    const live = !TERMINAL.has(r.status);
    const time = live && t0 ? `${Math.round((Date.now() - t0) / 1000)} s` : r.runtime_ms !== undefined ? `${nf0.format(r.runtime_ms)} ms` : "";
    return `<div class="run"><div class="top"><b>${esc(KIND_LABEL[r.kind])}</b><span class="tiny muted">${esc(KIND_DESC[r.kind])}</span>
        <span class="right">${statusPill(r.status)}${live ? `<button class="btn ghost sm" data-cancel="${esc(r.run_id)}">Cancel</button>` : ""}</span></div>
      <div class="track" aria-hidden="true">${trackFor(r).map((c) => `<i class="${c}"></i>`).join("")}</div>
      <div class="meta">Queued → Solving → Auditing → Done${time ? ` · ${esc(time)}` : ""}${r.solver_status ? ` · solver ${esc(r.solver_status)}` : ""}${r.audit ? ` · audit ${r.audit.passed ? "passed" : "FAILED"}` : ""}</div></div>`;
  }).join("")}</div>`;
  $("runStatus").querySelectorAll("[data-cancel]").forEach((b) => b.addEventListener("click", async () => {
    try { await api(`/runs/${b.dataset.cancel}/cancel`, { method: "POST" }); toast("Cancellation requested."); } catch (e) { toast(e.message, "err"); }
  }));
}

async function afterRuns() {
  S.comparison = null; S.expl = {};
  const b = S.runs.baseline, o = S.runs.optimized;
  if (b?.status === "COMPLETED" && o?.status === "COMPLETED") {
    try {
      const body = (lang) => JSON.stringify({ base_run_id: b.run_id, alt_run_id: o.run_id, lang });
      S.comparison = { en: await api("/comparisons", { method: "POST", body: body("en") }), ur: await api("/comparisons", { method: "POST", body: body("ur") }) };
    } catch (e) { toast(`Comparison failed: ${e.message}`, "err"); }
  }
  if (o?.status === "COMPLETED") {
    for (const lang of ["en", "ur"]) {
      try { S.expl[lang] = (await api(`/runs/${o.run_id}/explanation?lang=${lang}`)).explanation; } catch { /* shown as unavailable */ }
    }
  }
  if (!location.hash.startsWith("#results")) $("navResultsBadge").hidden = false;
  renderResults(); renderReport(); renderStress(); renderFlow(); renderDesk();
}

/* ---------- comparison ---------- */
const KPI_DEFS = [
  { key: "served_rate_pct", title: "Demand served", ic: "users", fk: "pct", fmt: pct, d: (v) => `${nf1.format(v)} pp`, better: "up" },
  { key: "unmet", title: "Unmet visits / week", ic: "alert", fk: "num", fmt: num, d: num, better: "down", eps: 0.5 },
  { key: "worst_cluster_coverage_pct", title: "Worst-served cluster", ic: "scale", fk: "pct", fmt: pct, d: (v) => `${nf1.format(v)} pp`, better: "up" },
  { key: "mean_travel_min", title: "Average assigned travel", ic: "clock", fk: "mins", fmt: mins, d: (v) => `${nf1.format(v)} min`, better: "down" },
  { key: "equity_gap_pp", title: "Equity gap", ic: "scale", fk: "pp", fmt: (v) => (v === null ? "n/a" : `${nf1.format(v)} pp`), d: (v) => `${nf1.format(v)} pp`, better: "down" },
  { key: "cost_pkr", title: "Weekly cost", ic: "coins", fk: "pkr", fmt: pkr, d: pkr, better: "none", eps: 0.5 },
];

function kpiTile(def, base, alt, greedy) {
  const mb = base?.metrics?.[def.key], ma = alt.metrics[def.key], mg = greedy?.metrics?.[def.key];
  const d = mb && ma.value !== null && mb.value !== null ? ma.value - mb.value : null;
  const counts = ma.numerator !== null && ma.numerator !== undefined && ma.denominator ? `${num(ma.numerator)} / ${num(ma.denominator)}` : "";
  const worst = def.key === "worst_cluster_coverage_pct" && ma.community_id ? `<small>${esc(placeName(ma.community_id))}</small>` : "";
  const tipTxt = `${def.title}\nOptimized: ${def.fmt(ma.value)}${counts ? ` (${counts})` : ""}\nBaseline: ${mb ? def.fmt(mb.value) : "n/a"}\nGreedy: ${mg ? def.fmt(mg.value) : "n/a"}`;
  return `<div class="tile" data-tip="${esc(tipTxt)}"><div class="lbl">${icon(def.ic, "sm")}${esc(def.title)}</div>
    <div class="val">${ma.value === null ? "n/a" : countSpan(ma.value, def.fk)}${worst}</div>
    <div class="cmp">${deltaBadge(d, def.better, def.d, def.eps ?? 0.05)}<span>vs baseline ${esc(mb ? def.fmt(mb.value) : "n/a")}</span></div>
    <div class="meta">Greedy ${esc(mg ? def.fmt(mg.value) : "n/a")}</div></div>`;
}

function diagnosticCard(r) {
  const hints = (r.error?.hints || []).map((h) => `<li>${esc(h)}</li>`).join("");
  return `<div class="card mt-1" style="border-color:var(--crit-line)"><div class="card-h" style="background:var(--crit-bg);border-radius:var(--radius) var(--radius) 0 0">
      <div class="ic" style="background:var(--card);color:var(--crit-ink)">${icon("alert")}</div><div><h2>${esc(KIND_LABEL[r.kind])} — ${esc(r.status === "NO_SOLUTION" ? "no feasible plan" : r.status.toLowerCase())}</h2>
      <p class="desc">${esc(r.error?.reason || "No allocation was found.")} No numbers are shown for this plan.</p></div></div>
    <div class="card-b">${hints ? `<ul class="small" style="margin:0;padding-left:1.1rem">${hints}</ul>` : ""}
      <p class="tiny muted mt-h" style="margin-bottom:0">The confirmed scenario was not changed automatically. Adjust it in the <a href="#plan">Scenario builder</a>.</p></div></div>`;
}

function renderResults() {
  const box = $("resultsBox");
  box.classList.add("anim");
  const b = S.runs.baseline, o = S.runs.optimized, g = S.runs.greedy;
  if (!o && !b) {
    box.innerHTML = `<div class="card">${emptyState("chart", "No results yet", "Build and confirm a scenario to compare the baseline, greedy and optimized plans.", `<a class="btn primary" href="#plan">${icon("play", "sm")}Start a scenario</a>`)}</div>`;
    return;
  }
  const p = (o || b).plan;
  const okB = b?.status === "COMPLETED", okO = o?.status === "COMPLETED", okG = g?.status === "COMPLETED";
  const chips = [`${icon("coins", "sm")}${pkr(p.budget_pkr)}/week`, `${icon("plus", "sm")}up to ${p.max_new_units} new units`, `${icon("clock", "sm")}${p.threshold_minutes}-min threshold`,
    `${icon("users", "sm")}demand ${p.demand_multiplier_pct}%`, `${icon("scale", "sm")}equity floor ${p.equity_min_pct ? `${p.equity_min_pct}%` : "off"}`, `${icon("target", "sm")}${fieldValue("policy", p.policy)}`];
  let html = `<div class="card"><div class="card-h"><div class="ic">${icon("hash")}</div><div><h2>Confirmed plan</h2><p class="desc">Plan hash <span class="mono">${esc(short(S.scenario?.plan_hash || o?.plan_hash))}</span> · ${esc(S.dataset.manifest.district_label)} · one modeled week</p></div>
      <div class="right" data-local-only><a class="btn sm" href="#plan">${icon("sliders", "sm")}New scenario</a></div></div>
    <div class="card-b"><div class="row">${chips.map((c) => `<span class="chip">${c}</span>`).join("")}</div></div>
    <div class="card-b flush table-wrap" style="border-top:1px solid var(--line)"><table><thead><tr><th>Plan</th><th>Status</th><th>Solver</th><th>Independent audit</th><th>New sites</th><th class="num">Runtime</th></tr></thead><tbody>${
      KINDS.map((k) => {
        const r = S.runs[k];
        if (!r) return "";
        const a = r.audit ? `${r.audit.checks.filter((c) => c.passed).length}/${r.audit.checks.length}` : "";
        return `<tr><td><b>${esc(KIND_LABEL[k])}</b> <span class="muted tiny">${esc(KIND_DESC[k])}</span></td><td>${statusPill(r.status)}</td>
          <td>${esc(r.solver_status || "—")}${r.optimality ? ` <span class="muted tiny">${r.optimality === "proven" ? "proven optimal" : "not proven optimal"}</span>` : ""}</td>
          <td>${r.audit ? (r.audit.passed ? `<span class="status ok">${icon("shield")}Passed ${a}</span>` : `<span class="status bad">${icon("x")}Failed ${a}</span>`) : "—"}</td>
          <td>${esc((r.selected_candidate_ids || []).join(", ") || "none")}</td><td class="num">${r.runtime_ms !== undefined ? `${nf0.format(r.runtime_ms)} ms` : "—"}</td></tr>`;
      }).join("")}</tbody></table></div></div>`;

  for (const r of [b, o, g]) if (r && TERMINAL.has(r.status) && r.status !== "COMPLETED") html += diagnosticCard(r);
  if (b?.status === "NO_SOLUTION" && okO) html += `<div class="alert warn mt-1">${icon("alert", "sm")}<div>The baseline is infeasible under this policy, so the optimized plan is shown without a baseline comparison.</div></div>`;

  if (okO) {
    const cov = o.metrics.coverage_pct;
    const d = okB ? cov.value - b.metrics.coverage_pct.value : null;
    const acpv = S.comparison?.en?.additional_cost_per_added_covered_visit;
    html += `<div class="card mt-1"><div class="card-b"><div class="figure">
        <div><div class="big-lbl">Visits reached within ${p.threshold_minutes} minutes · optimized plan</div>
          <div class="row" style="align-items:flex-end;gap:.8rem"><div class="big">${countSpan(cov.value, "pct")}</div>${d !== null ? `<div style="margin-bottom:.4rem">${deltaBadge(d, "up", (v) => `${nf1.format(v)} pp vs baseline`)}</div>` : ""}</div>
          <div class="big-sub">${num(cov.numerator)} of ${num(cov.denominator)} weekly visits${acpv?.value !== null && acpv?.value !== undefined ? ` · about <b>${pkr(Math.round(acpv.value))}</b> per added covered visit` : ""}</div></div>
        <div>${bars3d(coverageRows())}</div>
      </div></div></div>`;
    html += `<div class="tiles six mt-1 anim">${KPI_DEFS.map((def) => kpiTile(def, okB ? b : null, o, okG ? g : null)).join("")}</div>`;

    html += `<div class="grid g-main-side mt-1">
      <div class="card"><div class="card-h"><div class="ic">${icon("cube")}</div><div><h2>Coverage map</h2><p class="desc">${S.mapMode === "3d" ? "Column = weekly demand split into within / beyond / unmet · drag to rotate" : "Hover a cluster, site or line for details"}</p></div>
        <div class="right"><div class="seg" role="group" aria-label="Map view"><button data-mode="3d" aria-pressed="${S.mapMode === "3d"}">3D</button><button data-mode="2d" aria-pressed="${S.mapMode === "2d"}">2D</button></div>
          <div class="seg" role="group" aria-label="Plan shown on map">${KINDS.map((k) => `<button data-map="${k}" aria-pressed="${S.mapKind === k}">${esc(k === "optimized" ? "Optimized" : k === "greedy" ? "Greedy" : "Baseline")}</button>`).join("")}</div></div></div>
        <div class="card-b"><label class="small row" style="margin-bottom:.6rem;font-weight:550"><input type="checkbox" id="showAssign" ${S.showAssign ? "checked" : ""}> Show assignments</label><div id="resMap"></div></div></div>
      <div class="stack">
        <div class="card"><div class="card-h"><div class="ic">${icon("spark")}</div><div><h2>Explanation</h2><p class="desc">Generated from audited numbers</p></div>
          <div class="right"><div class="seg" role="group" aria-label="Language"><button data-lang="en" aria-pressed="${S.lang === "en"}">English</button><button data-lang="ur" aria-pressed="${S.lang === "ur"}" lang="ur">اردو</button></div></div></div>
          <div class="card-b" id="explBox"></div></div>
        <div class="card"><div class="card-h"><div class="ic">${icon("shield")}</div><div><h2>Independent audit</h2><p class="desc">Recomputed from the saved result, without the solver</p></div></div>
          <div class="card-b">${auditHtml(o)}</div></div>
      </div></div>`;

    html += `<div class="grid g-2 mt-1">
      <div class="card"><div class="card-h"><div class="ic">${icon("building")}</div><div><h2>Why these sites?</h2><p class="desc">What each new site does — and what is lost without it (re-solved and audited)</p></div></div>
        <div class="card-b" id="impactBox"><div class="skeleton"></div></div></div>
      <div class="card"><div class="card-h"><div class="ic">${icon("route")}</div><div><h2>Community journeys</h2><p class="desc">Travel time to the nearest open site, before and after</p></div></div>
        <div class="card-b" id="journeysBox"></div></div></div>`;

    html += `<div class="card mt-1"><div class="card-h"><div class="ic">${icon("chart")}</div><div><h2>${S.geo ? "Coverage by tehsil" : "Coverage by cluster"}</h2><p class="desc">Share of ${S.geo ? "each tehsil's" : "each cluster's"} visits within ${p.threshold_minutes} min — baseline → optimized</p></div>
        <div class="right"><div class="seg" role="group" aria-label="Sort clusters"><button data-sort="gain" aria-pressed="${S.sortBy === "gain"}">By gain</button><button data-sort="cov" aria-pressed="${S.sortBy === "cov"}">By coverage</button><button data-sort="id" aria-pressed="${S.sortBy === "id"}">By ID</button></div></div></div>
      <div class="card-b" id="dumbbell"></div>
      <details class="more"><summary>Show data table</summary><div class="table-wrap" id="dumbbellTable"></div></details></div>`;

    html += `<div class="card mt-1"><div class="card-h"><div class="ic">${icon("coins")}</div><div><h2>Budget trade-off</h2><p class="desc">Coverage reached at each weekly budget · every point is a separate optimized, audited run</p></div></div>
      <div class="card-b" id="tradeoffBox"><div class="skeleton" style="height:240px"></div><p class="tiny muted mt-h">Solving 18 scenarios on this computer…</p></div>
      <details class="more"><summary>Show data table</summary><div class="table-wrap" id="tradeoffTable"></div></details></div>`;

    html += `<div class="grid g-2 mt-1">
      <div class="card"><div class="card-h"><div class="ic">${icon("building")}</div><div><h2>Allocation by site</h2><p class="desc">Weekly visits assigned; bar = optimized utilisation</p></div></div>
        <div class="card-b flush table-wrap">${allocationTable(okB ? b : null, okG ? g : null, o)}</div></div>
      <div class="card"><div class="card-h"><div class="ic">${icon("cpu")}</div><div><h2>Objective stages</h2><p class="desc">Each proven optimum is fixed before the next stage</p></div></div>
        <div class="card-b flush table-wrap">${stagesTable()}</div>
        ${okG && g.greedy_trace ? `<div class="card-f small"><b>Greedy picks:</b> ${g.greedy_trace.map((t) => `${esc(t.added)} (+${t.gain_within_visits} visits for ${esc(pkr(t.cost_pkr))})`).join(" → ") || "none"}</div>` : ""}</div></div>`;

    html += `<div class="card mt-1" data-local-only><div class="card-h"><div class="ic">${icon("coins")}</div><div><h2>What if the budget changes?</h2><p class="desc">Other values stay the same; you confirm the new plan hash before it runs</p></div></div>
      <div class="card-b"><div class="field" style="margin-bottom:.6rem"><label for="wi_r">New weekly budget <span class="val-pill" id="wi_v">${esc(pkrShort(p.budget_pkr))}</span></label>
        <input type="range" id="wi_r" min="0" max="1000000" step="10000" value="${Math.min(p.budget_pkr, 1000000)}"></div>
        <div class="row"><button class="btn dark" id="wi_btn">${icon("hash", "sm")}Review this budget</button><span class="tiny muted" id="wi_note"></span></div>
        <div id="wi_box"></div></div></div>`;

    html += `<div class="card mt-1" data-local-only><div class="card-h"><div class="ic">${icon("pen")}</div><div><h2>Planner's review</h2><p class="desc">The model advises; people decide. Your judgement is saved on this computer and printed in the report.</p></div></div>
      <div class="card-b" id="reviewBox"></div></div>`;
  }
  box.innerHTML = html;
  if (!okO) return;

  const drawMap = () => {
    const run = S.runs[S.mapKind];
    if (run?.status === "COMPLETED") mountMap($("resMap"), run, { showAssign: S.showAssign, mode: S.mapMode, title: `Coverage map: ${S.mapKind} plan` });
    else $("resMap").innerHTML = `<p class="muted small">No completed ${esc(S.mapKind)} result to show.</p>`;
  };
  drawMap();
  box.querySelectorAll("[data-map]").forEach((btn) => btn.addEventListener("click", () => {
    S.mapKind = btn.dataset.map;
    box.querySelectorAll("[data-map]").forEach((x) => x.setAttribute("aria-pressed", String(x === btn)));
    drawMap();
  }));
  $("showAssign").addEventListener("change", (e) => { S.showAssign = e.target.checked; drawMap(); });
  box.querySelectorAll("[data-mode]").forEach((btn) => btn.addEventListener("click", () => {
    S.mapMode = btn.dataset.mode;
    box.querySelectorAll("[data-mode]").forEach((x) => x.setAttribute("aria-pressed", String(x === btn)));
    drawMap();
  }));
  animateCounts(box);
  renderJourneys(okB ? b : null, o);
  if (!PUBLIC_DEMO) renderReview(o);
  loadImpact(o);
  loadTradeoff(o);

  const drawExpl = () => {
    const e = S.expl[S.lang];
    const cmp = S.comparison?.[S.lang]?.explanation || [];
    const rtl = S.lang === "ur";
    $("explBox").innerHTML = e
      ? `<div class="expl" ${rtl ? 'dir="rtl" lang="ur"' : ""}>${cmp.map((s) => `<p class="lead">${esc(s)}</p>`).join("")}${e.sentences.map((s) => `<p>${esc(s)}</p>`).join("")}</div>
         <div class="source-note">${icon("shield", "sm")}<span>Deterministic template filled from evidence packet <span class="mono">${esc(short(e.packet_sha256))}</span>. No language model wrote these numbers.${e.review_note ? ` ${esc(e.review_note)}` : ""}</span></div>`
      : `<p class="muted small">Explanation unavailable.</p>`;
  };
  drawExpl();
  box.querySelectorAll("[data-lang]").forEach((btn) => btn.addEventListener("click", () => {
    S.lang = btn.dataset.lang;
    box.querySelectorAll("[data-lang]").forEach((x) => x.setAttribute("aria-pressed", String(x === btn)));
    drawExpl();
  }));

  const byTehsil = (r) => {
    if (!r || !S.geo) return r;
    const tOf = Object.fromEntries(S.geo.clusters.map((x) => [x.id, x.tehsil]));
    const agg = {};
    for (const pc of r.metrics.per_cluster) {
      const t = tOf[pc.community_id] || "?";
      const a = agg[t] || (agg[t] = { community_id: t, demand: 0, served: 0, within_threshold: 0, unmet: 0 });
      a.demand += pc.demand; a.served += pc.served; a.within_threshold += pc.within_threshold; a.unmet += pc.unmet;
    }
    for (const a of Object.values(agg)) a.coverage_pct = a.demand ? (100 * a.within_threshold) / a.demand : null;
    return { ...r, metrics: { ...r.metrics, per_cluster: Object.values(agg) } };
  };
  const drawDumbbell = () => { const out = dumbbell(byTehsil(okB ? b : null), byTehsil(o)); $("dumbbell").innerHTML = out.svg; $("dumbbellTable").innerHTML = out.table; };
  drawDumbbell();
  box.querySelectorAll("[data-sort]").forEach((btn) => btn.addEventListener("click", () => {
    S.sortBy = btn.dataset.sort;
    box.querySelectorAll("[data-sort]").forEach((x) => x.setAttribute("aria-pressed", String(x === btn)));
    drawDumbbell();
  }));

  if (PUBLIC_DEMO) return;
  const wi = $("wi_r"); setFill(wi);
  wi.addEventListener("input", () => { $("wi_v").textContent = pkrShort(Number(wi.value)); setFill(wi); $("wi_box").innerHTML = ""; });
  $("wi_btn").addEventListener("click", async () => {
    const plan = { ...p, budget_pkr: Number(wi.value) };
    try {
      const scn = await createScenario(plan);
      S.reviewed = scn; S.parse = null; setForm(plan); renderSummary(); renderFlow();
      $("wi_box").innerHTML = `<div class="alert info mt-1">${icon("hash", "sm")}<div style="flex:1">Reviewed: ${esc(pkr(plan.budget_pkr))}/week, everything else unchanged.<div class="hashbox mt-h">${esc(scn.plan_hash)}</div>
        <div class="row mt-h"><button class="btn primary" id="wiConfirm">${icon("play", "sm")}Confirm &amp; run</button></div></div></div>`;
      $("wiConfirm").addEventListener("click", () => confirmAndRun(scn));
      $("wiConfirm").focus();
    } catch (e) { $("wi_box").innerHTML = `<div class="alert err mt-1">${icon("alert", "sm")}<div>${esc(e.message)}</div></div>`; }
  });
}

function auditHtml(r) {
  const passed = r.audit.passed;
  const n = r.audit.checks.filter((c) => c.passed).length;
  return `<div class="audit-banner ${passed ? "" : "bad"}"><div class="ring">${icon(passed ? "shield" : "alert", "lg")}</div>
      <div><b>${passed ? "All checks passed" : "Audit failed"}</b><div class="small">${n} of ${r.audit.checks.length} checks · result <span class="mono">${esc(short(r.result_sha256))}</span></div></div></div>
    <div class="audit-grid">${r.audit.checks.map((c) => `<div class="audit-item" data-tip="${esc(`${c.id}: ${c.name}\nExpected: ${JSON.stringify(c.expected)}\nActual: ${JSON.stringify(c.actual)}`)}"><span class="mk ${c.passed ? "ok" : "bad"}">${icon(c.passed ? "check" : "x")}</span><span>${esc(c.name)} <code>${esc(c.id)}</code></span></div>`).join("")}</div>`;
}

function dumbbell(base, alt) {
  const c = C();
  const bmap = {}; if (base) for (const r of base.metrics.per_cluster) bmap[r.community_id] = r;
  const rows = alt.metrics.per_cluster.map((r) => ({ ...r, base: bmap[r.community_id]?.coverage_pct ?? null }));
  if (S.sortBy === "gain") rows.sort((a, d) => ((d.coverage_pct - (d.base ?? 0)) - (a.coverage_pct - (a.base ?? 0))) || d.coverage_pct - a.coverage_pct);
  else if (S.sortBy === "cov") rows.sort((a, d) => d.coverage_pct - a.coverage_pct || a.community_id.localeCompare(d.community_id));
  const rowH = 24, left = S.geo ? 118 : 48, right = 66, top = 30, W = 760;
  const H = top + rows.length * rowH + 24;
  const x = (v) => left + ((W - left - right) * (v || 0)) / 100;
  const floor = alt.plan.equity_min_pct;
  const spline = 'calcMode="spline" keyTimes="0;1" keySplines="0.2 0.7 0.2 1"';
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Coverage within threshold by cluster, baseline and optimized. Data table available below."><title>Coverage by cluster</title>`;
  for (const t of [0, 25, 50, 75, 100]) s += `<line x1="${x(t)}" y1="${top - 8}" x2="${x(t)}" y2="${H - 20}" stroke="${c.grid}"/><text x="${x(t)}" y="${H - 6}" font-size="11" text-anchor="middle" fill="${c.ink}">${t}%</text>`;
  if (floor > 0) s += `<line x1="${x(floor)}" y1="${top - 12}" x2="${x(floor)}" y2="${H - 20}" stroke="${c.warn}" stroke-width="1.5" stroke-dasharray="5 4"/><text x="${x(floor) + 4}" y="${top - 14}" font-size="11" fill="${c.warnInk}">equity floor ${floor}%</text>`;
  s += `<g font-size="11" fill="${c.ink}"><circle cx="${left}" cy="12" r="5" fill="${c.base}"/><text x="${left + 10}" y="16">baseline</text><circle cx="${left + 84}" cy="12" r="5" fill="${c.s1}"/><text x="${left + 94}" y="16">optimized</text></g>`;
  rows.forEach((r, i) => {
    const y = top + i * rowH + rowH / 2;
    const gain = r.base === null ? null : r.coverage_pct - r.base;
    const from = x(r.base ?? 0), to = x(r.coverage_pct);
    const begin = `${(0.15 + i * 0.03).toFixed(2)}s`;
    const tipTxt = `Cluster ${r.community_id} · demand ${r.demand}/week\nBaseline ${pct(r.base)} → optimized ${pct(r.coverage_pct)}${gain !== null ? ` (${gain >= 0 ? "+" : ""}${nf1.format(gain)} pp)` : ""}\n${r.within_threshold} visits within threshold · ${r.unmet} unmet`;
    s += `<g data-tip="${esc(tipTxt)}"><rect x="0" y="${y - rowH / 2}" width="${W}" height="${rowH}" fill="transparent"/>`;
    s += `<text x="${left - 12}" y="${y + 4}" font-size="11.5" font-weight="600" text-anchor="end" fill="${c.inkStrong}">${esc(r.community_id)}</text>`;
    s += `<line x1="${from}" y1="${y}" x2="${from}" y2="${y}" stroke="${c.axis}" stroke-width="2" stroke-linecap="round"><animate attributeName="x2" from="${from}" to="${to}" dur="0.9s" begin="${begin}" fill="freeze" ${spline}/></line>`;
    if (r.base !== null) s += `<circle cx="${from}" cy="${y}" r="6" fill="${c.base}" stroke="${c.card}" stroke-width="2"/>`;
    s += `<circle cx="${from}" cy="${y}" r="6" fill="${c.s1}" stroke="${c.card}" stroke-width="2"><animate attributeName="cx" from="${from}" to="${to}" dur="0.9s" begin="${begin}" fill="freeze" ${spline}/></circle>`;
    if (gain !== null && Math.abs(gain) >= 0.05) s += `<text class="fade-in" style="animation-delay:${(0.9 + i * 0.03).toFixed(2)}s" x="${W - right + 12}" y="${y + 4}" font-size="11" fill="${c.ink}">${gain > 0 ? "+" : "−"}${nf1.format(Math.abs(gain))} pp</text>`;
    s += "</g>";
  });
  s += "</svg>";
  const table = `<table><thead><tr><th>Cluster</th><th class="num">Demand</th><th class="num">Baseline %</th><th class="num">Optimized %</th><th class="num">Change (pp)</th><th class="num">Within threshold</th><th class="num">Unmet</th></tr></thead><tbody>${
    rows.map((r) => `<tr><td>${esc(r.community_id)}</td><td class="num">${r.demand}</td><td class="num">${pct(r.base)}</td><td class="num">${pct(r.coverage_pct)}</td><td class="num">${r.base === null ? "n/a" : nf1.format(r.coverage_pct - r.base)}</td><td class="num">${r.within_threshold}</td><td class="num">${r.unmet}</td></tr>`).join("")
  }</tbody></table>`;
  return { svg: s, table };
}

function allocationTable(base, greedy, alt) {
  const load = (run) => { const m = {}; if (run) for (const a of run.assignments) m[a.site_id] = (m[a.site_id] || 0) + a.visits; return m; };
  const lb = load(base), lg = load(greedy), lo = load(alt);
  const sel = new Set(alt.selected_candidate_ids);
  const sites = S.dataset.sites.filter((s) => s.type === "existing" || sel.has(s.id) || greedy?.selected_candidate_ids.includes(s.id));
  return `<table><thead><tr><th>Site</th><th class="num">Capacity</th><th class="num">Baseline</th><th class="num">Greedy</th><th>Optimized</th></tr></thead><tbody>${
    sites.map((s) => {
      const u = s.capacity_per_week ? (100 * (lo[s.id] || 0)) / s.capacity_per_week : 0;
      return `<tr class="${sel.has(s.id) ? "hl" : ""}"><td><b>${esc(s.label)}</b>${sel.has(s.id) ? ' <span class="status ok" style="margin-left:.3rem">NEW</span>' : ` <span class="muted tiny">${esc(s.type)}</span>`}</td>
        <td class="num">${s.capacity_per_week}</td><td class="num">${base ? lb[s.id] || 0 : "n/a"}</td><td class="num">${greedy ? lg[s.id] || 0 : "n/a"}</td>
        <td data-tip="${esc(`${s.id}: ${lo[s.id] || 0} of ${s.capacity_per_week} visits/week (${nf1.format(u)}% used)`)}"><span class="meter ${u >= 99.9 ? "full" : ""}"><i style="width:${u}%"></i></span>${lo[s.id] || 0}</td></tr>`;
    }).join("")
  }</tbody></table>`;
}

function stagesTable() {
  const rows = [];
  for (const k of KINDS) {
    const r = S.runs[k];
    if (!r?.objective_stages?.length) continue;
    r.objective_stages.forEach((st, i) => rows.push(`<tr><td>${i === 0 ? `<b>${esc(KIND_LABEL[k])}</b>` : ""}</td><td>${i + 1}. ${st.sense === "max" ? "Maximize" : "Minimize"} ${esc(st.label)}</td><td>${st.status === "OPTIMAL" ? `<span class="status ok">${icon("check")}Optimal</span>` : esc(st.status)}</td><td class="num">${st.value === null ? "—" : num(st.value)}</td></tr>`));
  }
  return `<table><thead><tr><th>Plan</th><th>Stage</th><th>Status</th><th class="num">Fixed value</th></tr></thead><tbody>${rows.join("")}</tbody></table>`;
}

/* ---------- stress lab ---------- */
async function runStressSuite() {
  const ok = S.runs.baseline?.status === "COMPLETED" && S.runs.optimized?.status === "COMPLETED";
  if (!ok) { toast("Run a scenario first: the stress suite needs completed baseline and optimized plans.", "err"); return; }
  const seed = Number($("s_seed").value), count = Number($("s_count").value);
  const tRaw = $("s_target").value.trim();
  if (!Number.isInteger(seed) || seed < 0) { toast("Seed must be a whole number ≥ 0.", "err"); return; }
  const btn = $("stressBtn"); btn.disabled = true; btn.innerHTML = `<span class="spin"></span>Running…`;
  $("stressStatus").innerHTML = statusPill("QUEUED");
  try {
    const body = { base_run_id: S.runs.baseline.run_id, alt_run_id: S.runs.optimized.run_id, seed, count };
    if (tRaw !== "") body.coverage_target_pct = Number(tRaw);
    let st = await api("/stress-runs", { method: "POST", body: JSON.stringify(body) });
    const t0 = Date.now(); let delay = 1000;
    while (!TERMINAL.has(st.status)) {
      await sleep(delay);
      st = await api(`/stress-runs/${st.stress_run_id}`);
      $("stressStatus").innerHTML = `${statusPill(st.status)} <span class="tiny muted">${Math.round((Date.now() - t0) / 1000)} s</span>`;
      delay = Math.min(delay * 1.5, 5000);
    }
    S.stress = st; saveSession();
    $("stressStatus").innerHTML = `${statusPill(st.status)} <span class="tiny muted">${st.results?.runtime_ms !== undefined ? `${nf0.format(st.results.runtime_ms)} ms` : ""}</span>`;
    renderStress();
    toast(`Stress suite finished: ${st.results?.cases?.length ?? 0} cases.`, st.status === "COMPLETED" ? "ok" : "err");
  } catch (e) { $("stressStatus").innerHTML = `<div class="alert err">${icon("alert", "sm")}<div>${esc(e.message)}</div></div>`; }
  finally { btn.disabled = false; btn.innerHTML = `${icon("play", "sm")}Run stress suite`; }
}

function intervalChart(rowsDef, res) {
  const c = C();
  const W = 760, left = 190, right = 30, rowH = 58, top = 34;
  const H = top + rowsDef.length * rowH + 10;
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Scenario ranges for baseline and optimized plans. Table below."><title>Scenario ranges</title>`;
  s += `<g font-size="11" fill="${c.ink}"><rect x="${left}" y="6" width="22" height="10" rx="3" fill="${c.base}"/><text x="${left + 28}" y="15">baseline</text><rect x="${left + 100}" y="6" width="22" height="10" rx="3" fill="${c.s1}"/><text x="${left + 128}" y="15">optimized</text>
    <text x="${left + 210}" y="15">bar = P10–P90 · line = min–max · tick = median</text></g>`;
  rowsDef.forEach((d, i) => {
    const y0 = top + i * rowH;
    const x = (v) => left + ((W - left - right) * v) / d.max;
    s += `<text x="0" y="${y0 + 22}" font-size="12" font-weight="650" fill="${c.inkStrong}">${esc(d.title)}</text><text x="0" y="${y0 + 38}" font-size="10.5" fill="${c.ink}">${esc(d.sub)}</text>`;
    s += `<line x1="${left}" y1="${y0 + 46}" x2="${W - right}" y2="${y0 + 46}" stroke="${c.grid}"/>`;
    for (const t of [0, d.max / 2, d.max]) s += `<text x="${x(t)}" y="${y0 + 56}" font-size="9.5" text-anchor="middle" fill="${c.ink}">${esc(d.fmt(t))}</text>`;
    [["base", "Baseline", c.base, y0 + 14], ["alt", "Optimized", c.s1, y0 + 32]].forEach(([k, label, col, y], j) => {
      const m = res.summary[k].metrics[d.key];
      if (!m || m.n === 0) { s += `<text x="${left}" y="${y + 4}" font-size="11" fill="${c.critInk}">no successful cases</text>`; return; }
      const delay = `animation-delay:${(0.1 + i * 0.12 + j * 0.06).toFixed(2)}s`;
      const tipTxt = `${label} · ${d.title}\nmedian ${d.fmt(m.median)}\nP10–P90 ${d.fmt(m.p10)} – ${d.fmt(m.p90)}\nrange ${d.fmt(m.min)} – ${d.fmt(m.max)} · n=${m.n}`;
      s += `<g data-tip="${esc(tipTxt)}"><rect x="${left}" y="${y - 8}" width="${W - left - right}" height="16" fill="transparent"/>`;
      s += `<line class="grow-x" style="${delay}" x1="${x(m.min)}" y1="${y}" x2="${x(m.max)}" y2="${y}" stroke="${col}" stroke-width="2" stroke-linecap="round"/>`;
      s += `<rect class="grow-x" style="${delay}" x="${x(m.p10)}" y="${y - 5}" width="${Math.max(x(m.p90) - x(m.p10), 3)}" height="10" rx="4" fill="${col}" fill-opacity=".5"/>`;
      s += `<line class="fade-in" style="animation-delay:${(0.7 + i * 0.12).toFixed(2)}s" x1="${x(m.median)}" y1="${y - 7}" x2="${x(m.median)}" y2="${y + 7}" stroke="${c.inkStrong}" stroke-width="3" stroke-linecap="round"/></g>`;
    });
  });
  return `${s}</svg>`;
}

function stress3d(host, res) {
  const c = C();
  const X = (d) => ((d - 105) / 25) * 30, Z = (t) => ((t - 115) / 25) * 30, Y = (v) => (v || 0) * 0.4;
  const ground = [{ type: "poly", pts: [[-33, -33], [33, -33], [33, 33], [-33, 33]], fill: c.dark ? "rgba(38,42,46,.62)" : "rgba(255,253,249,.88)", stroke: c.axis, width: 1 }];
  for (let d = 80; d <= 130; d += 10) {
    ground.push({ type: "line", a: [X(d), -33], b: [X(d), 33], color: c.grid, width: 0.8 });
    ground.push({ type: "text", x: X(d), z: 37, text: `×${(d / 100).toFixed(1)}`, color: c.ink, size: 10, weight: 600 });
  }
  for (let t = 90; t <= 140; t += 10) {
    ground.push({ type: "line", a: [-33, Z(t)], b: [33, Z(t)], color: c.grid, width: 0.8 });
    ground.push({ type: "text", x: 38, z: Z(t), text: `×${(t / 100).toFixed(1)}`, color: c.ink, size: 10, weight: 600 });
  }
  ground.push({ type: "text", x: 0, z: 43, text: "demand multiplier →", color: c.inkStrong, size: 11, weight: 700 });
  ground.push({ type: "text", x: 46, z: 0, text: "travel multiplier →", color: c.inkStrong, size: 11, weight: 700 });
  const items = [];
  items.push({ type: "line", pts: [[-33, 0, -33], [-33, Y(100), -33]], color: c.axis, width: 1.5, delay: 0.1 });
  for (const v of [0, 25, 50, 75, 100]) {
    items.push({ type: "line", pts: [[-33, Y(v), -33], [33, Y(v), -33]], color: c.grid, width: 0.8, delay: 0.15 });
    items.push({ type: "label", x: -37, y: Y(v), z: -33, text: `${v}%`, color: c.ink, size: 10, weight: 600, always: true, delay: 0.2 });
  }
  items.push({ type: "label", x: -33, y: Y(100) + 4, z: -33, text: "coverage within threshold", color: c.inkStrong, size: 11, weight: 700, always: true, delay: 0.3 });
  res.cases.forEach((cs, i) => {
    const x = X(cs.demand_pct), z = Z(cs.travel_pct), delay = 0.3 + i * 0.04;
    const b = cs.base, a = cs.alt;
    const tip = (lbl, o) => `Case ${cs.case} · ${lbl}\ndemand ×${(cs.demand_pct / 100).toFixed(2)} · travel ×${(cs.travel_pct / 100).toFixed(2)}\n${o.status === "COMPLETED" ? `coverage ${pct(o.coverage_pct)} · unmet ${pct(o.unmet_rate_pct)}` : o.status}`;
    if (b.status === "COMPLETED" && a.status === "COMPLETED") items.push({ type: "line", pts: [[x, Y(b.coverage_pct), z], [x, Y(a.coverage_pct), z]], color: c.ink, alpha: 0.45, width: 1.4, delay: delay + 0.4 });
    if (b.status === "COMPLETED") items.push({ type: "dot", id: `b${cs.case}`, x, y: Y(b.coverage_pct), z, r: 0.95, color: c.base, stem: c.grid, delay, pick: true, tip: tip("baseline", b) });
    if (a.status === "COMPLETED") items.push({ type: "dot", id: `a${cs.case}`, x, y: Y(a.coverage_pct), z, r: 1.15, color: c.s1, stem: c.grid, delay: delay + 0.1, pick: true, tip: tip("optimized", a) });
  });
  const scene = new Viz3D.Scene(host, { height: (w) => Math.max(320, Math.min(480, w * 0.62)), radius: 58, yaw: -0.7, pitch: 0.52, center: [0, 14, 0],
    label: "3D scatter of stress cases: demand multiplier by travel multiplier by coverage", halo: c.dark ? "#141618" : "#fffdf9", spin: 0.14 });
  scene.setData({ items, ground });
}

function renderStress() {
  const box = $("stressBox");
  const ready = S.runs.baseline?.status === "COMPLETED" && S.runs.optimized?.status === "COMPLETED";
  $("stressBtn").disabled = PUBLIC_DEMO || !ready;
  if (!S.stress?.results) {
    box.innerHTML = `<div class="card">${ready
      ? emptyState("activity", "Ready to stress-test", "Run the suite to see how the baseline and optimized plans hold up across 20 fixed-seed cases.")
      : emptyState("activity", "Run a scenario first", "The stress suite needs completed baseline and optimized plans.", `<a class="btn primary sm" href="#plan">Start a scenario</a>`)}</div>`;
    return;
  }
  const res = S.stress.results;
  if (res.error) { box.innerHTML = `<div class="alert err">${icon("alert", "sm")}<div>Stress run ${esc(S.stress.status)}.</div></div>`; return; }
  const sb = res.summary.base, sa = res.summary.alt, gain = res.summary.coverage_gain_pp;
  const maxTravel = Math.ceil(Math.max(10, ...res.cases.flatMap((c) => [c.base.mean_travel_min || 0, c.alt.mean_travel_min || 0])) * 1.1 / 10) * 10;
  const tile = (ic, lbl, val, meta) => `<div class="tile"><div class="lbl">${icon(ic, "sm")}${esc(lbl)}</div><div class="val">${val}</div><div class="meta">${meta}</div></div>`;
  const hasTarget = res.coverage_target_pct !== null;
  box.classList.add("anim");
  box.innerHTML = `${res.timed_out ? `<div class="alert warn">${icon("alert", "sm")}<div>Time limit reached; some cases were not run.</div></div>` : ""}
    <div class="tiles">
      ${tile("up", "Median coverage gain", gain.n ? `${nf1.format(gain.median)}<small>pp</small>` : "n/a", gain.n ? `P10–P90 ${nf1.format(gain.p10)} – ${nf1.format(gain.p90)} pp` : "")}
      ${tile("check", "Optimized ≥ baseline", `${res.summary.alt_better_or_equal_cases}<small>of ${gain.n} cases</small>`, "paired comparison, same cases")}
      ${tile("alert", "Infeasible cases", `${sa.failed_cases}<small>optimized</small>`, `baseline ${sb.failed_cases} · failure rate ${nf1.format(sa.failure_rate_pct)}%`)}
      ${hasTarget ? tile("target", `Below ${res.coverage_target_pct}% coverage`, `${sa.below_coverage_target_cases}<small>optimized</small>`, `baseline ${sb.below_coverage_target_cases} of ${res.case_count}`) : tile("hash", "Cases · seed", `${res.case_count}<small>seed ${res.seed}</small>`, `${nf0.format(res.runtime_ms)} ms total`)}
    </div>
    <div class="card"><div class="card-h"><div class="ic">${icon("cube")}</div><div><h2>Scenario cloud (3D)</h2><p class="desc">Each dot is one stress case · x = demand, depth = travel time, height = coverage · drag to rotate</p></div></div>
      <div class="card-b"><div id="stress3d"></div><div class="legend"><span><span class="sw" style="background:${C().base};border-radius:50%"></span>baseline</span><span><span class="sw" style="background:${C().s1};border-radius:50%"></span>optimized</span><span><i class="ln" style="background:${C().ink};opacity:.6"></i>gain in the same case</span></div></div></div>
    <div class="card"><div class="card-h"><div class="ic">${icon("activity")}</div><div><h2>Scenario ranges</h2><p class="desc">${esc(res.caveat)}</p></div></div>
      <div class="card-b">${intervalChart([
        { key: "coverage_pct", title: "Visits within threshold", sub: "higher is better", max: 100, fmt: (v) => `${nf0.format(v)}%` },
        { key: "unmet_rate_pct", title: "Unmet demand", sub: "lower is better", max: 100, fmt: (v) => `${nf0.format(v)}%` },
        { key: "worst_cluster_coverage_pct", title: "Worst-served cluster", sub: "higher is better", max: 100, fmt: (v) => `${nf0.format(v)}%` },
        { key: "mean_travel_min", title: "Average assigned travel", sub: "minutes, lower is better", max: maxTravel, fmt: (v) => `${nf0.format(v)} min` },
      ], res)}
      ${sa.failed_cases === 0 && sb.failed_cases === 0 && S.runs.optimized.plan.equity_min_pct === 0 ? `<div class="source-note">${icon("info", "sm")}<span>With no equity floor the model is always feasible — unmet demand absorbs shortfalls — so failures only appear with a floor above 0%. Use a coverage target to count shortfalls.</span></div>` : ""}</div></div>
    <div class="card"><div class="card-h"><div class="ic">${icon("hash")}</div><div><h2>Per-case observations</h2><p class="desc">Quantiles: numpy ${esc(res.quantile_method)} method</p></div></div>
      <div class="card-b flush table-wrap"><table><thead><tr><th>Case</th><th class="num">Demand</th><th class="num">Travel</th><th>Baseline</th><th class="num">Coverage</th><th>Optimized</th><th class="num">Coverage</th><th class="num">Gain</th><th>Worst cluster</th></tr></thead><tbody>${
        res.cases.map((c) => `<tr><td>${c.case}</td><td class="num">×${(c.demand_pct / 100).toFixed(2)}</td><td class="num">×${(c.travel_pct / 100).toFixed(2)}</td><td>${statusPill(c.base.status)}</td><td class="num">${pct(c.base.coverage_pct)}</td><td>${statusPill(c.alt.status)}</td><td class="num">${pct(c.alt.coverage_pct)}</td><td class="num">${c.coverage_gain_pp === undefined ? "—" : `${c.coverage_gain_pp >= 0 ? "+" : "−"}${nf1.format(Math.abs(c.coverage_gain_pp))} pp`}</td><td>${esc(c.alt.worst_cluster_id || "—")} <span class="muted">${pct(c.alt.worst_cluster_coverage_pct)}</span></td></tr>`).join("")
      }</tbody></table></div></div>`;
  stress3d($("stress3d"), res);
}

/* ---------- report ---------- */
function renderReport() {
  const b = S.runs.baseline, o = S.runs.optimized, g = S.runs.greedy;
  if (!o || !TERMINAL.has(o.status)) {
    $("reportBox").innerHTML = `<div class="card">${emptyState("file", "No report yet", "Complete a scenario to generate a printable report with hashes, audit and exports.", `<a class="btn primary sm" href="#plan">Start a scenario</a>`)}</div>`;
    return;
  }
  const e = S.expl.en;
  const m = S.dataset.manifest;
  const url = (r, format) => PUBLIC_DEMO ? `exports/${r.kind}.${format}`
    : `${API}/runs/${r.run_id}/export?format=${format}${format === "html" && r.kind !== "baseline" && b?.status === "COMPLETED" ? `&compare_to=${b.run_id}` : ""}`;
  const dl = (r) => r && TERMINAL.has(r.status) ? `<div class="dl-row"><b>${esc(KIND_LABEL[r.kind])}</b>${statusPill(r.status)}<span class="spacer" style="flex:1"></span>
      <a class="btn sm" href="${url(r, "html")}" target="_blank" rel="noopener">${icon("print", "sm")}Report</a>
      <a class="btn sm" href="${url(r, "json")}" download>${icon("download", "sm")}JSON</a>
      <a class="btn sm" href="${url(r, "csv")}" download>${icon("download", "sm")}CSV</a></div>` : "";
  const keyRows = o.status === "COMPLETED" ? [
    ["Visits within threshold", "coverage_pct", pct], ["Demand served", "served_rate_pct", pct], ["Unmet visits / week", "unmet", num],
    ["Worst-served cluster", "worst_cluster_coverage_pct", pct], ["Average assigned travel", "mean_travel_min", mins], ["Weekly cost", "cost_pkr", pkr],
  ].map(([l, k, f]) => `<tr><td>${esc(l)}</td><td class="num">${b?.status === "COMPLETED" ? esc(f(b.metrics[k].value)) : "n/a"}</td><td class="num">${g?.status === "COMPLETED" ? esc(f(g.metrics[k].value)) : "n/a"}</td><td class="num"><b>${esc(f(o.metrics[k].value))}</b></td></tr>`).join("") : "";
  $("reportBox").innerHTML = `<div class="card doc">
    <div class="doc-head"><div class="brand-mark"><svg viewBox="0 0 24 24"><use href="#i-logo"/></svg></div>
      <div style="flex:1"><h2 style="font-size:1.2rem">CIVITWIN AI planning report</h2><div class="small muted">${esc(m.district_label)} · dataset ${esc(m.id)} v${esc(m.version)} · one modeled week</div></div>
      <span class="badge-synthetic">${isReal() ? `${icon("db", "sm")}REAL DATA + ASSUMPTIONS` : `${icon("flask", "sm")}SYNTHETIC`}</span><button class="btn sm no-print" onclick="window.print()">${icon("print", "sm")}Print</button></div>
    <div class="doc-sec"><h3>Executive summary</h3>${e ? `${(S.comparison?.en?.explanation || []).map((s) => `<p><b>${esc(s)}</b></p>`).join("")}${e.sentences.map((s) => `<p class="small" style="color:var(--ink-2)">${esc(s)}</p>`).join("")}` : `<p class="muted">The optimized plan did not complete (${esc(o.status)}), so there is no summary.</p>`}</div>
    ${keyRows ? `<div class="doc-sec"><h3>Key figures</h3><div class="table-wrap"><table><thead><tr><th>Measure</th><th class="num">Baseline</th><th class="num">Greedy</th><th class="num">Optimized</th></tr></thead><tbody>${keyRows}</tbody></table></div></div>` : ""}
    ${o.status === "COMPLETED" ? reportHumanSection(o) : ""}
    <div class="doc-sec"><h3>Provenance</h3><dl class="kv"><dt>Dataset SHA-256</dt><dd class="mono">${esc(m.sha256)}</dd><dt>Plan hash</dt><dd class="mono">${esc(S.scenario?.plan_hash || o.plan_hash)}</dd>
      <dt>Result hash (optimized)</dt><dd class="mono">${esc(o.result_sha256 || "—")}</dd><dt>Solver</dt><dd>${esc(o.engine?.solver_version || "—")}</dd><dt>Audit</dt><dd>${o.audit ? `${o.audit.passed ? "passed" : "FAILED"} · ${o.audit.checks.length} checks` : "—"}</dd></dl></div>
    <div class="doc-sec no-print"><h3>Downloads</h3>${[b, g, o].map(dl).join("")}<p class="tiny muted mt-h">Exports include dataset, plan and result hashes, solver settings, the audit and the data-type warning. CSV cells starting with = + − @ are escaped.</p></div>
    <div class="doc-sec"><h3>Assumptions and limitations</h3><ul class="small">${m.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}
      <li>Results are hypothetical decision support, not medical advice or a government-approved allocation.</li>
      <li>Demand means modeled visits per week, not unique residents; improvements are modeled, not causal.</li>
      <li>The baseline is a modeled baseline using the same assignment rules, not observed practice.</li>
      <li>Stress results are scenario ranges from illustrative multipliers, not forecasts or confidence intervals.</li>
      <li>The fairness metric reflects the chosen policy and is not a guarantee of fairness.</li></ul></div></div>`;
}

/* ---------- human touch: greeting, presets, tour ---------- */
function renderGreeting() {
  if (!$("greet")) return;
  const h = new Date().getHours();
  const part = h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
  $("greet").innerHTML = `<span class="ur" lang="ur">السلام علیکم</span><span>· ${part}. Thank you for planning with people in mind.</span>`;
}
renderGreeting();

const PRESETS = [
  { ic: "target", t: "Default plan", d: "PKR 3 lakh, 2 units, 45 min", p: {} },
  { ic: "coins", t: "Tight budget", d: "PKR 1.5 lakh and 1 new unit", p: { budget_pkr: 150000, max_new_units: 1 } },
  { ic: "bolt", t: "Demand surge", d: "25% more visits, e.g. an outbreak week", p: { demand_multiplier_pct: 125 } },
  { ic: "clock", t: "Faster access", d: "Stricter standard: 30 minutes", p: { threshold_minutes: 30 } },
  { ic: "heart", t: "No one left behind", d: "Every cluster ≥10% · 5 units · 7 lakh", p: { equity_min_pct: 10, max_new_units: 5, budget_pkr: 700000 } },
  { ic: "scale", t: "Equity first", d: "Lift the worst-served first · 3 units", p: { policy: "equity_first", max_new_units: 3, budget_pkr: 450000 } },
];
function renderPresets() {
  $("presets").innerHTML = PRESETS.map((x, i) => `<button type="button" class="preset" data-preset="${i}"><span class="ic">${icon(x.ic, "sm")}</span><span><b>${esc(x.t)}</b><span>${esc(x.d)}</span></span></button>`).join("");
  $("presets").addEventListener("click", (e) => {
    const b = e.target.closest("[data-preset]");
    if (!b) return;
    const x = PRESETS[Number(b.dataset.preset)];
    setForm({ ...defaultsPlan(), ...x.p });
    S.parse = null; $("parseOut").innerHTML = "";
    invalidateReview();
    toast(`“${x.t}” loaded. Check the values, then review the plan.`, "ok");
  });
}

const TOUR = [
  { ic: "heart", ur: "خوش آمدید", t: "Welcome to CIVITWIN", d: "A planning sandbox for one question: where should new health services go so that more families can reach care within a reasonable journey? The Bajaur view uses real public data — OpenStreetMap, the 2023 census and the government facility registry — with every assumption written down." },
  { ic: "spark", ur: "اپنی بات لکھیں", t: "1 · Describe the plan in your words", d: "Type in English or Urdu — for example “بجٹ ۳ لاکھ، دو نئے مراکز، ۴۵ منٹ” — or pick a quick scenario. The offline parser fills the form; nothing runs yet." },
  { ic: "hash", ur: "تصدیق", t: "2 · Review and confirm", d: "You see every value and the plan's fingerprint (hash). Only after you confirm does the solver run the baseline, a greedy benchmark and the optimized plan on identical inputs." },
  { ic: "shield", ur: "جانچ", t: "3 · Solved, then audited", d: "The solver decides, an independent audit re-checks every constraint and number, and the explanation is filled only from audited results — in English or Urdu." },
  { ic: "route", ur: "انسان فیصلہ کرتا ہے", t: "4 · Explore, then decide as people", d: "See the 3D map, who is still far away, why each site was chosen and what more budget buys. Then record your own review — the model advises, people decide." },
];
let tourStep = 0;
function showTour(step = 0) {
  tourStep = step;
  const x = TOUR[step];
  $("tourIcon").innerHTML = icon(x.ic, "lg");
  $("tourUr").textContent = x.ur; $("tourUr").setAttribute("lang", "ur");
  $("tourTitle").textContent = x.t; $("tourText").textContent = x.d;
  $("tourDots").innerHTML = TOUR.map((_, i) => `<i class="${i === step ? "on" : ""}"></i>`).join("");
  $("tourBack").disabled = step === 0;
  $("tourNext").textContent = step === TOUR.length - 1 ? "Start planning" : "Next";
  $("tour").hidden = false;
  $("tourNext").focus();
}
function closeTour() { $("tour").hidden = true; try { localStorage.setItem("civitwin.toured", "1"); } catch { /* ignore */ } }
$("tourNext").addEventListener("click", () => { if (tourStep < TOUR.length - 1) showTour(tourStep + 1); else { closeTour(); location.hash = "#plan"; } });
$("tourBack").addEventListener("click", () => { if (tourStep > 0) showTour(tourStep - 1); });
$("tourSkip").addEventListener("click", closeTour);
$("tourBtn").addEventListener("click", () => { closeNav(); showTour(0); });
$("tour").addEventListener("keydown", (e) => { if (e.key === "Escape") closeTour(); });
$("tour").addEventListener("click", (e) => { if (e.target === $("tour")) closeTour(); });
try { if (!PUBLIC_DEMO && !localStorage.getItem("civitwin.toured")) setTimeout(() => showTour(0), 900); } catch { /* ignore */ }

/* ---------- decision support: why these sites ---------- */
async function loadImpact(o) {
  const box = $("impactBox");
  if (!box) return;
  try {
    const data = S.impact[o.run_id] || (S.impact[o.run_id] = await api(`/runs/${o.run_id}/site-impact`));
    if ($("impactBox") !== box) return;
    if (!data.sites.length) { box.innerHTML = emptyState("building", "No new sites opened", "This plan uses existing sites only."); return; }
    const thr = data.threshold_minutes;
    box.innerHTML = data.sites.map((x) => {
      const used = x.capacity ? (100 * x.assigned_visits) / x.capacity : 0;
      const lost = x.within_lost_if_removed;
      const chips = x.clusters_served.map((c) => `<span class="tag ${c.minutes <= thr ? "ok" : ""}" data-tip="${esc(`${c.community_id} → ${x.site_id}: ${c.visits} visits/week, ${c.minutes} min${c.minutes <= thr ? "" : " (beyond threshold)"}`)}">${esc(placeName(c.community_id))} · ${c.visits} · ${mm(c.minutes)}</span>`).join("");
      return `<div class="impact"><div class="head"><span class="status ok">${icon("plus")}NEW</span><b>${esc(siteName(x.site_id))}</b><span class="cost">${esc(pkr(x.cost_pkr))}/week · capacity ${x.capacity}</span></div>
        <div class="stats">
          <div><div class="v">${countSpan(x.within_threshold_visits, "int")}</div><div class="l">visits/week within ${thr} min</div></div>
          <div data-tip="${esc(`Re-solved with ${x.site_id} closed and everything else unchanged.\nAudit of that run: ${x.if_removed_audit_passed ? "passed" : "n/a"}`)}"><div class="v">${lost === undefined ? esc(x.if_removed_status) : `−${countSpan(lost, "int")}`}</div><div class="l">${lost === undefined ? "if removed" : `if removed (−${nf1.format(x.coverage_lost_pp_if_removed)} pp)`}</div></div>
          <div><div class="v">${x.cost_per_within_visit_kept ? esc(pkr(Math.round(x.cost_per_within_visit_kept))) : "—"}</div><div class="l">per covered visit kept</div></div>
        </div>
        <div class="small muted" style="margin-bottom:.35rem"><span class="meter"><i style="width:${Math.min(100, used)}%"></i></span>${x.assigned_visits} of ${x.capacity} visits/week used (${nf1.format(used)}%)</div>
        <div>${chips}</div></div>`;
    }).join("") + `<div class="source-note">${icon("info", "sm")}<span>${esc(data.note)} Green chips are within ${thr} minutes.</span></div>`;
    animateCounts(box);
  } catch (e) { if ($("impactBox") === box) box.innerHTML = `<div class="alert err">${icon("alert", "sm")}<div>Site analysis failed: ${esc(e.message)}</div></div>`; }
}

/* ---------- human touch: community journeys ---------- */
function journeyRows(base, o) {
  const ds = S.dataset;
  const existing = ds.sites.filter((x) => x.type === "existing").map((x) => x.id);
  const after = existing.concat(o.selected_candidate_ids);
  const nearest = (cid, ids) => {
    let best = null;
    for (const id of ids) { const t = S.minutes[`${cid}|${id}`]; if (t !== undefined && (!best || t < best.t)) best = { t, id }; }
    return best;
  };
  const per = {}; for (const pc of o.metrics.per_cluster) per[pc.community_id] = pc;
  const perB = {}; if (base) for (const pc of base.metrics.per_cluster) perB[pc.community_id] = pc;
  return ds.communities.map((c) => {
    const b = nearest(c.id, existing), a = nearest(c.id, after);
    return { id: c.id, name: placeName(c.id), zone: c.zone_class, demand: per[c.id].demand, before: b, after: a, saved: b && a ? b.t - a.t : null,
      cov: per[c.id].coverage_pct, covBefore: perB[c.id]?.coverage_pct ?? null };
  });
}

const mm = (t) => (t >= 90 ? `${Math.floor(t / 60)} h ${Math.round(t % 60)} min` : `${Math.round(t)} min`);
function journeyCard(r, thr, maxT) {
  const w = (t) => `${Math.min(100, (100 * t) / maxT).toFixed(1)}%`;
  const thrPos = `${Math.min(100, (100 * thr) / maxT).toFixed(1)}%`;
  const changed = r.after && r.before && r.after.id !== r.before.id;
  const inside = r.after && r.after.t <= thr;
  const how = S.dsInfo?.travel_mode === "foot" ? "walk" : S.dsInfo?.travel_mode === "car" ? "drive" : "journey";
  const B = r.before && siteName(r.before.id), A = r.after && siteName(r.after.id);
  let story;
  if (!r.before && !r.after) story = `${r.name} has no route to any health facility in this model.`;
  else if (changed) story = `For a family in ${r.name}, the nearest open health facility was ${B} — about ${mm(r.before.t)} away (${how}). With ${A} open, it is about ${mm(r.after.t)}: ${mm(r.saved)} shorter, ${inside ? `inside the ${thr}-minute standard` : `still beyond the ${thr}-minute standard`}.`;
  else if (inside) story = `Families in ${r.name} already have ${A} about ${mm(r.after.t)} away (${how}) — within the ${thr}-minute standard.`;
  else story = `Families in ${r.name} still face about ${r.after ? mm(r.after.t) : "—"} (${how}) to ${A || "the nearest facility"}. This plan does not bring care closer; outreach or another site may be needed.`;
  return `<div class="story"><div class="who">${icon("users", "sm")}${esc(r.name)} <span class="tiny muted">· ${r.demand} visits/week · coverage ${pct(r.covBefore)} → ${pct(r.cov)}</span></div>
    <div class="trip"><span>Before</span><div class="tbar"><i class="before" style="width:${r.before ? w(r.before.t) : "0%"}"></i><span class="thr" style="left:${thrPos}" title="${thr}-minute standard"></span></div><span><b>${r.before ? mm(r.before.t) : "no route"}</b> ${r.before ? `· ${esc(B)}` : ""}</span></div>
    <div class="trip"><span>After</span><div class="tbar"><i class="after" style="width:${r.after ? w(r.after.t) : "0%"}"></i><span class="thr" style="left:${thrPos}"></span></div><span><b>${r.after ? mm(r.after.t) : "no route"}</b> ${r.after ? `· ${esc(A)}` : ""}</span></div>
    <p class="quote">${esc(story)}</p></div>`;
}

function renderJourneys(base, o) {
  const box = $("journeysBox");
  if (!box) return;
  const thr = o.plan.threshold_minutes;
  const rows = journeyRows(base, o);
  const reach = (k) => rows.filter((r) => r[k] && r[k].t <= thr).length;
  const totalD = rows.reduce((a, r) => a + r.demand, 0);
  const avg = (k) => rows.reduce((a, r) => a + (r[k] ? r[k].t * r.demand : 0), 0) / Math.max(1, rows.filter((r) => r[k]).reduce((a, r) => a + r.demand, 0));
  const helped = rows.filter((r) => r.saved > 0).sort((a, b) => b.saved - a.saved);
  const left = rows.filter((r) => !r.after || r.after.t > thr).sort((a, b) => (b.after?.t ?? 999) - (a.after?.t ?? 999));
  const maxT = Math.max(thr * 1.5, ...rows.map((r) => Math.max(r.before?.t || 0, r.after?.t || 0)));
  const pickId = S.journeyPick && rows.some((r) => r.id === S.journeyPick) ? S.journeyPick : null;
  const stories = pickId ? rows.filter((r) => r.id === pickId) : helped.slice(0, 3);
  box.innerHTML = `<div class="journey-stats">
      <div><div class="v">${reach("before")} → ${reach("after")}</div><div class="l">clusters with a site within ${thr} min</div></div>
      <div><div class="v">${nf1.format(avg("before"))} → ${nf1.format(avg("after"))}</div><div class="l">avg. minutes to nearest site (per visit)</div></div>
      <div><div class="v">${countSpan(left.length, "int")}</div><div class="l">clusters still beyond ${thr} min</div></div></div>
    <div class="row between" style="margin-bottom:.5rem"><span class="small" style="font-weight:650">${pickId ? `Journey for ${esc(placeName(pickId))}` : helped.length ? "Biggest changes for families" : "No cluster gets a closer site in this plan"}</span>
      <label class="small row" style="gap:.4rem">Show cluster <select id="journeyPick" style="width:auto;padding:.25rem .5rem"><option value="">Top 3</option>${rows.map((r) => `<option value="${esc(r.id)}" ${r.id === pickId ? "selected" : ""}>${esc(r.name)}</option>`).join("")}</select></label></div>
    ${stories.map((r) => journeyCard(r, thr, maxT)).join("")}
    ${left.length ? `<div class="left-behind"><b>Still far from care:</b> ${left.slice(0, 18).map((r) => `<span class="tag">${esc(r.name)} · ${r.after ? mm(r.after.t) : "no route"}</span>`).join("")}${left.length > 18 ? ` <span class="tiny">and ${left.length - 18} more</span>` : ""}
      <div class="tiny" style="margin-top:.35rem">Ideas to discuss with these communities — not modeled here: mobile clinic days, Lady Health Worker outreach, transport support, or a site in the next budget round.</div></div>` : ""}
    <div class="source-note">${icon("info", "sm")}<span>${isReal() ? "Stories built from real road/path travel times (OSRM on OpenStreetMap) and census-based population estimates — not interviews with real families." : "Illustrative stories built from modeled travel times on a schematic network — not real people or real journeys."} Times are to the nearest open site; actual assignments also depend on capacity.</span></div>`;
  $("journeyPick").addEventListener("change", (e) => { S.journeyPick = e.target.value || null; renderJourneys(base, o); });
  animateCounts(box);
}

/* ---------- decision support: budget trade-off ---------- */
async function loadTradeoff(o) {
  const box = $("tradeoffBox");
  if (!box) return;
  try {
    const data = S.tradeoff[o.plan_hash] || (S.tradeoff[o.plan_hash] = await api(`/runs/${o.run_id}/tradeoff`, { method: "POST" }));
    if ($("tradeoffBox") !== box) return;
    box.innerHTML = tradeoffChart(data, o);
    $("tradeoffTable").innerHTML = `<table><thead><tr><th class="num">Budget</th>${data.curves.map((c) => `<th class="num">≤${c.max_new_units} units: coverage</th><th>sites</th>`).join("")}</tr></thead><tbody>${
      data.budgets.map((bud, i) => `<tr><td class="num">${esc(pkr(bud))}</td>${data.curves.map((c) => { const p = c.points[i]; return p.status === "COMPLETED" ? `<td class="num">${pct(p.coverage_pct)}</td><td>${esc(p.selected_candidate_ids.join(", ") || "none")}</td>` : `<td class="num">${esc(p.status)}</td><td></td>`; }).join("")}</tr>`).join("")
    }</tbody></table>`;
  } catch (e) { if ($("tradeoffBox") === box) box.innerHTML = `<div class="alert err">${icon("alert", "sm")}<div>Trade-off analysis failed: ${esc(e.message)}</div></div>`; }
}

function tradeoffChart(data, o) {
  const c = C();
  const W = 760, H = 300, left = 52, right = 120, top = 18, bottom = 42;
  const maxB = Math.max(...data.budgets);
  const x = (b) => left + ((W - left - right) * b) / maxB;
  const y = (v) => top + (H - top - bottom) * (1 - (v || 0) / 100);
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Coverage versus weekly budget for each unit limit. Data table below."><title>Budget trade-off</title>`;
  for (const t of [0, 25, 50, 75, 100]) s += `<line x1="${left}" y1="${y(t)}" x2="${W - right + 10}" y2="${y(t)}" stroke="${c.grid}"/><text x="${left - 8}" y="${y(t) + 4}" font-size="11" text-anchor="end" fill="${c.ink}">${t}%</text>`;
  for (const b of data.budgets) s += `<text x="${x(b)}" y="${H - 20}" font-size="10.5" text-anchor="middle" fill="${c.ink}">${b ? `${b / 100000}L` : "0"}</text>`;
  s += `<text x="${(left + W - right) / 2}" y="${H - 4}" font-size="11" text-anchor="middle" fill="${c.ink}">weekly budget for new units (PKR lakh)</text>`;
  const cur = data.current_budget_pkr;
  if (cur <= maxB) s += `<line x1="${x(cur)}" y1="${top}" x2="${x(cur)}" y2="${H - bottom}" stroke="${c.axis}" stroke-dasharray="4 4"/>`;
  const legend = [];
  // draw the relaxed curve first so the plan's own curve stays visible where they overlap
  [...data.curves].sort((a, b2) => Number(a.is_plan_limit) - Number(b2.is_plan_limit)).forEach((cv, k) => {
    const col = cv.is_plan_limit ? c.s1 : c.s2;
    const pts = cv.points.filter((p) => p.status === "COMPLETED");
    if (!pts.length) return;
    const d = pts.map((p, i) => `${i ? "L" : "M"}${x(p.budget_pkr).toFixed(1)},${y(p.coverage_pct).toFixed(1)}`).join(" ");
    s += `<path d="${d}" fill="none" stroke="${col}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1" style="animation:dash 1.4s var(--ease) ${0.15 + k * 0.35}s forwards"/>`;
    pts.forEach((p, i) => {
      const tip = `Budget ${pkr(p.budget_pkr)}/week · up to ${cv.max_new_units} units\nCoverage ${pct(p.coverage_pct)} · worst cluster ${pct(p.worst_cluster_coverage_pct)}\nCost ${pkr(p.cost_pkr)} · sites ${p.selected_candidate_ids.join(", ") || "none"}${p.gain_pp_per_lakh !== undefined ? `\n+${nf1.format(p.gain_pp_per_lakh)} pp per extra lakh` : ""}`;
      s += `<g data-tip="${esc(tip)}"><circle cx="${x(p.budget_pkr)}" cy="${y(p.coverage_pct)}" r="10" fill="transparent"/><circle class="fade-in" style="animation-delay:${(0.3 + k * 0.35 + i * 0.08).toFixed(2)}s" cx="${x(p.budget_pkr)}" cy="${y(p.coverage_pct)}" r="4.5" fill="${col}" stroke="${c.card}" stroke-width="2"/></g>`;
    });
    const last = pts[pts.length - 1];
    const ly = y(last.coverage_pct) + (cv.is_plan_limit ? 14 : -10);
    s += `<g class="fade-in" style="animation-delay:${1.3 + k * 0.3}s"><line x1="${x(last.budget_pkr) + 8}" y1="${ly - 4}" x2="${x(last.budget_pkr) + 20}" y2="${ly - 4}" stroke="${col}" stroke-width="3"/><text x="${x(last.budget_pkr) + 24}" y="${ly}" font-size="11.5" fill="${c.inkStrong}">up to ${cv.max_new_units} units</text></g>`;
    legend.push(`<span><i class="ln" style="background:${col}"></i>up to ${cv.max_new_units} new units${cv.is_plan_limit ? " (your limit)" : " (limit relaxed)"}</span>`);
  });
  const yourCov = o.metrics.coverage_pct.value;
  if (cur <= maxB) s += `<g data-tip="${esc(`Your confirmed plan\n${pkr(cur)}/week · ${pct(yourCov)} within ${data.threshold_minutes} min`)}"><circle cx="${x(cur)}" cy="${y(yourCov)}" r="9" fill="none" stroke="${c.inkStrong}" stroke-width="2"/><text x="${x(cur)}" y="${y(yourCov) - 15}" font-size="11" font-weight="700" text-anchor="middle" fill="${c.inkStrong}">your plan</text></g>`;
  s += "</svg>";
  legend.push(`<span><svg width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="5" fill="none" stroke="${c.inkStrong}" stroke-width="2"/></svg>your confirmed plan</span>`);

  const ins = [];
  const plan = data.curves.find((cv) => cv.is_plan_limit), relaxed = data.curves.find((cv) => !cv.is_plan_limit);
  const done = (cv) => (cv ? cv.points.filter((p) => p.status === "COMPLETED") : []);
  const firstMax = (cv) => { const ps = done(cv); if (!ps.length) return null; const m = Math.max(...ps.map((p) => p.coverage_pct)); return ps.find((p) => p.coverage_pct >= m - 1e-9); };
  const pm = firstMax(plan), rm = firstMax(relaxed);
  if (pm) ins.push(`With up to ${plan.max_new_units} new units, coverage stops rising at ${pkr(pm.budget_pkr)}/week (${pct(pm.coverage_pct)}). ${pm.budget_pkr < maxB ? "Beyond that, more money alone does not help — the unit limit is what binds." : ""}`);
  if (rm && relaxed) ins.push(`If up to ${relaxed.max_new_units} units were allowed, ${pkr(rm.budget_pkr)}/week would reach ${pct(rm.coverage_pct)}.`);
  const steps = done(plan).filter((p) => p.gain_pp_per_lakh !== undefined);
  if (steps.length) { const best = steps.reduce((a, b2) => (b2.gain_pp_per_lakh > a.gain_pp_per_lakh ? b2 : a)); ins.push(`Best value: the step up to ${pkr(best.budget_pkr)} adds about ${nf1.format(best.gain_pp_per_lakh)} percentage points per extra lakh.`); }
  return `${s}<div class="legend">${legend.join("")}</div><div class="insights">${ins.map((t) => `<div>${icon("spark", "sm")}<span>${esc(t)}</span></div>`).join("")}</div>
    <div class="source-note">${icon("info", "sm")}<span>${esc(data.note)} Computed in ${nf0.format(data.runtime_ms)} ms.</span></div>`;
}

/* ---------- human-in-the-loop: planner's review ---------- */
const DECISIONS = [["discuss", "Discuss with stakeholders"], ["field", "Needs field verification"], ["not_suitable", "Not suitable"]];
const reviewKey = (o) => `civitwin.review.${o.plan_hash}`;
function loadReview(o) { try { return JSON.parse(localStorage.getItem(reviewKey(o)) || "null"); } catch { return null; } }
function renderReview(o) {
  const box = $("reviewBox");
  if (!box) return;
  const r = loadReview(o) || { name: "", role: "District planner", decision: "discuss", notes: "", ack: false };
  const roles = ["District planner", "District Health Officer", "NGO / partner", "Community representative", "Lady Health Worker supervisor", "Other"];
  box.innerHTML = `<form id="reviewForm" novalidate>
    <div class="review-grid">
      <div class="field"><label for="rv_name">Reviewer name</label><input type="text" id="rv_name" maxlength="80" value="${esc(r.name)}" placeholder="e.g. your name"></div>
      <div class="field"><label for="rv_role">Role</label><select id="rv_role">${roles.map((x) => `<option ${x === r.role ? "selected" : ""}>${esc(x)}</option>`).join("")}</select></div>
    </div>
    <div class="field"><div class="lbl" id="rvDecLbl">Decision</div><div class="decision-opts" role="radiogroup" aria-labelledby="rvDecLbl">${
      DECISIONS.map(([v, l]) => `<label class="policy-opt"><input type="radio" name="rv_dec" value="${v}" ${r.decision === v ? "checked" : ""}><b>${esc(l)}</b></label>`).join("")}</div></div>
    <div class="field"><label for="rv_notes">Field notes</label><textarea id="rv_notes" maxlength="2000" dir="auto" placeholder="What does the model not know? e.g. the road to C02 closes in winter; ask the Lady Health Workers about C15.">${esc(r.notes)}</textarea></div>
    <label class="check"><input type="checkbox" id="rv_ack" ${r.ack ? "checked" : ""}> I understand these results rest on ${isReal() ? "public data with stated assumptions" : "synthetic data"} and are advisory, not an approved allocation.</label>
    <div class="row mt-1"><button type="submit" class="btn primary">${icon("check", "sm")}Save review</button>${r.saved_at ? `<span class="saved-badge">${icon("check", "sm")}Saved ${esc(new Date(r.saved_at).toLocaleString())}</span>` : '<span class="tiny muted">Stays on this computer; nothing is uploaded.</span>'}</div>
  </form>`;
  $("reviewForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const name = $("rv_name").value.trim();
    if (!name) { toast("Please add the reviewer's name.", "err"); $("rv_name").focus(); return; }
    if (!$("rv_ack").checked) { toast("Please confirm you understand the results are advisory.", "err"); return; }
    const rec = { name, role: $("rv_role").value, decision: document.querySelector('input[name="rv_dec"]:checked')?.value || "discuss",
      notes: $("rv_notes").value.trim(), ack: true, saved_at: new Date().toISOString(), plan_hash: o.plan_hash };
    try { localStorage.setItem(reviewKey(o), JSON.stringify(rec)); } catch { toast("Could not save in this browser.", "err"); return; }
    toast("Review saved. It now appears in the report.", "ok");
    renderReview(o); renderReport();
  });
}

function reportHumanSection(o) {
  const base = S.runs.baseline?.status === "COMPLETED" ? S.runs.baseline : null;
  const rows = journeyRows(base, o);
  const thr = o.plan.threshold_minutes;
  const reach = (k) => rows.filter((r) => r[k] && r[k].t <= thr).length;
  const left = rows.filter((r) => !r.after || r.after.t > thr).map((r) => r.id);
  const rv = PUBLIC_DEMO ? null : loadReview(o);
  const dec = rv ? (DECISIONS.find(([v]) => v === rv.decision) || [])[1] : null;
  return `<div class="doc-sec"><h3>People and places</h3><p class="small" style="color:var(--ink-2)">Clusters with a site within ${thr} minutes: <b>${reach("before")} → ${reach("after")}</b> of ${rows.length}.
      ${left.length ? `Still beyond ${thr} minutes: ${esc(left.join(", "))} — options such as mobile clinic days or outreach should be discussed with these communities.` : "Every cluster has a site within the standard."}</p></div>
    ${PUBLIC_DEMO ? "" : `<div class="doc-sec"><h3>Planner's review</h3>${rv ? `<dl class="kv"><dt>Reviewer</dt><dd>${esc(rv.name)} · ${esc(rv.role)}</dd><dt>Decision</dt><dd>${esc(dec || rv.decision)}</dd><dt>Saved</dt><dd>${esc(new Date(rv.saved_at).toLocaleString())}</dd></dl>
      ${rv.notes ? `<p class="small mt-h" style="white-space:pre-line;color:var(--ink-2)" dir="auto">${esc(rv.notes)}</p>` : ""}` : `<p class="small muted">Not reviewed yet. Add a review on the Comparison page — the model advises, people decide.</p>`}</div>`}`;
}

/* ---------- session restore ---------- */
async function restoreSession() {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(STORE_KEY) || "null"); } catch { saved = null; }
  if (!saved?.scenario_id || (saved.dataset_id && saved.dataset_id !== S.dataset.manifest.id)) return;
  try {
    S.scenario = await api(`/scenarios/${saved.scenario_id}`);
    setForm(S.scenario.plan);
    for (const k of KINDS) if (saved.runs?.[k]) { try { S.runs[k] = await api(`/runs/${saved.runs[k]}`); } catch { S.runs[k] = null; } }
    if (saved.stress_id) { try { S.stress = await api(`/stress-runs/${saved.stress_id}`); } catch { S.stress = null; } }
    renderRunStatus();
    const pending = KINDS.map((k) => S.runs[k]).filter((r) => r && !TERMINAL.has(r.status));
    if (pending.length) await Promise.all(pending.map((r) => pollRun(r.run_id)));
    await afterRuns();
    $("navResultsBadge").hidden = true;
  } catch { localStorage.removeItem(STORE_KEY); }
}

if (!PUBLIC_DEMO) wireForm();
init();
