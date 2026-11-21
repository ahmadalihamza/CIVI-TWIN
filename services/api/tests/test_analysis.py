"""Trade-off curve and site impact (decision-support analyses)."""

from civitwin_engine.analysis import site_impact, tradeoff_curve
from civitwin_engine.dataset.generator import generate_demo_dataset
from civitwin_engine.fixtures import golden_dataset, golden_plan
from civitwin_engine.optimizer.problem import build_problem
from civitwin_engine.planspec import DEFAULTS, PlanSpec
from civitwin_engine.run import execute_run
from civitwin_engine.travel import travel_matrix


def test_golden_tradeoff_points(backend):
    ds = golden_dataset()
    tm = travel_matrix(ds)
    out = tradeoff_curve(ds, tm, golden_plan(), budgets=(0, 50, 100), backend=backend)
    assert len(out["curves"]) == 1  # plan limit (1) equals eligible candidates (1)
    pts = {p["budget_pkr"]: p for p in out["curves"][0]["points"]}
    assert pts[0]["coverage_pct"] == 60.0 and pts[0]["selected_candidate_ids"] == []
    assert pts[50]["coverage_pct"] == 60.0
    assert pts[100]["coverage_pct"] == 100.0 and pts[100]["selected_candidate_ids"] == ["N"]
    assert all(p["audit_passed"] for p in pts.values())
    assert pts[100]["gain_pp_per_lakh"] > 0


def test_tradeoff_is_monotone_on_demo(backend):
    ds = generate_demo_dataset()
    tm = travel_matrix(ds)
    plan = PlanSpec.model_validate({**DEFAULTS, "dataset_version_id": ds.manifest.id})
    out = tradeoff_curve(ds, tm, plan, budgets=(0, 300_000, 600_000), backend=backend)
    assert [c["max_new_units"] for c in out["curves"]] == [2, 7]
    for curve in out["curves"]:
        cov = [p["coverage_pct"] for p in curve["points"]]
        assert cov == sorted(cov)  # more budget never lowers optimal coverage
        for p in curve["points"]:
            assert p["cost_pkr"] <= p["budget_pkr"] and p["audit_passed"]


def test_golden_site_impact(backend):
    ds = golden_dataset()
    tm = travel_matrix(ds)
    plan = golden_plan()
    run = execute_run(build_problem(ds, tm, plan), "optimized", backend=backend)
    out = site_impact(ds, tm, plan, run, backend=backend)
    (n,) = out["sites"]
    assert n["site_id"] == "N" and n["within_threshold_visits"] == 40
    assert n["within_lost_if_removed"] == 40
    assert n["coverage_lost_pp_if_removed"] == 40.0
    assert n["cost_per_within_visit_kept"] == 100 / 40
    assert n["clusters_served"] == [{"community_id": "B", "visits": 40, "minutes": 10}]
