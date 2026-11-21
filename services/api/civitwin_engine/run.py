"""Run pipeline: solve -> metrics -> hash -> independent audit -> publish or fail closed."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .audit import audit_result, result_hash
from .metrics import compute_metrics
from .optimizer.problem import Problem
from .optimizer.solve import solve

MODEL_VERSION = "1.0"
SYNTHETIC_WARNING = ("SYNTHETIC DEMONSTRATION: all inputs are fictional; results do not "
                     "describe real district services.")
REAL_DATA_NOTE = ("REAL PUBLIC DATA WITH ASSUMPTIONS: facility locations, settlements, census population and "
                  "road travel times are real; population split, utilisation, capacity and costs are "
                  "planning assumptions. Advisory output, not an approved allocation.")
FIXED_KINDS = ("greedy", "stress_case", "what_if")


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _input_warnings(p: Problem) -> list[str]:
    w = [SYNTHETIC_WARNING if p.is_synthetic else REAL_DATA_NOTE]
    no_site = [c for c in p.community_ids if not any((c, s) in p.travel for s in p.site_ids)]
    if no_site:
        w.append(f"{len(no_site)} cluster(s) cannot reach any site: {', '.join(no_site)}. "
                 "Their demand can only be unmet.")
    return w


def execute_run(
    p: Problem,
    kind: str,
    *,
    open_candidates: list[str] | None = None,
    time_limit_s: float = 10.0,
    backend: str | None = None,
    cancel: threading.Event | None = None,
    run_id: str | None = None,
    scenario_id: str | None = None,
    on_stage: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    if on_stage:
        on_stage("solving")
    raw = solve(p, kind, open_candidates=open_candidates, time_limit_s=time_limit_s,
                cancel=cancel, backend=backend)
    record: dict[str, Any] = {
        "run_id": run_id or f"run-{uuid.uuid4().hex[:10]}",
        "scenario_id": scenario_id,
        "kind": kind,
        "status": None,
        "solver_status": raw["solver_status"],
        "dataset_sha256": p.dataset_sha256,
        "plan_hash": p.plan_hash,
        "plan": p.plan.model_dump(mode="json"),
        "model_version": MODEL_VERSION,
        "created_at": now_iso(),
        "runtime_ms": raw["runtime_ms"],
        "engine": raw.get("engine"),
        "objective_stages": raw.get("objective_stages", []),
        "warnings": _input_warnings(p),
        "stress_multipliers": {"demand_pct": p.stress_demand_pct,
                               "travel_pct": p.stress_travel_pct},
    }
    if raw["status"] != "SOLVED":
        # Errors and non-solution states carry no result fields (SRS §8.1).
        record["status"] = raw["status"]
        record["error"] = {"reason": raw.get("reason"), "hints": raw.get("hints", [])}
        return record

    metrics = compute_metrics(p, raw["assignments"], raw["unmet_by_community"],
                              raw["selected_candidate_ids"])
    record.update({
        "optimality": raw["optimality"],
        "stopped_reason": raw.get("stopped_reason"),
        "selected_candidate_ids": raw["selected_candidate_ids"],
        "assignments": raw["assignments"],
        "unmet_by_community": raw["unmet_by_community"],
        "metrics": metrics,
    })
    if raw["optimality"] != "proven":
        record["warnings"].append(
            "Solver did not prove optimality for every objective stage "
            f"({raw.get('stopped_reason')}). Result is feasible and audited, not proven optimal.")
    record["result_sha256"] = result_hash(record)

    if on_stage:
        on_stage("auditing")
    fixed = [] if kind == "baseline" else (open_candidates if kind in FIXED_KINDS else None)
    audit = audit_result(p, record, fixed_selection=fixed)
    record["audit"] = audit
    if audit["passed"]:
        record["status"] = "COMPLETED"
        return record

    # Fail closed: keep the audit for diagnosis, publish nothing else.
    failed = {k: record[k] for k in ("run_id", "scenario_id", "kind", "solver_status",
                                     "dataset_sha256", "plan_hash", "plan", "model_version",
                                     "created_at", "runtime_ms", "engine", "warnings")}
    failed["status"] = "FAILED"
    failed["error"] = {"reason": "Independent audit failed; result not published.",
                       "hints": [c["name"] for c in audit["checks"] if not c["passed"]]}
    failed["audit"] = audit
    return failed
