"""Decision-support analyses built on the audited solver.

* tradeoff_curve — coverage reached at a range of weekly budgets (SRS P1 "frontier"
  visualisation), for the plan's unit limit and with the unit limit relaxed.
* site_impact — for each opened site: the visits it serves, the clusters it reaches,
  and what is lost if only that site is removed (leave-one-out, same policy).

Every number comes from execute_run, so every point is solved and independently
audited; points that are infeasible or time out are reported as such, never filled in.
"""

from __future__ import annotations

import time
from typing import Any

from .dataset.schema import Dataset
from .optimizer.problem import build_problem
from .planspec import PlanSpec
from .run import execute_run
from .travel import TravelMatrix

DEFAULT_BUDGETS = tuple(range(0, 800_001, 100_000))


def _summary(run: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"status": run["status"], "solver_status": run.get("solver_status")}
    if run["status"] == "COMPLETED":
        m = run["metrics"]
        out.update({
            "coverage_pct": m["coverage_pct"]["value"],
            "within_threshold_visits": m["within_threshold_visits"]["value"],
            "worst_cluster_coverage_pct": m["worst_cluster_coverage_pct"]["value"],
            "unmet": m["unmet"]["value"],
            "cost_pkr": m["cost_pkr"]["value"],
            "selected_candidate_ids": run["selected_candidate_ids"],
            "audit_passed": run["audit"]["passed"],
            "optimality": run["optimality"],
        })
    return out


def tradeoff_curve(
    ds: Dataset,
    tm: TravelMatrix,
    plan: PlanSpec,
    *,
    budgets: tuple[int, ...] = DEFAULT_BUDGETS,
    backend: str | None = None,
    time_limit_s: float = 45.0,
) -> dict[str, Any]:
    eligible = sum(1 for s in ds.sites if s.type == "candidate" and s.eligible)
    unit_limits = sorted({plan.max_new_units, eligible})
    t0 = time.monotonic()
    curves = []
    for units in unit_limits:
        points = []
        for b in budgets:
            remaining = time_limit_s - (time.monotonic() - t0)
            if remaining <= 0.3:
                points.append({"budget_pkr": b, "status": "NOT_RUN"})
                continue
            variant = plan.model_copy(update={"budget_pkr": b, "max_new_units": units})
            run = execute_run(build_problem(ds, tm, variant), "optimized",
                              time_limit_s=min(10.0, remaining), backend=backend)
            points.append({"budget_pkr": b, **_summary(run)})
        # marginal coverage per extra PKR 100,000 between consecutive completed points
        prev = None
        for pt in points:
            if pt["status"] == "COMPLETED":
                if prev is not None:
                    step = (pt["budget_pkr"] - prev["budget_pkr"]) / 100_000
                    pt["gain_pp_per_lakh"] = (pt["coverage_pct"] - prev["coverage_pct"]) / step
                prev = pt
        curves.append({"max_new_units": units, "is_plan_limit": units == plan.max_new_units,
                       "points": points})
    return {
        "plan_hash": plan.plan_hash(),
        "threshold_minutes": plan.threshold_minutes,
        "current_budget_pkr": plan.budget_pkr,
        "budgets": list(budgets),
        "curves": curves,
        "runtime_ms": int((time.monotonic() - t0) * 1000),
        "note": ("Each point is a separate optimized, audited run with only the budget (and unit "
                 "limit) changed. Synthetic data; modeled visits, not people."),
    }


def site_impact(
    ds: Dataset,
    tm: TravelMatrix,
    plan: PlanSpec,
    run: dict[str, Any],
    *,
    backend: str | None = None,
) -> dict[str, Any]:
    if run.get("status") != "COMPLETED":
        raise ValueError("site impact needs a COMPLETED run")
    p = build_problem(ds, tm, plan)
    if run["plan_hash"] != p.plan_hash:
        raise ValueError("run does not belong to this plan")
    selected = list(run["selected_candidate_ids"])
    thr = plan.threshold_minutes
    total_w = run["metrics"]["within_threshold_visits"]["value"]
    total_d = run["metrics"]["total_demand"]["value"]
    sites = []
    for s in selected:
        mine = [a for a in run["assignments"] if a["site_id"] == s]
        within = sum(a["visits"] for a in mine if a["minutes"] <= thr)
        without = execute_run(p, "what_if", open_candidates=[x for x in selected if x != s],
                              backend=backend)
        entry: dict[str, Any] = {
            "site_id": s,
            "cost_pkr": p.cost[s],
            "capacity": p.capacity[s],
            "assigned_visits": sum(a["visits"] for a in mine),
            "within_threshold_visits": within,
            "clusters_served": [
                {"community_id": a["community_id"], "visits": a["visits"], "minutes": a["minutes"]}
                for a in sorted(mine, key=lambda a: -a["visits"])
            ],
            "if_removed_status": without["status"],
        }
        if without["status"] == "COMPLETED":
            w2 = without["metrics"]["within_threshold_visits"]["value"]
            lost = total_w - w2
            entry.update({
                "within_lost_if_removed": lost,
                "coverage_lost_pp_if_removed": 100.0 * lost / total_d if total_d else None,
                "cost_per_within_visit_kept": (p.cost[s] / lost) if lost > 0 else None,
                "if_removed_audit_passed": without["audit"]["passed"],
            })
        sites.append(entry)
    return {"run_id": run["run_id"], "plan_hash": run["plan_hash"], "threshold_minutes": thr,
            "sites": sites,
            "note": "Leave-one-out: re-solved with only that site closed, same policy and inputs."}


