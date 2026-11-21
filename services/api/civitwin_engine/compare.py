"""Result comparison (SRS FR-08, §6.1)."""

from __future__ import annotations

from typing import Any


class IncompatibleComparison(ValueError):
    pass


def _v(run: dict[str, Any], key: str) -> Any:
    return run["metrics"][key]["value"]


def compare_runs(base: dict[str, Any], alt: dict[str, Any]) -> dict[str, Any]:
    """Compare two COMPLETED runs that share dataset hash and confirmed plan hash."""
    problems = []
    for r in (base, alt):
        if r.get("status") != "COMPLETED" or not (r.get("audit") or {}).get("passed"):
            problems.append(f"run {r.get('run_id')} is not a completed, audited result "
                            f"(status {r.get('status')})")
    if base.get("dataset_sha256") != alt.get("dataset_sha256"):
        problems.append("runs use different datasets (dataset hash differs)")
    if base.get("plan_hash") != alt.get("plan_hash"):
        problems.append("runs use different confirmed plans (plan hash differs)")
    if base.get("kind") == alt.get("kind"):
        problems.append("runs have the same kind; compare baseline, greedy or optimized")
    if problems:
        raise IncompatibleComparison("; ".join(problems))

    def pp(key: str) -> float | None:
        a, b = _v(base, key), _v(alt, key)
        return None if a is None or b is None else b - a

    w_base = base["metrics"]["within_threshold_visits"]["value"]
    w_alt = alt["metrics"]["within_threshold_visits"]["value"]
    c_base = base["metrics"]["cost_pkr"]["value"]
    c_alt = alt["metrics"]["cost_pkr"]["value"]
    dw = w_alt - w_base
    return {
        "base_run_id": base["run_id"],
        "alt_run_id": alt["run_id"],
        "base_kind": base["kind"],
        "alt_kind": alt["kind"],
        "dataset_sha256": base["dataset_sha256"],
        "plan_hash": base["plan_hash"],
        "deltas": {
            "coverage_pp": pp("coverage_pct"),
            "served_rate_pp": pp("served_rate_pct"),
            "unmet_rate_pp": pp("unmet_rate_pct"),
            "worst_cluster_pp": pp("worst_cluster_coverage_pct"),
            "equity_gap_pp": pp("equity_gap_pp"),
            "within_threshold_visits": dw,
            "unmet_visits": _v(alt, "unmet") - _v(base, "unmet"),
            "mean_travel_min": pp("mean_travel_min"),
            "cost_pkr": c_alt - c_base,
        },
        # SRS §6.1: null if denominator <= 0
        "additional_cost_per_added_covered_visit": {
            "value": None if dw <= 0 else (c_alt - c_base) / dw,
            "unit": "PKR per added within-threshold visit/week",
            "numerator": c_alt - c_base,
            "denominator": dw,
        },
        "tie_or_worse": dw <= 0,
    }
