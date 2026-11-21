"""Independent feasibility and metric audit (SRS FR-07, §5.4).

Reads only the serialized result and the planning inputs. It deliberately does not
import the solver or the metrics module: every quantity is recomputed here from scratch.
Any mismatch fails closed.
"""

from __future__ import annotations

import json
from typing import Any

from .hashing import sha256_of
from .optimizer.problem import Problem

HASHED_RESULT_FIELDS = (
    "kind", "dataset_sha256", "plan_hash", "selected_candidate_ids", "assignments",
    "unmet_by_community", "metrics",
)


def result_hash(result: dict[str, Any]) -> str:
    """Hash of the result content (excludes run id, timestamps, runtime and the audit)."""
    core: dict[str, Any] = {k: result.get(k) for k in HASHED_RESULT_FIELDS}
    core["objective_stages"] = [
        (s.get("stage"), s.get("status"), s.get("value")) for s in result.get("objective_stages", [])
    ]
    return sha256_of(core)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def audit_result(
    p: Problem,
    result: dict[str, Any],
    *,
    fixed_selection: list[str] | None = None,
) -> dict[str, Any]:
    # Work from a JSON round-trip so nothing but serialized data is inspected.
    r = json.loads(json.dumps(result))
    checks: list[dict[str, Any]] = []

    def check(cid: str, name: str, ok: bool, expected: Any = None, actual: Any = None) -> None:
        checks.append({"id": cid, "name": name, "passed": bool(ok),
                       "expected": expected, "actual": actual})

    assignments = r.get("assignments") or []
    unmet = r.get("unmet_by_community") or []
    selected = r.get("selected_candidate_ids") or []
    kind = r.get("kind")

    # A01 integrality and non-negativity
    bad_vals = [a for a in assignments if not _is_int(a.get("visits")) or a["visits"] < 0]
    bad_vals += [u for u in unmet if not _is_int(u.get("visits")) or u["visits"] < 0]
    check("A01", "Integer, non-negative visits", not bad_vals, 0, len(bad_vals))

    # A02 known IDs, no duplicates, unmet listed once per community
    cset, sset = set(p.community_ids), set(p.site_ids)
    foreign = [a for a in assignments if a.get("community_id") not in cset
               or a.get("site_id") not in sset]
    foreign += [u for u in unmet if u.get("community_id") not in cset]
    foreign_sel = [s for s in selected if s not in sset]
    pairs = [(a.get("community_id"), a.get("site_id")) for a in assignments]
    dup_pairs = len(pairs) - len(set(pairs))
    unmet_ids = [u.get("community_id") for u in unmet]
    unmet_ok = sorted(unmet_ids) == sorted(p.community_ids)
    check("A02", "No foreign or duplicate IDs; unmet listed for every community",
          not foreign and not foreign_sel and dup_pairs == 0 and unmet_ok,
          "0 foreign, 0 duplicates, all communities",
          {"foreign": len(foreign) + len(foreign_sel), "duplicates": dup_pairs,
           "unmet_complete": unmet_ok})
    if bad_vals or foreign or foreign_sel:
        # Cannot safely recompute further; fail closed.
        return _finish(r, checks)

    # A03 allowed (reachable) pairs with correct travel minutes
    bad_pairs = [a for a in assignments if (a["community_id"], a["site_id"]) not in p.travel
                 or a.get("minutes") != p.travel[(a["community_id"], a["site_id"])]]
    check("A03", "Assignments use reachable pairs with recorded travel minutes",
          not bad_pairs, 0, len(bad_pairs))

    # A04 demand balance
    served_by = {c: 0 for c in p.community_ids}
    for a in assignments:
        served_by[a["community_id"]] += a["visits"]
    unmet_by = {u["community_id"]: u["visits"] for u in unmet}
    imbalance = {c: served_by[c] + unmet_by.get(c, 0) - p.demand[c] for c in p.community_ids}
    bad_bal = {c: v for c, v in imbalance.items() if v != 0}
    check("A04", "Demand balance: assigned + unmet = demand", not bad_bal, {}, bad_bal)

    # A05 capacity; closed sites carry nothing
    open_sites = set(p.existing_ids) | set(selected)
    load = {s: 0 for s in p.site_ids}
    for a in assignments:
        load[a["site_id"]] += a["visits"]
    over = {s: load[s] for s in p.site_ids
            if load[s] > (p.capacity[s] if s in open_sites else 0)}
    check("A05", "Capacity respected; closed sites unused", not over, {}, over)

    # A06 selection validity
    sel_set = set(selected)
    not_candidate = sorted(s for s in sel_set if p.site_type.get(s) != "candidate")
    ineligible = sorted(s for s in sel_set if not p.eligible.get(s, False))
    sel_ok = not not_candidate and not ineligible and len(sel_set) == len(selected)
    if fixed_selection is not None:
        sel_ok = sel_ok and sel_set == set(fixed_selection)
    check("A06", "Selected sites are eligible candidates (and match any fixed selection)",
          sel_ok, sorted(fixed_selection) if fixed_selection is not None else "eligible only",
          sorted(sel_set))

    # A07 budget
    cost = sum(p.cost[s] for s in sel_set)
    check("A07", "Budget respected", cost <= p.plan.budget_pkr, f"<= {p.plan.budget_pkr}", cost)

    # A08 unit count
    check("A08", "New-unit limit respected", len(sel_set) <= p.plan.max_new_units,
          f"<= {p.plan.max_new_units}", len(sel_set))

    # A09 equity floor
    within_by = {c: 0 for c in p.community_ids}
    for a in assignments:
        if a["minutes"] <= p.threshold:
            within_by[a["community_id"]] += a["visits"]
    q = p.plan.equity_min_pct
    floor_fail = [c for c in p.community_ids
                  if p.demand[c] > 0 and 100 * within_by[c] < q * p.demand[c]]
    check("A09", f"Equity floor {q}% holds for every cluster", not floor_fail, [], floor_fail)

    # A10 reported metrics equal recomputed metrics
    D = p.total_demand
    S = sum(served_by.values())
    W = sum(within_by.values())
    L = sum(a["minutes"] * a["visits"] for a in assignments)
    U = sum(unmet_by.values())
    pos = [c for c in p.community_ids if p.demand[c] > 0]
    cov = {c: 100.0 * within_by[c] / p.demand[c] for c in pos}
    worst = min(cov.values()) if cov else None
    m_bp = min((10_000 * within_by[c] // p.demand[c] for c in pos), default=0)
    expected_metrics = {
        "total_demand": D, "served": S, "unmet": U, "within_threshold_visits": W,
        "visit_minutes": L, "cost_pkr": cost, "equity_score_bp": m_bp,
        "coverage_pct": None if D == 0 else 100.0 * W / D,
        "served_rate_pct": None if D == 0 else 100.0 * S / D,
        "mean_travel_min": None if S == 0 else L / S,
        "worst_cluster_coverage_pct": worst,
    }
    reported = r.get("metrics") or {}
    mismatches = {}
    for k, v in expected_metrics.items():
        got = (reported.get(k) or {}).get("value") if isinstance(reported.get(k), dict) else None
        if not _close(got, v):
            mismatches[k] = {"expected": v, "reported": got}
    stage_vals = {s["stage"]: s["value"] for s in r.get("objective_stages", [])
                  if s.get("value") is not None}
    stage_expected = {"W": W, "S": S, "L": L, "C": cost}
    for k, v in stage_vals.items():
        if k in stage_expected and stage_expected[k] != v:
            mismatches[f"stage_{k}"] = {"expected": stage_expected[k], "reported": v}
        if k == "m" and v > m_bp:
            mismatches["stage_m"] = {"expected": f"<= {m_bp}", "reported": v}
    check("A10", "Reported metrics and stage values match recomputation", not mismatches, {},
          mismatches)

    # A11 kind-specific rules
    kind_ok = kind != "baseline" or not sel_set
    check("A11", "Baseline opens no candidate sites", kind_ok, "[]" if kind == "baseline" else
          "n/a", sorted(sel_set) if kind == "baseline" else "n/a")

    # A12 result hash
    claimed = r.get("result_sha256")
    actual = result_hash(r)
    check("A12", "Result hash matches content", claimed == actual, claimed, actual)

    return _finish(r, checks)


def _finish(r: dict[str, Any], checks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "passed": bool(checks) and all(c["passed"] for c in checks),
        "checks": checks,
        "result_sha256": r.get("result_sha256"),
        "checks_run": len(checks),
    }