def coordination(run: dict[str, Any], geo: dict[str, Any],
                 base_run: dict[str, Any] | None = None) -> dict[str, Any]:
    """Coordinate health planning with education need, by tehsil (real census literacy).

    Health coverage comes from the audited run; literacy from PBS Census 2023. School
    locations are not openly published for Bajaur, so education enters as a need signal:
    the joint priority index and the service-hub suggestions are labelled as such.
    """
    if run.get("status") != "COMPLETED":
        raise ValueError("coordination needs a COMPLETED run")
    thr = run["plan"]["threshold_minutes"]
    tehsil_of = {c["id"]: c["tehsil"] for c in geo["clusters"]}
    pop_of = {c["id"]: c["population"] for c in geo["clusters"]}
    fac = {f["id"]: f for f in geo["facilities"]}
    lit_mean = geo["literacy_district_weighted_pct"]

    def by_tehsil(r: dict[str, Any] | None) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        if not r or r.get("status") != "COMPLETED":
            return out
        for pc in r["metrics"]["per_cluster"]:
            t = tehsil_of.get(pc["community_id"])
            if t is None:
                continue
            o = out.setdefault(t, {"demand": 0, "within": 0, "unmet": 0})
            o["demand"] += pc["demand"]; o["within"] += pc["within_threshold"]; o["unmet"] += pc["unmet"]
        return out

    plan_t, base_t = by_tehsil(run), by_tehsil(base_run)
    new_sites = {s: fac[s] for s in run["selected_candidate_ids"] if s in fac}
    rows = []
    for t in geo["tehsils"]:
        name = t["name"]
        pt = plan_t.get(name, {"demand": 0, "within": 0, "unmet": 0})
        cov = 100.0 * pt["within"] / pt["demand"] if pt["demand"] else None
        bt = base_t.get(name)
        bcov = 100.0 * bt["within"] / bt["demand"] if bt and bt["demand"] else None
        lit = t["literacy_pct"]
        joint = None if cov is None else (1 - cov / 100) * (1 - lit / 100)
        rows.append({"tehsil": name, "population": t["population"], "literacy_pct": lit,
                     "literacy_gap_pp": round(lit_mean - lit, 2), "health_coverage_pct": cov,
                     "baseline_health_coverage_pct": bcov, "unmet_visits": pt["unmet"],
                     "new_sites": [s for s, f in new_sites.items() if f["tehsil"] == name],
                     "joint_priority_index": joint})
    ranked = sorted([r for r in rows if r["joint_priority_index"] is not None], key=lambda r: -r["joint_priority_index"])
    for i, r in enumerate(ranked, 1):
        r["joint_priority_rank"] = i

    hubs = []
    for sid, f in new_sites.items():
        mine = [a for a in run["assignments"] if a["site_id"] == sid]
        within = sum(a["visits"] for a in mine if a["minutes"] <= thr)
        clusters = sorted({a["community_id"] for a in mine})
        people = sum(pop_of.get(c, 0) for c in clusters)
        lit = next(t["literacy_pct"] for t in geo["tehsils"] if t["name"] == f["tehsil"])
        hubs.append({
            "site_id": sid, "label": f["label"], "type_name": f["type_name"], "tehsil": f["tehsil"],
            "action": "Reactivate" if f["kind"] == "reactivate" else "Build",
            "within_threshold_visits": within, "clusters_served": len(clusters), "people_in_served_clusters": people,
            "tehsil_literacy_pct": lit, "below_district_literacy": lit < lit_mean,
            "hub_score": round(within * (1 - lit / 100), 1),
            "suggestion": ("Co-locate a community school or adult-literacy class with this health unit — the tehsil's "
                           f"literacy ({lit:.1f}%) is below the district average ({lit_mean:.1f}%)." if lit < lit_mean else
                           "Health unit first; tehsil literacy is at or above the district average."),
        })
    hubs.sort(key=lambda h: -h["hub_score"])
    return {"run_id": run["run_id"], "threshold_minutes": thr, "district_literacy_pct": lit_mean,
            "tehsils": rows, "hubs": hubs,
            "note": ("Health coverage is from the audited plan; literacy is PBS Census 2023. School locations are not "
                     "openly published for Bajaur, so education is used as a need signal: the joint index = "
                     "(share of visits not reached) x (share of people not literate). Suggestions are for discussion.")}
