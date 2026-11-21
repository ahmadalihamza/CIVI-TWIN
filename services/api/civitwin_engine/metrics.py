"""Metric definitions (SRS §6.1). Exact integer totals; rounding is for display only."""

from __future__ import annotations

from typing import Any

from .optimizer.problem import Problem


def metric(value: float | int | None, unit: str, numerator: int | None = None,
           denominator: int | None = None, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"value": value, "unit": unit, "numerator": numerator,
                           "denominator": denominator}
    out.update(extra)
    return out


def ratio_pct(num: int, den: int) -> float | None:
    return None if den == 0 else 100.0 * num / den


def compute_metrics(
    problem: Problem,
    assignments: list[dict[str, Any]],
    unmet: list[dict[str, Any]],
    selected: list[str],
) -> dict[str, Any]:
    D = problem.total_demand
    within_by: dict[str, int] = {c: 0 for c in problem.community_ids}
    served_by: dict[str, int] = {c: 0 for c in problem.community_ids}
    S = W = L = 0
    for a in assignments:
        v = a["visits"]
        S += v
        served_by[a["community_id"]] += v
        L += a["minutes"] * v
        if a["minutes"] <= problem.threshold:
            W += v
            within_by[a["community_id"]] += v
    U = sum(u["visits"] for u in unmet)
    C = sum(problem.cost[s] for s in selected)

    per_cluster = []
    for c in problem.community_ids:
        d = problem.demand[c]
        per_cluster.append({
            "community_id": c,
            "demand": d,
            "served": served_by[c],
            "within_threshold": within_by[c],
            "unmet": d - served_by[c],
            "coverage_pct": ratio_pct(within_by[c], d),
        })
    positive = [p for p in per_cluster if p["demand"] > 0]
    worst = min(positive, key=lambda p: (p["coverage_pct"], p["community_id"]), default=None)
    best = max(positive, key=lambda p: (p["coverage_pct"], p["community_id"]), default=None)
    # Equity score m in basis points: min over positive-demand clusters of
    # floor(10000 * within_i / D_i), matching 10000*within_i >= m*D_i.
    m = min((10_000 * p["within_threshold"] // p["demand"] for p in positive), default=0)

    B = problem.plan.budget_pkr
    return {
        "total_demand": metric(D, "visits/week"),
        "served": metric(S, "visits/week"),
        "served_rate_pct": metric(ratio_pct(S, D), "%", S, D),
        "unmet": metric(U, "visits/week"),
        "unmet_rate_pct": metric(ratio_pct(U, D), "%", U, D),
        "within_threshold_visits": metric(W, "visits/week"),
        "coverage_pct": metric(ratio_pct(W, D), "%", W, D),
        "visit_minutes": metric(L, "visit-minutes"),
        "mean_travel_min": metric(None if S == 0 else L / S, "minutes", L, S),
        "worst_cluster_coverage_pct": metric(
            None if worst is None else worst["coverage_pct"], "%",
            None if worst is None else worst["within_threshold"],
            None if worst is None else worst["demand"],
            community_id=None if worst is None else worst["community_id"]),
        "equity_gap_pp": metric(
            None if worst is None else best["coverage_pct"] - worst["coverage_pct"],  # type: ignore[index]
            "percentage points"),
        "equity_score_bp": metric(m, "basis points"),
        "cost_pkr": metric(C, "PKR/week"),
        "budget_utilization_pct": metric(ratio_pct(C, B), "%", C, B),
        "new_units": metric(len(selected), "units"),
        "per_cluster": per_cluster,
    }
