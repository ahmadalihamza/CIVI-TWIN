"""Deterministic greedy benchmark (SRS §6.3, decision D7).

Each round adds the eligible, affordable candidate with the largest *estimated* gain in
within-threshold visits per PKR, then re-solves the assignment (coverage stage) to update
who is covered. The estimate for a candidate is
    min(capacity, sum of not-yet-covered demand of clusters within the threshold),
a standard capacity-aware greedy rule that needs no solve per candidate, so the benchmark
stays fast on real data. Zero-cost candidates rank first; ties break by smallest ID.
The final greedy plan is solved with the full confirmed policy and audited like any run.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from .optimizer.problem import Problem
from .optimizer.solve import solve
from .run import execute_run


def _within_by_cluster(p: Problem, selection: list[str], backend: str | None,
                       limit: float) -> dict[str, int] | None:
    rec = solve(p, "greedy", open_candidates=selection, time_limit_s=limit, backend=backend,
                max_stages=1)
    if rec["status"] != "SOLVED":
        return None
    out = {c: 0 for c in p.community_ids}
    for a in rec["assignments"]:
        if a["minutes"] <= p.threshold:
            out[a["community_id"]] += a["visits"]
    return out


def greedy_selection(p: Problem, *, backend: str | None = None,
                     time_limit_s: float = 30.0) -> tuple[list[str], list[dict[str, Any]]]:
    t0 = time.monotonic()
    # choose on coverage alone (no floor); the final solve enforces the confirmed plan
    p_cov = replace(p, plan=p.plan.model_copy(update={"equity_min_pct": 0, "policy": "coverage_first",
                                                      "min_coverage_pct": None}))
    selection: list[str] = []
    trace: list[dict[str, Any]] = []
    within = _within_by_cluster(p_cov, [], backend, time_limit_s) or {c: 0 for c in p.community_ids}
    reach = {c: [i for i in p.community_ids if p.within(i, c)] for c in p.eligible_candidate_ids}
    while len(selection) < p.plan.max_new_units:
        spent = sum(p.cost[s] for s in selection)
        best: tuple[float, str, int] | None = None
        for c in sorted(p.eligible_candidate_ids):
            if c in selection or spent + p.cost[c] > p.plan.budget_pkr:
                continue
            est = min(p.capacity[c], sum(p.demand[i] - within[i] for i in reach[c]))
            if est <= 0:
                continue
            score = float("inf") if p.cost[c] == 0 else est / p.cost[c]
            if best is None or score > best[0] or (score == best[0] and c < best[1]):
                best = (score, c, est)
        if best is None:
            break
        remaining = time_limit_s - (time.monotonic() - t0)
        if remaining <= 0.2:
            break
        before = sum(within.values())
        new = _within_by_cluster(p_cov, sorted(selection + [best[1]]), backend, remaining)
        if new is None:
            break
        selection = sorted(selection + [best[1]])
        within = new
        trace.append({"added": best[1], "estimated_gain": best[2],
                      "gain_within_visits": sum(within.values()) - before,
                      "cost_pkr": p.cost[best[1]], "within_after": sum(within.values())})
    return selection, trace


def execute_greedy(p: Problem, *, backend: str | None = None, time_limit_s: float = 30.0,
                   scenario_id: str | None = None) -> dict[str, Any]:
    t0 = time.monotonic()
    selection, trace = greedy_selection(p, backend=backend, time_limit_s=time_limit_s)
    rec = execute_run(p, "greedy", open_candidates=selection,
                      time_limit_s=max(time_limit_s - (time.monotonic() - t0), 5.0),
                      backend=backend, scenario_id=scenario_id)
    rec["greedy_trace"] = trace
    rec["runtime_ms"] = int((time.monotonic() - t0) * 1000)
    return rec
