"""Fixed-seed stress tests (SRS FR-09, §6.2).

A scenario sensitivity experiment, not a forecast. Each case draws one integer demand
multiplier (80-130%) and one travel multiplier (90-140%) with random.Random(seed).
Both plans keep their site selections fixed and are re-assigned on identical cases.
"""

from __future__ import annotations

import random
import time
from typing import Any

import numpy as np

from .dataset.schema import Dataset
from .optimizer.problem import build_problem
from .planspec import PlanSpec
from .run import execute_run
from .travel import TravelMatrix

DEMAND_RANGE = (80, 130)
TRAVEL_RANGE = (90, 140)
MAX_CASES = 20
QUANTILE_METHOD = "linear"  # numpy default (Hyndman & Fan type 7)

TRACKED = ("coverage_pct", "served_rate_pct", "unmet_rate_pct", "worst_cluster_coverage_pct",
           "mean_travel_min")


def stress_cases(seed: int, count: int) -> list[dict[str, int]]:
    if not 1 <= count <= MAX_CASES:
        raise ValueError(f"case count must be 1..{MAX_CASES}")
    rng = random.Random(seed)
    return [{"case": i + 1, "demand_pct": rng.randint(*DEMAND_RANGE),
             "travel_pct": rng.randint(*TRAVEL_RANGE)} for i in range(count)]


def _summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "median": None, "min": None, "max": None, "p10": None, "p90": None}
    arr = np.array(values, dtype=float)
    return {
        "n": len(values),
        "median": float(np.median(arr)),
        "min": float(arr.min()),
        "max": float(arr.max()),
        "p10": float(np.percentile(arr, 10, method=QUANTILE_METHOD)),
        "p90": float(np.percentile(arr, 90, method=QUANTILE_METHOD)),
    }


def run_stress(
    ds: Dataset,
    tm: TravelMatrix,
    plan: PlanSpec,
    base_run: dict[str, Any],
    alt_run: dict[str, Any],
    *,
    seed: int = 2026,
    count: int = 20,
    time_limit_s: float = 60.0,
    backend: str | None = None,
    coverage_target_pct: float | None = None,
) -> dict[str, Any]:
    for r in (base_run, alt_run):
        if r.get("status") != "COMPLETED":
            raise ValueError("stress tests need two COMPLETED, audited runs")
    if base_run["plan_hash"] != alt_run["plan_hash"] or \
            base_run["dataset_sha256"] != alt_run["dataset_sha256"]:
        raise ValueError("runs must share dataset hash and plan hash")
    if plan.plan_hash() != base_run["plan_hash"]:
        raise ValueError("plan does not match the runs being stress-tested")

    t0 = time.monotonic()
    cases = stress_cases(seed, count)
    plans = {"base": base_run, "alt": alt_run}
    per_case: list[dict[str, Any]] = []
    timed_out = False
    for case in cases:
        row: dict[str, Any] = {**case}
        for label, run in plans.items():
            remaining = time_limit_s - (time.monotonic() - t0)
            if remaining <= 0.2:
                timed_out = True
                row[label] = {"status": "NOT_RUN"}
                continue
            p = build_problem(ds, tm, plan, stress_demand_pct=case["demand_pct"],
                              stress_travel_pct=case["travel_pct"])
            rec = execute_run(p, "stress_case", open_candidates=run["selected_candidate_ids"],
                              time_limit_s=min(remaining, 10.0), backend=backend)
            obs: dict[str, Any] = {"status": rec["status"], "solver_status": rec["solver_status"]}
            if rec["status"] == "COMPLETED":
                m = rec["metrics"]
                obs.update({k: m[k]["value"] for k in TRACKED})
                obs["within_threshold_visits"] = m["within_threshold_visits"]["value"]
                obs["total_demand"] = m["total_demand"]["value"]
                obs["worst_cluster_id"] = m["worst_cluster_coverage_pct"]["community_id"]
                obs["audit_passed"] = True
            else:
                obs["reason"] = (rec.get("error") or {}).get("reason")
            row[label] = obs
        if row["base"].get("status") == "COMPLETED" and row["alt"].get("status") == "COMPLETED":
            row["coverage_gain_pp"] = row["alt"]["coverage_pct"] - row["base"]["coverage_pct"]
        per_case.append(row)

    def stats(label: str) -> dict[str, Any]:
        ok = [r[label] for r in per_case if r[label].get("status") == "COMPLETED"]
        failed = [r for r in per_case if r[label].get("status") not in ("COMPLETED", "NOT_RUN")]
        out = {
            "successful_cases": len(ok),
            "failed_cases": len(failed),
            "not_run_cases": sum(1 for r in per_case if r[label].get("status") == "NOT_RUN"),
            "failure_rate_pct": 100.0 * len(failed) / len(per_case),
            "metrics": {k: _summary([o[k] for o in ok if o[k] is not None]) for k in TRACKED},
        }
        if coverage_target_pct is not None:
            out["below_coverage_target_cases"] = sum(
                1 for o in ok if o["coverage_pct"] < coverage_target_pct)
        return out

    gains = [r["coverage_gain_pp"] for r in per_case if "coverage_gain_pp" in r]
    return {
        "seed": seed,
        "case_count": count,
        "demand_range_pct": list(DEMAND_RANGE),
        "travel_range_pct": list(TRAVEL_RANGE),
        "quantile_method": QUANTILE_METHOD,
        "base_run_id": base_run["run_id"],
        "alt_run_id": alt_run["run_id"],
        "base_selection": base_run["selected_candidate_ids"],
        "alt_selection": alt_run["selected_candidate_ids"],
        "coverage_target_pct": coverage_target_pct,
        "cases": per_case,
        "summary": {"base": stats("base"), "alt": stats("alt"),
                    "coverage_gain_pp": _summary(gains),
                    "alt_better_or_equal_cases": sum(1 for g in gains if g >= 0)},
        "timed_out": timed_out,
        "runtime_ms": int((time.monotonic() - t0) * 1000),
        "caveat": ("Scenario ranges from illustrative multipliers, not confidence intervals or "
                   "real-world probabilities."),
    }
