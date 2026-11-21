"""Real Bajaur data: integrity of the built dataset and an audited end-to-end plan."""

import json
from pathlib import Path

import pytest

from civitwin_engine.analysis import coordination
from civitwin_engine.dataset.validation import dataset_hash, validate_dataset
from civitwin_engine.greedy import execute_greedy
from civitwin_engine.optimizer.problem import build_problem
from civitwin_engine.planspec import DEFAULTS, PlanSpec
from civitwin_engine.run import execute_run
from civitwin_engine.travel import travel_matrix

REAL = Path(__file__).resolve().parents[3] / "data" / "real"
pytestmark = pytest.mark.skipif(not (REAL / "bajaur_real_walk_v1.json").exists(),
                                reason="real dataset not built (scripts/build_real_dataset.py)")


def _load(name):
    return json.loads((REAL / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def walk():
    ds = validate_dataset(_load("bajaur_real_walk_v1.json"))
    return ds, travel_matrix(ds), _load("bajaur_geo_walk.json")


def _inside(pt, ring):
    x, y = pt
    c = False
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def test_dataset_is_real_and_hash_is_stable(walk):
    ds, _, _ = walk
    assert ds.manifest.is_synthetic is False
    assert dataset_hash(ds) == ds.manifest.sha256
    assert any("Census 2023" in a for a in ds.manifest.assumptions)


def test_population_matches_census(walk):
    ds, _, geo = walk
    census = _load("census_2023_bajaur.json")
    assert sum(c.population for c in ds.communities) == census["district_total"] == 1_287_960
    for t in census["tehsils"]:
        assert sum(c["population"] for c in geo["clusters"] if c["tehsil"] == t["name"]) == t["pop_2023"]


def test_facilities_come_from_registry_and_lie_in_bajaur(walk):
    _, _, geo = walk
    reg = [f for f in geo["facilities"] if f["kind"] in ("existing", "reactivate")]
    assert len(reg) == 44
    assert sum(f["kind"] == "existing" for f in reg) == 37
    district = geo["district"]
    outside = [f["id"] for f in geo["facilities"] if not _inside((f["lon"], f["lat"]), district)]
    assert len(outside) <= 2, outside  # gazetteer coordinates may sit on the border


def test_real_plan_is_audited_and_beats_or_ties_greedy(walk):
    ds, tm, geo = walk
    plan = PlanSpec.model_validate({**DEFAULTS, "dataset_version_id": ds.manifest.id,
                                    "budget_pkr": 600_000, "max_new_units": 6, "threshold_minutes": 60})
    p = build_problem(ds, tm, plan)
    base = execute_run(p, "baseline")
    opt = execute_run(p, "optimized")
    greedy = execute_greedy(p)
    for r in (base, opt, greedy):
        assert r["status"] == "COMPLETED" and r["audit"]["passed"]
        assert "REAL PUBLIC DATA" in r["warnings"][0]
    w = lambda r: r["metrics"]["within_threshold_visits"]["value"]  # noqa: E731
    assert w(opt) >= w(greedy) >= w(base)
    co = coordination(opt, geo, base)
    assert len(co["tehsils"]) == 7
    assert sorted(r["joint_priority_rank"] for r in co["tehsils"]) == list(range(1, 8))
    assert {h["site_id"] for h in co["hubs"]} == set(opt["selected_candidate_ids"])
