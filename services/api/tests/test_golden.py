"""T01: golden fixture (SRS §11.1) with a real solver, no mocks."""

from civitwin_engine.fixtures import golden_dataset, golden_plan
from civitwin_engine.optimizer.problem import build_problem
from civitwin_engine.run import execute_run
from civitwin_engine.travel import travel_matrix


def _problem(**kw):
    ds = golden_dataset()
    return build_problem(ds, travel_matrix(ds), golden_plan(**kw))


def test_travel_matrix_matches_fixture():
    ds = golden_dataset()
    assert travel_matrix(ds).minutes() == {("A", "E"): 10, ("A", "N"): 40,
                                           ("B", "E"): 50, ("B", "N"): 10}


def test_golden_baseline(backend):
    r = execute_run(_problem(), "baseline", backend=backend)
    assert r["status"] == "COMPLETED" and r["audit"]["passed"]
    assert r["solver_status"] == "OPTIMAL"
    assert r["selected_candidate_ids"] == []
    assert r["assignments"] == [{"community_id": "A", "site_id": "E", "visits": 60,
                                 "minutes": 10}]
    assert {u["community_id"]: u["visits"] for u in r["unmet_by_community"]} == {"A": 0, "B": 40}
    m = r["metrics"]
    assert m["coverage_pct"]["value"] == 60.0
    assert m["served_rate_pct"]["value"] == 60.0
    assert m["worst_cluster_coverage_pct"]["value"] == 0.0
    assert m["worst_cluster_coverage_pct"]["community_id"] == "B"
    assert m["mean_travel_min"]["value"] == 10.0
    assert m["cost_pkr"]["value"] == 0


def test_golden_optimized(backend):
    r = execute_run(_problem(), "optimized", backend=backend)
    assert r["status"] == "COMPLETED" and r["audit"]["passed"]
    assert r["solver_status"] == "OPTIMAL" and r["optimality"] == "proven"
    assert r["selected_candidate_ids"] == ["N"]
    assert r["assignments"] == [
        {"community_id": "A", "site_id": "E", "visits": 60, "minutes": 10},
        {"community_id": "B", "site_id": "N", "visits": 40, "minutes": 10},
    ]
    m = r["metrics"]
    assert m["coverage_pct"]["value"] == 100.0
    assert m["served_rate_pct"]["value"] == 100.0
    assert m["worst_cluster_coverage_pct"]["value"] == 100.0
    assert m["mean_travel_min"]["value"] == 10.0
    assert m["cost_pkr"]["value"] == 100
    assert [c["id"] for c in r["audit"]["checks"]] == [f"A{i:02d}" for i in range(1, 13)]


def test_golden_is_reproducible(backend):
    a = execute_run(_problem(), "optimized", backend=backend)
    b = execute_run(_problem(), "optimized", backend=backend)
    assert a["result_sha256"] == b["result_sha256"]
