/* Planning desk: real map + facts + quick plan + results + health/education coordination. */
"use strict";

function deskRun() { const o = S.runs.optimized; return o?.status === "COMPLETED" ? o : null; }

function deskPeopleWithin(open, thr) {
  if (!S.geo) return null;
  let n = 0;
  for (const c of S.geo.clusters) { const b = GeoMap.nearestOpen(c.id, open, S.minutes); if (b && b.t <= thr) n += c.population; }
  return n;
}

function renderDesk() {
  if (!$("deskMap") || !S.dataset) return;
  const o = deskRun();
  const thr = o ? o.plan.threshold_minutes : (S.dsInfo?.default_plan?.threshold_minutes || 45);
  const existing = S.dataset.sites.filter((x) => x.type === "existing").map((x) => x.id);
  if (!S.geo) {
    const run = S.deskWhen === "today" ? S.runs.baseline : o;
    $("deskMap").innerHTML = `<div class="m3"></div>`;
    map3d($("deskMap").querySelector(".m3"), run, { showAssign: true, title: "Demo district" });
    $("deskLegend").innerHTML = map3dLegend(run, true);
  } else {
    const run = o && S.deskWhen === "plan" ? o : null;
    GeoMap.render($("deskMap"), { geo: S.geo, dataset: S.dataset, minutes: S.minutes, run, threshold: thr, mode: S.mapLayer,
      show: S.layers, palette: geoPalette(), onPick: (id) => { S.journeyPick = id; renderDeskVillage(); } });
    $("deskLegend").innerHTML = GeoMap.legend(S.mapLayer, geoPalette(), thr, !!run);
  }
  // facts
  const ds = S.dataset, pop = ds.communities.reduce((a, c) => a + (c.population || 0), 0);
  const nonf = ds.sites.filter((x) => x.type === "candidate" && x.fixed_cost_pkr && S.geo?.facilities.find((f) => f.id === x.id)?.kind === "reactivate").length;
  const within = deskPeopleWithin(existing, thr);
  $("deskFacts").innerHTML = S.geo ? `<h2>Bajaur today <small>${S.dsInfo.travel_mode === "foot" ? "on foot" : "by vehicle"}</small></h2>
    <div class="facts">
      <div class="big"><b>${within === null ? "—" : pct((100 * within) / pop)}</b><span>of people live within ${thr} min of a working facility</span></div>
      <div><b>${num(pop)}</b><span>people (Census 2023)</span></div>
      <div><b>${existing.length}</b><span>working government facilities</span></div>
      <div><b>${nonf}</b><span>listed as non-functional (could reopen)</span></div>
    </div>
    <div class="src">Sources: PBS Census 2023 · FATA Health Dept/WHO registry (OCHA, 2018) · OSM/GeoNames · OSRM travel times.</div>`
    : `<h2>Synthetic planning district</h2><div class="facts">
        <div><b>${ds.communities.length}</b><span>fictional community clusters</span></div>
        <div><b>${existing.length}</b><span>modeled existing sites</span></div>
        <div><b>${ds.sites.length - existing.length}</b><span>modeled candidate zones</span></div>
      </div><div class="src">Schematic travel network and illustrative weekly demand.</div>`;
  if (PUBLIC_DEMO) { renderDeskResult(); return; }
  // quick plan
  const f = readForm();
  const busy = S.running;
  $("deskPlan").innerHTML = `<h2>Plan new access <small>you confirm before it runs</small></h2>
    <div class="qform">
      <div><label for="q_b">Weekly budget (PKR)</label><input id="q_b" type="number" min="0" step="10000" value="${f.budget_pkr}"></div>
      <div><label for="q_u">Facilities to open/reopen</label><input id="q_u" type="number" min="0" max="${dsStats().eligible}" value="${f.max_new_units}"></div>
      <div><label for="q_t">Travel standard (min)</label><input id="q_t" type="number" min="1" max="240" value="${f.threshold_minutes}"></div>
      <div><label for="q_p">Priority</label><select id="q_p">${["coverage_first", "equity_first"].map((v) => `<option value="${v}" ${f.policy === v ? "selected" : ""}>${v === "coverage_first" ? "Reach most visits" : "Lift worst-off first"}</option>`).join("")}</select></div>
    </div>
    <div id="deskReview" class="mt-h">${S.reviewed ? `<div class="hashbox">${esc(S.reviewed.plan_hash)}</div>` : ""}</div>
    <div class="row mt-h">${S.reviewed && !busy ? `<button class="btn primary" id="q_go">${icon("play", "sm")}Confirm &amp; run</button><button class="btn" id="q_edit">Edit</button>`
      : `<button class="btn dark" id="q_rev" ${busy ? "disabled" : ""}>${busy ? '<span class="spin"></span>Running…' : `${icon("hash", "sm")}Review plan`}</button>`}</div>`;
  $("q_rev")?.addEventListener("click", async () => {
    const plan = { ...readForm(), budget_pkr: Number($("q_b").value), max_new_units: Number($("q_u").value), threshold_minutes: Number($("q_t").value), policy: $("q_p").value, min_coverage_pct: null };
    setForm(plan);
    await reviewPlan(plan);
    renderDesk();
  });
  $("q_edit")?.addEventListener("click", () => { S.reviewed = null; renderSummary(); renderDesk(); });
  $("q_go")?.addEventListener("click", async () => { const scn = S.reviewed; S.deskWhen = "plan"; renderDesk(); await confirmAndRun(scn, { stay: true }); });
  renderDeskResult(); renderDeskVillage();
}

