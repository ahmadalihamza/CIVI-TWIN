"""Smoke test against a running server: health -> scenario -> confirm -> run -> audit."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

PLAN = {"dataset_version_id": "demo-bajaur-v1", "budget_pkr": 300000, "max_new_units": 2,
        "threshold_minutes": 45, "demand_multiplier_pct": 100, "equity_min_pct": 0,
        "policy": "coverage_first", "seed": 2026, "min_coverage_pct": None}


def call(base: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    base = ap.parse_args().url.rstrip("/") + "/api/v1"
    assert call(base, "/health")["status"] == "ok"
    print("ready:", call(base, "/ready"))
    scn = call(base, "/scenarios", {"plan": PLAN})
    call(base, f"/scenarios/{scn['scenario_id']}/confirm", {"plan_hash": scn["plan_hash"]})
    run = call(base, f"/scenarios/{scn['scenario_id']}/runs",
               {"kind": "optimized", "plan_hash": scn["plan_hash"]})
    for _ in range(60):
        run = call(base, f"/runs/{run['run_id']}")
        if run["status"] not in ("QUEUED", "RUNNING", "AUDITING"):
            break
        time.sleep(1)
    ok = run["status"] == "COMPLETED" and run["audit"]["passed"]
    cov = run.get("metrics", {}).get("coverage_pct", {}).get("value")
    print(f"run {run['run_id']}: {run['status']}, audit passed={run.get('audit', {}).get('passed')}"
          f", coverage={cov}")
    print("SMOKE OK" if ok else "SMOKE FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
