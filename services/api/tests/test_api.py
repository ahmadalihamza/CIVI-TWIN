"""Integration tests: API + SQLite + job executor (T08, T10, T12, T13)."""

import time

import pytest
from fastapi.testclient import TestClient

from civitwin_api.main import create_app
from civitwin_engine.planspec import DEFAULTS

PLAN = {**DEFAULTS, "dataset_version_id": "demo-bajaur-v1"}


@pytest.fixture()
def client(tmp_path):
    app = create_app(str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


def _wait(client, url, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = client.get(url).json()
        if r["status"] not in ("QUEUED", "RUNNING", "AUDITING"):
            return r
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def _confirmed(client, plan=PLAN):
    scn = client.post("/api/v1/scenarios", json={"plan": plan}).json()
    client.post(f"/api/v1/scenarios/{scn['scenario_id']}/confirm",
                json={"plan_hash": scn["plan_hash"]})
    return scn


def _run(client, scn, kind, key=None):
    headers = {"Idempotency-Key": key} if key else {}
    r = client.post(f"/api/v1/scenarios/{scn['scenario_id']}/runs",
                    json={"kind": kind, "plan_hash": scn["plan_hash"]}, headers=headers)
    assert r.status_code == 202, r.text
    return _wait(client, f"/api/v1/runs/{r.json()['run_id']}")


def test_health_ready_system(client):
    assert client.get("/api/v1/health").json() == {"status": "ok"}
    ready = client.get("/api/v1/ready").json()
    assert "demo-bajaur-v1" in ready["datasets"] and ready["solver_backends"]
    sysinfo = client.get("/api/v1/system").json()
    assert sysinfo["ai_model_enabled"] is False and "SYNTHETIC" in sysinfo["warning"]


def test_dataset_endpoint(client):
    ds = client.get("/api/v1/datasets/demo-bajaur-v1").json()
    assert ds["manifest"]["is_synthetic"] is True
    assert len(ds["communities"]) == 24 and len(ds["sites"]) == 13
    assert ds["travel"]["minutes"]
    assert client.get("/api/v1/datasets/nope").status_code == 404


def test_full_flow_confirm_run_compare_export(client):
    scn = client.post("/api/v1/scenarios", json={"plan": PLAN}).json()
    # running before confirmation is refused
    r = client.post(f"/api/v1/scenarios/{scn['scenario_id']}/runs",
                    json={"kind": "optimized", "plan_hash": scn["plan_hash"]})
    assert r.status_code == 409
    # wrong hash on confirm -> 409
    bad = client.post(f"/api/v1/scenarios/{scn['scenario_id']}/confirm",
                      json={"plan_hash": "x" * 64})
    assert bad.status_code == 409 and bad.json()["code"] == "plan_hash_mismatch"
    client.post(f"/api/v1/scenarios/{scn['scenario_id']}/confirm",
                json={"plan_hash": scn["plan_hash"]})
    base = _run(client, scn, "baseline")
    opt = _run(client, scn, "optimized")
    greedy = _run(client, scn, "greedy")
    for run in (base, opt, greedy):
        assert run["status"] == "COMPLETED" and run["audit"]["passed"]
    cmp = client.post("/api/v1/comparisons",
                      json={"base_run_id": base["run_id"], "alt_run_id": opt["run_id"]}).json()
    assert cmp["deltas"]["coverage_pp"] > 0 and cmp["explanation"]
    ur = client.post("/api/v1/comparisons", json={"base_run_id": base["run_id"],
                                                  "alt_run_id": opt["run_id"], "lang": "ur"})
    assert ur.status_code == 200
    ex = client.get(f"/api/v1/runs/{opt['run_id']}/explanation?lang=ur").json()
    assert ex["explanation"]["review_note"] and ex["ai_model_used"] is False
    j = client.get(f"/api/v1/runs/{opt['run_id']}/export?format=json")
    assert j.status_code == 200 and opt["result_sha256"] in j.text
    c = client.get(f"/api/v1/runs/{opt['run_id']}/export?format=csv")
    assert "dataset_sha256" in c.text
    h = client.get(f"/api/v1/runs/{opt['run_id']}/export?format=html&compare_to={base['run_id']}")
    assert "SYNTHETIC DEMONSTRATION" in h.text


def test_t08_mismatched_comparison_rejected(client):
    a = _confirmed(client)
    b = _confirmed(client, {**PLAN, "budget_pkr": 150_000})
    ra, rb = _run(client, a, "baseline"), _run(client, b, "optimized")
    r = client.post("/api/v1/comparisons", json={"base_run_id": ra["run_id"],
                                                 "alt_run_id": rb["run_id"]})
    assert r.status_code == 409 and "plan hash" in r.json()["message"]


def test_invalid_plan_errors(client):
    r = client.post("/api/v1/scenarios", json={"plan": {**PLAN, "budget_pkr": -1}})
    assert r.status_code == 422 and r.json()["field_errors"][0]["field"] == "budget_pkr"
    r = client.post("/api/v1/scenarios", json={"plan": {**PLAN, "max_new_units": 8}})
    assert r.status_code == 422 and "eligible" in r.json()["message"]
    r = client.post("/api/v1/scenarios", json={"plan": {**PLAN, "extra": 1}})
    assert r.status_code == 422
    r = client.post("/api/v1/scenarios", content=b"{not json",
                    headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["request_id"]


def test_infeasible_equity_floor_returns_no_solution(client):
    scn = _confirmed(client, {**PLAN, "equity_min_pct": 50})
    run = _run(client, scn, "baseline")
    assert run["status"] == "NO_SOLUTION"
    assert "metrics" not in run and run["error"]["hints"]
    assert client.get(f"/api/v1/runs/{run['run_id']}/explanation").status_code == 409


def test_idempotency_key(client):
    scn = _confirmed(client)
    r1 = client.post(f"/api/v1/scenarios/{scn['scenario_id']}/runs",
                     json={"kind": "baseline", "plan_hash": scn["plan_hash"]},
                     headers={"Idempotency-Key": "k1"}).json()
    r2 = client.post(f"/api/v1/scenarios/{scn['scenario_id']}/runs",
                     json={"kind": "baseline", "plan_hash": scn["plan_hash"]},
                     headers={"Idempotency-Key": "k1"}).json()
    assert r1["run_id"] == r2["run_id"]
    r3 = client.post(f"/api/v1/scenarios/{scn['scenario_id']}/runs",
                     json={"kind": "optimized", "plan_hash": scn["plan_hash"]},
                     headers={"Idempotency-Key": "k1"})
    assert r3.status_code == 409
    _wait(client, f"/api/v1/runs/{r1['run_id']}")


def test_t13_cancel_terminal_and_restart(tmp_path):
    db = str(tmp_path / "restart.db")
    app = create_app(db)
    with TestClient(app) as c:
        scn = _confirmed(c)
        done = _run(c, scn, "baseline")
        assert c.post(f"/api/v1/runs/{done['run_id']}/cancel").status_code == 409
        # simulate a crash mid-run: a RUNNING row left behind
        store = app.state.civitwin.store
        store.create_run("run-crashed", scn["scenario_id"], "optimized", None, "h")
        store.set_run_status("run-crashed", "RUNNING", "solving")
    app2 = create_app(db)
    with TestClient(app2) as c2:
        crashed = c2.get("/api/v1/runs/run-crashed").json()
        assert crashed["status"] == "INTERRUPTED" and "metrics" not in crashed
        assert c2.get(f"/api/v1/runs/{done['run_id']}").json()["status"] == "COMPLETED"


def test_stress_endpoint(client):
    scn = _confirmed(client)
    base, opt = _run(client, scn, "baseline"), _run(client, scn, "optimized")
    r = client.post("/api/v1/stress-runs", json={"base_run_id": base["run_id"],
                                                 "alt_run_id": opt["run_id"], "seed": 5,
                                                 "count": 4})
    assert r.status_code == 202
    s = _wait(client, f"/api/v1/stress-runs/{r.json()['stress_run_id']}")
    assert s["status"] == "COMPLETED" and len(s["results"]["cases"]) == 4


def test_import_rejects_bad_dataset(client):
    ds = client.get("/api/v1/datasets/demo-bajaur-v1").json()
    ds.pop("travel")
    ds.pop("validation_warnings")
    # same id -> conflict
    assert client.post("/api/v1/datasets/import", json=ds).status_code == 409
    ds["manifest"]["id"] = "demo-copy"
    ds["manifest"]["sha256"] = None
    ds["communities"][0]["node_id"] = "missing"
    r = client.post("/api/v1/datasets/import", json=ds)
    assert r.status_code == 422 and r.json()["field_errors"][0]["code"] == "unknown_node"
    assert "demo-copy" not in [d["id"] for d in client.get("/api/v1/datasets").json()]


def test_parse_endpoint(client):
    r = client.post("/api/v1/plans/parse", json={"text": "بجٹ ۳ لاکھ، دو نئے مراکز، ۴۵ منٹ"})
    out = r.json()
    assert out["draft"]["budget_pkr"] == 300_000 and out["language"] == "ur"
    assert out["ai_model_used"] is False


def test_ui_assets_are_revalidated_not_cached(client):
    r = client.get("/")
    assert r.status_code == 200 and "CIVITWIN" in r.text
    assert r.headers["cache-control"] == "no-cache"
    assert client.get("/app.js").headers["cache-control"] == "no-cache"
    assert "cache-control" not in client.get("/api/v1/health").headers


def test_tradeoff_and_site_impact_endpoints(client):
    scn = _confirmed(client)
    opt = _run(client, scn, "optimized")
    t = client.post(f"/api/v1/runs/{opt['run_id']}/tradeoff")
    assert t.status_code == 200, t.text
    curves = t.json()["curves"]
    assert [c["max_new_units"] for c in curves] == [2, 7]
    assert all(p["status"] == "COMPLETED" for c in curves for p in c["points"])
    again = client.post(f"/api/v1/runs/{opt['run_id']}/tradeoff")
    assert again.json() == t.json()  # cached, deterministic
    imp = client.get(f"/api/v1/runs/{opt['run_id']}/site-impact")
    assert imp.status_code == 200
    ids = [s["site_id"] for s in imp.json()["sites"]]
    assert ids == opt["selected_candidate_ids"]
    infeasible = _run(client, _confirmed(client, {**PLAN, "equity_min_pct": 50}), "optimized")
    assert client.get(f"/api/v1/runs/{infeasible['run_id']}/site-impact").status_code == 409


def test_real_datasets_and_geo(client):
    ids = {d["id"]: d for d in client.get("/api/v1/datasets").json()}
    if "bajaur-real-walk-v1" not in ids:
        pytest.skip("real dataset not built")
    w = ids["bajaur-real-walk-v1"]
    assert w["is_synthetic"] is False and w["has_map"] and w["travel_mode"] == "foot"
    geo = client.get("/api/v1/datasets/bajaur-real-walk-v1/geo").json()
    assert len(geo["tehsils"]) == 7 and geo["pakistan"] and geo["attribution"]
    assert client.get("/api/v1/datasets/demo-bajaur-v1/geo").status_code == 404
    plan = {**DEFAULTS, "dataset_version_id": "bajaur-real-walk-v1", **w["default_plan"]}
    scn = _confirmed(client, plan)
    base, opt = _run(client, scn, "baseline"), _run(client, scn, "optimized")
    assert opt["status"] == "COMPLETED" and opt["audit"]["passed"]
    co = client.get(f"/api/v1/runs/{opt['run_id']}/coordination?base_run_id={base['run_id']}")
    assert co.status_code == 200 and len(co.json()["tehsils"]) == 7