async function renderDeskResult() {
  const o = deskRun(), b = S.runs.baseline;
  if (!o) { $("deskResult").innerHTML = ""; $("deskCoord").innerHTML = ""; return; }
  const thr = o.plan.threshold_minutes;
  const existing = S.dataset.sites.filter((x) => x.type === "existing").map((x) => x.id);
  const pop = S.dataset.communities.reduce((a, c) => a + (c.population || 0), 0);
  const pB = deskPeopleWithin(existing, thr), pA = deskPeopleWithin(existing.concat(o.selected_candidate_ids), thr);
  const row = (l, bv, av) => `<tr><td>${l}</td><td class="num">${bv}</td><td class="num"><b>${av}</b></td></tr>`;
  const okB = b?.status === "COMPLETED";
  let html = `<h2>What this plan changes <small>audit ${o.audit.passed ? "passed" : "FAILED"} · ${esc(o.solver_status)}</small></h2>
    <div class="seg" role="group" aria-label="Map shows"><button data-when="today" aria-pressed="${S.deskWhen === "today"}">Map: baseline</button><button data-when="plan" aria-pressed="${S.deskWhen === "plan"}">Map: with plan</button></div>
    <table class="ba mt-h"><thead><tr><th></th><th class="num">Baseline</th><th class="num">Plan</th></tr></thead><tbody>
      ${pB !== null ? row(`People within ${thr} min of a facility`, pct((100 * pB) / pop), pct((100 * pA) / pop)) : ""}
      ${row(`Visits reached within ${thr} min`, okB ? pct(b.metrics.coverage_pct.value) : "n/a", pct(o.metrics.coverage_pct.value))}
      ${row("Unmet visits / week", okB ? num(b.metrics.unmet.value) : "n/a", num(o.metrics.unmet.value))}
      ${row("Weekly cost", "PKR 0", pkr(o.metrics.cost_pkr.value))}</tbody></table>
    <ul class="actions" id="deskActions">${o.selected_candidate_ids.map((id) => { const g = S.geo?.facilities.find((x) => x.id === id);
      return `<li><span class="verb ${g?.kind === "new" ? "build" : ""}">${!g ? "ADD" : g.kind === "new" ? "BUILD" : "REOPEN"}</span><span>${esc(siteName(id))}<small>${esc(g ? `${g.type_name} · ${g.tehsil}` : "")}</small></span></li>`; }).join("")}</ul>
    <div class="mini-note"><a href="#results">Full comparison, audit and stories →</a></div>`;
  $("deskResult").innerHTML = html;
  $("deskResult").querySelectorAll("[data-when]").forEach((x) => x.addEventListener("click", () => { S.deskWhen = x.dataset.when; renderDesk(); }));
  if (!S.geo) { $("deskCoord").innerHTML = ""; return; }
  try {
    const key = `${o.run_id}|${okB ? b.run_id : ""}`;
    const co = S.coord[key] || (S.coord[key] = await api(`/runs/${o.run_id}/coordination${okB ? `?base_run_id=${b.run_id}` : ""}`));
    $("deskCoord").innerHTML = `<h2>Health + education <small>by tehsil</small></h2>
      <table class="ba"><thead><tr><th>Tehsil</th><th class="num">Health reach</th><th class="num">Literacy</th><th class="num">Joint need</th></tr></thead><tbody>${
        co.tehsils.slice().sort((a2, b2) => a2.joint_priority_rank - b2.joint_priority_rank).map((t) => `<tr><td>${esc(t.tehsil)}</td><td class="num">${t.baseline_health_coverage_pct !== null ? `${pct(t.baseline_health_coverage_pct)} → ` : ""}${pct(t.health_coverage_pct)}</td><td class="num">${t.literacy_pct}%</td><td class="num">#${t.joint_priority_rank}</td></tr>`).join("")}</tbody></table>
      ${co.hubs.filter((h) => h.below_district_literacy).slice(0, 3).map((h) => `<div class="alert info">${icon("users", "sm")}<div><b>${esc(h.label)}</b> (${esc(h.tehsil)}): ${esc(h.suggestion)}</div></div>`).join("")}
      <div class="mini-note">${esc(co.note)}</div>`;
  } catch (e) { $("deskCoord").innerHTML = `<div class="alert err">${icon("alert", "sm")}<div>Coordination failed: ${esc(e.message)}</div></div>`; }
}

function renderDeskVillage() {
  const box = $("deskVillage");
  if (!box || !S.geo || !S.journeyPick) { if (box) box.innerHTML = ""; return; }
  const cl = S.geo.clusters.find((x) => x.id === S.journeyPick);
  if (!cl) { box.innerHTML = ""; return; }
  const o = deskRun();
  const existing = S.dataset.sites.filter((x) => x.type === "existing").map((x) => x.id);
  const thr = o ? o.plan.threshold_minutes : (S.dsInfo?.default_plan?.threshold_minutes || 45);
  if (o) {
    const r = journeyRows(S.runs.baseline?.status === "COMPLETED" ? S.runs.baseline : null, o).find((x) => x.id === cl.id);
    box.innerHTML = `<h2>${esc(cl.name)} <small>${esc(cl.tehsil)} · ≈ ${num(cl.population)} people</small></h2>${journeyCard(r, thr, Math.max(thr * 1.5, r.before?.t || 0))}`;
  } else {
    const nb = GeoMap.nearestOpen(cl.id, existing, S.minutes);
    box.innerHTML = `<h2>${esc(cl.name)} <small>${esc(cl.tehsil)} · ≈ ${num(cl.population)} people</small></h2>
      <p class="small">Nearest working facility: <b>${nb ? `${esc(siteName(nb.id))}, about ${mm(nb.t)}` : "no route"}</b>. Run a plan to see how this changes.</p>`;
  }
}

(function wireDesk() {
  document.querySelectorAll("[data-mapmode]").forEach((b) => b.addEventListener("click", () => {
    S.mapLayer = b.dataset.mapmode;
    document.querySelectorAll("[data-mapmode]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    renderDesk();
  }));
  const tg = { lyrRoads: "roads", lyrSettle: "settlements", lyrCand: "candidates", lyrFlows: "flows" };
  for (const [id, k] of Object.entries(tg)) $(id)?.addEventListener("change", (e) => { S.layers[k] = e.target.checked; renderDesk(); });
})();
