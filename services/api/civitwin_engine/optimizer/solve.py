"""Lexicographic allocation model (SRS §5).

Variables: x_j (candidate activation, binary), y_ij (assigned visits, reachable pairs
only), u_i (unmet visits), m (equity score, basis points). Existing sites are fixed open.
Stages share one wall-clock budget; each proven optimum is fixed before the next stage.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any

from .linmodel import Expr, LinModel, default_backend, solve_lexicographic
from .problem import Problem, ProblemError

STAGES: dict[str, list[tuple[str, str]]] = {
    "coverage_first": [("W", "max"), ("S", "max"), ("m", "max"), ("L", "min"), ("C", "min")],
    # decision D10: m moves to the front, the others keep their order
    "equity_first": [("m", "max"), ("W", "max"), ("S", "max"), ("L", "min"), ("C", "min")],
    "cost_efficient": [("C", "min"), ("W", "max"), ("S", "max"), ("L", "min")],
}
STAGE_LABELS = {
    "W": "within-threshold visits",
    "S": "served visits",
    "m": "equity score (worst-cluster coverage, basis points)",
    "L": "visit-minutes",
    "C": "weekly cost (PKR)",
}


def min_units_for_reach(p: Problem, backend: str | None = None) -> dict[str, Any] | None:
    """Fewest (then cheapest) new units so every positive-demand cluster has at least one
    open site within the threshold. A necessary condition for any equity floor > 0; capacity
    may require more. Returns None if some cluster cannot be reached at all."""
    need = [c for c in p.community_ids if p.demand[c] > 0
            and not any(p.within(c, s) for s in p.existing_ids)]
    if not need:
        return {"units": 0, "cost_pkr": 0, "sites": []}
    lm = LinModel()
    x = {j: lm.var(f"x_{j}", 0, 1) for j in p.eligible_candidate_ids}
    for c in need:
        opts = {x[j]: 1 for j in x if p.within(c, j)}
        if not opts:
            return None
        lm.add(opts, lo=1)
    exprs = {"U": Expr({v: 1 for v in x.values()}), "C": Expr({v: p.cost[j] for j, v in x.items()})}
    out = solve_lexicographic(lm, exprs, [("U", "min"), ("C", "min")],
                              {"U": "new units", "C": "cost"}, time_limit_s=2.0, seed=0,
                              backend=backend or default_backend())
    if out.kind != "SOLVED" or out.values is None:
        return None
    sites = sorted(j for j, v in x.items() if out.values[v] == 1)
    return {"units": len(sites), "cost_pkr": sum(p.cost[j] for j in sites), "sites": sites}


def infeasibility_hints(p: Problem, open_fixed: set[str] | None,
                        backend: str | None = None) -> list[str]:
    """Plain diagnostics; never applied automatically (SRS §5.2, §5.4)."""
    hints: list[str] = []
    q = p.plan.equity_min_pct
    possible = set(p.existing_ids) | (
        set(p.eligible_candidate_ids) if open_fixed is None else set(open_fixed)
    )
    if q > 0:
        no_existing = [c for c in p.community_ids if p.demand[c] > 0
                       and not any(p.within(c, s) for s in p.existing_ids)]
        if open_fixed is not None and not open_fixed and no_existing:
            hints.append(f"With existing sites only, clusters {', '.join(no_existing)} have no "
                         f"site within {p.threshold} minutes, so a {q}% floor cannot be met.")
        if open_fixed is None:
            reach = min_units_for_reach(p, backend)
            if reach is not None and reach["units"] > 0:
                hints.append(
                    f"Giving every cluster any site within {p.threshold} minutes needs at least "
                    f"{reach['units']} new units (cheapest such set: {', '.join(reach['sites'])}, "
                    f"PKR {reach['cost_pkr']:,}/week). This plan allows {p.plan.max_new_units} "
                    f"units and PKR {p.plan.budget_pkr:,}. Capacity may require more.")
        per_cluster: list[str] = []
        summarized = open_fixed is not None and not open_fixed and bool(no_existing)
        for c in p.community_ids:
            d = p.demand[c]
            if d == 0:
                continue
            need = math.ceil(q * d / 100)
            cap = sum(p.capacity[s] for s in possible if p.within(c, s))
            if cap == 0 and not summarized:
                per_cluster.append(f"Cluster {c} has no site within {p.threshold} minutes, so it "
                                   f"cannot reach a {q}% equity floor.")
            elif 0 < cap < need:
                per_cluster.append(f"Cluster {c} needs {need} visits within {p.threshold} minutes "
                                   f"but nearby capacity is only {cap}.")
        hints += per_cluster[:5]
        if len(per_cluster) > 5:
            hints.append(f"…and {len(per_cluster) - 5} more cluster(s) with the same problem.")
        hints.append("Try lowering the equity floor, raising the travel threshold, or revising "
                     "budget, unit limit or capacity assumptions.")
    if p.plan.policy == "cost_efficient":
        hints.append(f"The minimum coverage target of {p.plan.min_coverage_pct}% may be "
                     "unreachable with the available sites, budget and unit limit.")
    if open_fixed is not None:
        cost = sum(p.cost[s] for s in open_fixed)
        if cost > p.plan.budget_pkr:
            hints.append(f"The fixed site selection costs PKR {cost:,}, above the budget of "
                         f"PKR {p.plan.budget_pkr:,}.")
        if len(open_fixed) > p.plan.max_new_units:
            hints.append("The fixed site selection exceeds the new-unit limit.")
    if not hints:
        hints.append("Review budget, unit limit, capacity and equity assumptions.")
    return hints


def solve(
    p: Problem,
    kind: str,
    *,
    open_candidates: list[str] | None = None,
    time_limit_s: float = 10.0,
    cancel: threading.Event | None = None,
    backend: str | None = None,
    max_stages: int | None = None,
) -> dict[str, Any]:
    """Return a raw solve record (not yet audited).

    max_stages truncates the lexicographic stages (used only by the greedy benchmark's
    inner coverage evaluation; published runs always use the full policy).

    kind: "baseline" (all candidates closed), "optimized" (solver chooses), or a fixed
    selection kind ("greedy", "stress_case") that requires open_candidates.
    """
    t0 = time.monotonic()
    backend = backend or default_backend()
    if kind == "baseline":
        fixed: set[str] | None = set()
    elif kind == "optimized":
        fixed = None
    else:
        if open_candidates is None:
            raise ProblemError(f"kind {kind!r} needs a fixed candidate selection")
        fixed = set(open_candidates)
    if fixed is not None:
        bad = sorted(fixed - set(p.eligible_candidate_ids))
        if bad:
            raise ProblemError(f"fixed selection contains non-eligible candidates: {bad}")

    plan = p.plan
    stages = STAGES[plan.policy][: max_stages or None]

    def elapsed_ms() -> int:
        return int((time.monotonic() - t0) * 1000)

    def no_solution(reason: str) -> dict[str, Any]:
        return {"kind": kind, "status": "NO_SOLUTION", "solver_status": "INFEASIBLE",
                "reason": reason, "hints": infeasibility_hints(p, fixed, backend),
                "objective_stages": [], "runtime_ms": elapsed_ms()}

    lm = LinModel()

    # --- activation -------------------------------------------------------
    x: dict[str, int] = {}
    const_open: set[str] = set(p.existing_ids)
    for j in p.candidate_ids:
        if fixed is None:
            if p.eligible[j]:
                x[j] = lm.var(f"x_{j}", 0, 1)
        elif j in fixed:
            const_open.add(j)
    const_cost = sum(p.cost[j] for j in const_open if p.site_type[j] == "candidate")
    const_units = sum(1 for j in const_open if p.site_type[j] == "candidate")
    if const_cost > plan.budget_pkr or const_units > plan.max_new_units:
        return no_solution("Fixed site selection violates the budget or unit limit.")

    # --- assignment -------------------------------------------------------
    y: dict[tuple[str, str], int] = {}
    for i in p.community_ids:
        for j in p.site_ids:
            if ((i, j) in p.travel and (j in const_open or j in x)
                    and p.demand[i] > 0 and p.capacity[j] > 0):
                y[(i, j)] = lm.var(f"y_{i}_{j}", 0, min(p.demand[i], p.capacity[j]))
    u = {i: lm.var(f"u_{i}", 0, p.demand[i]) for i in p.community_ids}
    m = lm.var("m", 0, 10_000)

    for i in p.community_ids:  # demand balance
        coeffs = {v: 1 for (ci, _), v in y.items() if ci == i}
        coeffs[u[i]] = 1
        lm.add(coeffs, p.demand[i], p.demand[i])
    for j in p.site_ids:  # capacity
        coeffs = {v: 1 for (_, sj), v in y.items() if sj == j}
        if not coeffs:
            continue
        if j in x:
            coeffs[x[j]] = -p.capacity[j]
            lm.add(coeffs, hi=0)
        else:
            lm.add(coeffs, hi=p.capacity[j])
    if x:  # budget and unit count
        lm.add({v: p.cost[j] for j, v in x.items()}, hi=plan.budget_pkr - const_cost)
        lm.add({v: 1 for v in x.values()}, hi=plan.max_new_units - const_units)

    within = {i: [v for (ci, sj), v in y.items() if ci == i and p.within(ci, sj)]
              for i in p.community_ids}
    q = plan.equity_min_pct
    for i in p.community_ids:
        d = p.demand[i]
        if d == 0:
            continue
        if q > 0:
            if not within[i]:
                return no_solution(f"Cluster {i} cannot reach the {q}% equity floor.")
            lm.add({v: 100 for v in within[i]}, lo=q * d)  # 100*within_i >= q*D_i
        coeffs = {v: 10_000 for v in within[i]}
        coeffs[m] = -d
        lm.add(coeffs, lo=0)  # 10000*within_i >= m*D_i

    all_within = [v for vs in within.values() for v in vs]
    exprs = {
        "W": Expr({v: 1 for v in all_within}),
        "S": Expr({v: 1 for v in y.values()}),
        "L": Expr({v: p.travel[k] for k, v in y.items()}),
        "C": Expr({v: p.cost[j] for j, v in x.items()}, const_cost),
        "m": Expr({m: 1}),
    }
    if plan.policy == "cost_efficient":
        target = math.ceil((plan.min_coverage_pct or 0) * p.total_demand / 100)
        if target > 0 and not all_within:
            return no_solution("The minimum coverage target is unreachable.")
        if all_within:
            lm.add({v: 1 for v in all_within}, lo=target)

    outcome = solve_lexicographic(
        lm, exprs, stages, STAGE_LABELS, time_limit_s=max(time_limit_s - (time.monotonic() - t0),
                                                          0.05),
        seed=plan.seed, backend=backend, cancel=cancel,
    )
    engine = {"backend": outcome.backend, "solver_version": outcome.backend_version,
              "num_workers": 1, "random_seed": plan.seed, "time_limit_s": time_limit_s,
              "policy": plan.policy, "stages": [s for s, _ in stages],
              "variables": len(lm.names), "constraints": len(lm.rows)}

    if outcome.kind == "INFEASIBLE":
        rec = no_solution("The model is infeasible under the confirmed plan.")
        rec["engine"] = engine
        return rec
    if outcome.kind != "SOLVED":
        return {"kind": kind, "status": outcome.kind, "solver_status": outcome.kind,
                "reason": outcome.stopped_reason, "objective_stages": outcome.stage_log,
                "runtime_ms": elapsed_ms(), "engine": engine}

    vals = outcome.values
    assert vals is not None
    assignments = [
        {"community_id": i, "site_id": j, "visits": vals[v], "minutes": p.travel[(i, j)]}
        for (i, j), v in sorted(y.items())
        if vals[v] > 0
    ]
    unmet = [{"community_id": i, "visits": vals[u[i]]} for i in p.community_ids]
    selected = sorted([j for j in p.candidate_ids if j in const_open]
                      + [j for j, v in x.items() if vals[v] == 1])
    proven = all(s["status"] == "OPTIMAL" for s in outcome.stage_log)
    return {
        "kind": kind,
        "status": "SOLVED",
        "solver_status": "OPTIMAL" if proven else "FEASIBLE",
        "optimality": "proven" if proven else "not_proven",
        "stopped_reason": outcome.stopped_reason,
        "selected_candidate_ids": selected,
        "assignments": assignments,
        "unmet_by_community": unmet,
        "objective_stages": outcome.stage_log,
        "runtime_ms": elapsed_ms(),
        "engine": engine,
    }
