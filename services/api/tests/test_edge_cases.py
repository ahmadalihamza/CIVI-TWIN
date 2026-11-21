"""T02-T05, T07: edge cases and tamper detection."""

import copy

import pytest

from civitwin_engine.audit import audit_result, result_hash
from civitwin_engine.dataset.generator import generate_demo_dataset, generate_disconnected_fixture
from civitwin_engine.fixtures import golden_dataset, golden_plan
from civitwin_engine.optimizer.problem import ProblemError, build_problem
from civitwin_engine.planspec import DEFAULTS, PlanSpec
from civitwin_engine.run import execute_run
from civitwin_engine.travel import travel_matrix


def _golden(**kw):
    ds = golden_dataset()
    return build_problem(ds, travel_matrix(ds), golden_plan(**kw))


@pytest.mark.parametrize("budget,units", [(0, 1), (100, 0), (99, 1)])
def test_t02_zero_budget_or_units_opens_nothing(backend, budget, units):
    r = execute_run(_golden(budget_pkr=budget, max_new_units=units), "optimized", backend=backend)
    assert r["status"] == "COMPLETED" and r["audit"]["passed"]
    assert r["selected_candidate_ids"] == []
    assert r["metrics"]["cost_pkr"]["value"] == 0
    assert r["metrics"]["coverage_pct"]["value"] == 60.0


def test_t03_disconnected_cluster_is_unmet(backend):
    ds = generate_disconnected_fixture()
    tm = travel_matrix(ds)
    assert not any(c == "D03" for c, _ in tm.raw_minutes)
    plan = PlanSpec.model_validate({**DEFAULTS, "dataset_version_id": ds.manifest.id,
                                    "budget_pkr": 100_000, "max_new_units": 1})
    p = build_problem(ds, tm, plan)
    r = execute_run(p, "optimized", backend=backend)
    assert r["status"] == "COMPLETED" and r["audit"]["passed"]
    assert all(a["community_id"] != "D03" for a in r["assignments"])
    assert {u["community_id"]: u["visits"] for u in r["unmet_by_community"]}["D03"] == 30
    assert any("cannot reach any site" in w for w in r["warnings"])


def test_t04_capacity_saturation(backend):
    # Demand x3 (300%) far exceeds total capacity 100.
    r = execute_run(_golden(demand_multiplier_pct=300), "optimized", backend=backend)
    assert r["status"] == "COMPLETED" and r["audit"]["passed"]
    load = {}
    for a in r["assignments"]:
        load[a["site_id"]] = load.get(a["site_id"], 0) + a["visits"]
    assert load["E"] <= 60 and load.get("N", 0) <= 40
    assert r["metrics"]["served"]["value"] == 100
    assert r["metrics"]["unmet"]["value"] == 200
    assert r["metrics"]["total_demand"]["value"] == 300


def test_t05_impossible_equity_floor_has_no_fake_kpis(backend):
    r = execute_run(_golden(equity_min_pct=100, budget_pkr=0), "optimized", backend=backend)
    assert r["status"] == "NO_SOLUTION"
    assert "metrics" not in r and "assignments" not in r
    assert r["error"]["hints"]


def test_baseline_infeasible_under_floor_but_optimized_feasible(backend):
    p = _golden(equity_min_pct=100)
    assert execute_run(p, "baseline", backend=backend)["status"] == "NO_SOLUTION"
    r = execute_run(p, "optimized", backend=backend)
    assert r["status"] == "COMPLETED" and r["metrics"]["worst_cluster_coverage_pct"]["value"] == 100


@pytest.mark.parametrize("tamper", ["visits", "foreign", "closed_site", "budget", "metric"])
def test_t07_tampered_output_fails_audit(backend, tamper):
    p = _golden()
    good = execute_run(p, "optimized", backend=backend)
    bad = copy.deepcopy(good)
    if tamper == "visits":
        bad["assignments"][0]["visits"] += 5
    elif tamper == "foreign":
        bad["assignments"][0]["site_id"] = "ZZZ"
    elif tamper == "closed_site":
        bad["selected_candidate_ids"] = []
    elif tamper == "budget":
        bad["plan"]["budget_pkr"] = 0  # plan in the record is not trusted; problem is
        bad["selected_candidate_ids"] = ["N", "N"]
    elif tamper == "metric":
        bad["metrics"]["coverage_pct"]["value"] = 99.0
    # even if the attacker also recomputes the hash, constraint checks must still fail
    bad["result_sha256"] = result_hash(bad)
    audit = audit_result(p, bad)
    assert audit["passed"] is False


def test_tampered_hash_only_fails(backend):
    p = _golden()
    r = execute_run(p, "optimized", backend=backend)
    r2 = copy.deepcopy(r)
    r2["result_sha256"] = "0" * 64
    assert audit_result(p, r2)["passed"] is False


def test_plan_rejects_too_many_units():
    ds = golden_dataset()
    with pytest.raises(ProblemError):
        build_problem(ds, travel_matrix(ds), golden_plan(max_new_units=2))


def test_plan_for_wrong_dataset_rejected():
    ds = generate_demo_dataset()
    with pytest.raises(ProblemError):
        build_problem(ds, travel_matrix(ds), golden_plan())


def test_ineligible_candidate_never_opened(backend):
    ds = generate_demo_dataset()
    plan = PlanSpec.model_validate({**DEFAULTS, "dataset_version_id": ds.manifest.id,
                                    "budget_pkr": 10_000_000, "max_new_units": 7})
    r = execute_run(build_problem(ds, travel_matrix(ds), plan), "optimized", backend=backend,
                    time_limit_s=20)
    assert r["status"] == "COMPLETED"
    assert "N05" not in r["selected_candidate_ids"]


def test_equity_floor_diagnostic_reports_minimum_units(backend):
    ds = generate_demo_dataset()
    tm = travel_matrix(ds)
    plan = PlanSpec.model_validate({**DEFAULTS, "dataset_version_id": ds.manifest.id,
                                    "equity_min_pct": 10})
    r = execute_run(build_problem(ds, tm, plan), "optimized", backend=backend)
    assert r["status"] == "NO_SOLUTION"
    assert any("needs at least" in h and "new units" in h for h in r["error"]["hints"])
    ok = execute_run(build_problem(ds, tm, plan.model_copy(update={"max_new_units": 5,
                                                                   "budget_pkr": 700_000})),
                     "optimized", backend=backend)
    assert ok["status"] == "COMPLETED" and ok["audit"]["passed"]
    assert ok["metrics"]["worst_cluster_coverage_pct"]["value"] >= 10
