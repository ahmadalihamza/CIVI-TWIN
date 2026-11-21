"""Stress reproducibility (T09), greedy benchmark and comparison rules (T08)."""

import pytest

from civitwin_engine.compare import IncompatibleComparison, compare_runs
from civitwin_engine.dataset.generator import generate_demo_dataset
from civitwin_engine.fixtures import golden_dataset, golden_plan
from civitwin_engine.greedy import execute_greedy
from civitwin_engine.optimizer.problem import build_problem
from civitwin_engine.planspec import DEFAULTS, PlanSpec
from civitwin_engine.run import execute_run
from civitwin_engine.stress import run_stress, stress_cases
from civitwin_engine.travel import travel_matrix


@pytest.fixture(scope="module")
def demo():
    ds = generate_demo_dataset()
    tm = travel_matrix(ds)
    plan = PlanSpec.model_validate({**DEFAULTS, "dataset_version_id": ds.manifest.id})
    return ds, tm, plan, build_problem(ds, tm, plan)


def test_stress_cases_reproducible():
    assert stress_cases(2026, 20) == stress_cases(2026, 20)
    assert stress_cases(2026, 20) != stress_cases(2027, 20)
    for c in stress_cases(2026, 20):
        assert 80 <= c["demand_pct"] <= 130 and 90 <= c["travel_pct"] <= 140
    with pytest.raises(ValueError):
        stress_cases(1, 21)


def test_t09_stress_fixed_selection_and_reproducible(demo, backend):
    ds, tm, plan, p = demo
    base = execute_run(p, "baseline", backend=backend)
    alt = execute_run(p, "optimized", backend=backend)
    s1 = run_stress(ds, tm, plan, base, alt, seed=11, count=5, backend=backend)
    s2 = run_stress(ds, tm, plan, base, alt, seed=11, count=5, backend=backend)
    strip = lambda s: [{k: v for k, v in c.items()} for c in s["cases"]]  # noqa: E731
    assert strip(s1) == strip(s2)
    assert s1["alt_selection"] == alt["selected_candidate_ids"]
    for c in s1["cases"]:
        assert c["base"]["status"] == "COMPLETED" and c["alt"]["status"] == "COMPLETED"
    assert s1["summary"]["alt"]["successful_cases"] == 5
    assert s1["summary"]["alt"]["failure_rate_pct"] == 0.0


def test_stress_counts_failures_with_equity_floor(backend):
    ds = golden_dataset()
    tm = travel_matrix(ds)
    plan = golden_plan(equity_min_pct=90)
    p = build_problem(ds, tm, plan)
    alt = execute_run(p, "optimized", backend=backend)
    greedy = execute_greedy(p, backend=backend)
    assert alt["status"] == "COMPLETED" and greedy["status"] == "COMPLETED"
    s = run_stress(ds, tm, plan, greedy, alt, seed=3, count=8, backend=backend)
    # demand up to 130% exceeds total capacity, so some cases must fail the 90% floor
    assert s["summary"]["alt"]["failed_cases"] > 0
    assert s["summary"]["alt"]["failed_cases"] + s["summary"]["alt"]["successful_cases"] == 8


def test_greedy_respects_constraints_and_is_audited(demo, backend):
    ds, tm, plan, p = demo
    g = execute_greedy(p, backend=backend)
    assert g["status"] == "COMPLETED" and g["audit"]["passed"]
    assert len(g["selected_candidate_ids"]) <= plan.max_new_units
    assert g["metrics"]["cost_pkr"]["value"] <= plan.budget_pkr
    opt = execute_run(p, "optimized", backend=backend)
    # CP optimum can never be worse than greedy on the first lexicographic objective
    assert opt["metrics"]["within_threshold_visits"]["value"] >= \
        g["metrics"]["within_threshold_visits"]["value"]


def test_t08_comparison_rules(demo, backend):
    ds, tm, plan, p = demo
    base = execute_run(p, "baseline", backend=backend)
    alt = execute_run(p, "optimized", backend=backend)
    cmp = compare_runs(base, alt)
    assert cmp["deltas"]["coverage_pp"] > 0
    acpv = cmp["additional_cost_per_added_covered_visit"]
    assert acpv["value"] == pytest.approx(acpv["numerator"] / acpv["denominator"])
    with pytest.raises(IncompatibleComparison):
        compare_runs(base, base)
    other_plan = plan.model_copy(update={"budget_pkr": 150_000})
    other = execute_run(build_problem(ds, tm, other_plan), "optimized", backend=backend)
    with pytest.raises(IncompatibleComparison, match="plan hash"):
        compare_runs(base, other)
