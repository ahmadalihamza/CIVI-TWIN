"""Build the public read-only demo using the local API and an in-memory database."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from shutil import copyfile

from civitwin_api.main import WEB_DIR, create_app
from fastapi.testclient import TestClient
from smoke import PLAN

API = "/api/v1"
ASSETS = ("styles.css", "viz3d.js", "geomap.js", "app.js", "desk.js")
KINDS = ("baseline", "greedy", "optimized")
LANGUAGES = ("en", "ur")


def wait_for_run(client: TestClient, path: str) -> dict:
    deadline = time.monotonic() + 160
    while time.monotonic() < deadline:
        run = client.get(f"{API}{path}").raise_for_status().json()
        if run["status"] not in {"QUEUED", "RUNNING", "AUDITING"}:
            if run["status"] != "COMPLETED":
                raise RuntimeError(f"Cannot publish {path}: {run['status']}")
            return run
        time.sleep(0.1)
    raise TimeoutError(f"No completed result for {path}")


def build_snapshot(client: TestClient) -> tuple[dict, dict[str, bytes]]:
    def get(path: str, **params):
        return client.get(f"{API}{path}", params=params).raise_for_status()

    def post(path: str, **body) -> dict:
        return client.post(f"{API}{path}", json=body or None).raise_for_status().json()

    (info,) = get("/datasets").json()
    dataset = get(f"/datasets/{info['id']}").json()
    if not info["is_synthetic"] or not dataset["manifest"]["is_synthetic"] or info["has_map"]:
        raise RuntimeError("Public Pages builds require the schematic synthetic dataset")

    scenario = post("/scenarios", plan=PLAN)
    path = f"/scenarios/{scenario['scenario_id']}"
    plan_hash = scenario["plan_hash"]
    post(f"{path}/confirm", plan_hash=plan_hash)
    runs = {}
    for kind in KINDS:
        job = post(f"{path}/runs", kind=kind, plan_hash=plan_hash)
        result = wait_for_run(client, f"/runs/{job['run_id']}")
        if (not result["audit"]["passed"] or result["dataset_sha256"] != info["sha256"]
                or result["plan_hash"] != plan_hash):
            raise RuntimeError(f"Cannot publish an unaudited or mismatched {kind} run")
        runs[kind] = result

    baseline_id = runs["baseline"]["run_id"]
    optimized_id = runs["optimized"]["run_id"]
    pair = {"base_run_id": baseline_id, "alt_run_id": optimized_id}
    stress_job = post("/stress-runs", **pair, seed=PLAN["seed"], count=20)
    stress = wait_for_run(client, f"/stress-runs/{stress_job['stress_run_id']}")
    optimized = f"/runs/{optimized_id}"
    snapshot = {
        "info": info,
        "dataset": dataset,
        "runs": runs,
        "comparison": {lang: post("/comparisons", **pair, lang=lang) for lang in LANGUAGES},
        "expl": {lang: get(f"{optimized}/explanation", lang=lang).json()["explanation"]
                 for lang in LANGUAGES},
        "impact": get(f"{optimized}/site-impact").json(),
        "tradeoff": post(f"{optimized}/tradeoff"),
        "stress": stress,
    }
    exports = {}
    for kind, run in runs.items():
        for fmt in ("json", "csv", "html"):
            params = {"format": fmt}
            if kind != "baseline" and fmt == "html":
                params["compare_to"] = baseline_id
            exports[f"{kind}.{fmt}"] = get(f"/runs/{run['run_id']}/export", **params).content
    return snapshot, exports


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    output = parser.parse_args().output
    if output.exists() and any(output.iterdir()):
        parser.error("output directory must be empty")

    app = create_app(":memory:", load_real=False)
    try:
        with TestClient(app) as client:
            snapshot, exports = build_snapshot(client)
    finally:
        app.state.civitwin.executor.shutdown()
        app.state.civitwin.store.db.close()

    output.mkdir(parents=True, exist_ok=True)
    (output / "exports").mkdir()
    for filename in ASSETS:
        copyfile(WEB_DIR / filename, output / filename)
    index = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    (output / "index.html").write_text(
        index.replace('<html lang="en"', '<html data-public-demo lang="en"', 1), encoding="utf-8"
    )
    (output / "snapshot.json").write_text(json.dumps(snapshot, allow_nan=False), encoding="utf-8")
    for filename, content in exports.items():
        (output / "exports" / filename).write_bytes(content)
    optimized = snapshot["runs"]["optimized"]
    print(f"Built {output}: {optimized['solver_status']}, audit passed, "
          f"coverage {optimized['metrics']['coverage_pct']['value']:.1f}%")


if __name__ == "__main__":
    main()
