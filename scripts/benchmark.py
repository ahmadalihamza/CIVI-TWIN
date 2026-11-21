"""Benchmark (SRS §6.3, T15): baseline vs greedy vs solver on a parameter grid, plus timings.

Writes docs/benchmark/benchmark-<backend>.json and .md. Records the machine and versions;
reports misses and ties honestly.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

from civitwin_engine.dataset.generator import generate_demo_dataset
from civitwin_engine.greedy import execute_greedy
from civitwin_engine.optimizer.linmodel import available_backends, backend_version
from civitwin_engine.optimizer.problem import build_problem
from civitwin_engine.planspec import DEFAULTS, PlanSpec
from civitwin_engine.run import execute_run
from civitwin_engine.stress import run_stress
from civitwin_engine.travel import travel_matrix

ROOT = Path(__file__).resolve().parents[1]


def cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def ram_gb() -> float | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal"):
                return round(int(line.split()[1]) / 1024 / 1024, 1)
    except OSError:
        pass
    return None


def summary(run: dict) -> dict:
    out = {"status": run["status"], "solver_status": run.get("solver_status"),
           "runtime_ms": run.get("runtime_ms"),
           "audit_passed": (run.get("audit") or {}).get("passed")}
    if run["status"] == "COMPLETED":
        m = run["metrics"]
        out.update({"coverage_pct": round(m["coverage_pct"]["value"], 2),
                    "served_pct": round(m["served_rate_pct"]["value"], 2),
                    "worst_cluster_pct": round(m["worst_cluster_coverage_pct"]["value"], 2),
                    "cost_pkr": m["cost_pkr"]["value"],
                    "selected": run["selected_candidate_ids"]})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default=None, choices=available_backends())
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()
    backend = args.backend or available_backends()[0]

    ds = generate_demo_dataset()
    tm = travel_matrix(ds)
    plan = PlanSpec.model_validate({**DEFAULTS, "dataset_version_id": ds.manifest.id})
    p = build_problem(ds, tm, plan)

    timings: dict[str, list[int]] = {"baseline": [], "optimized": [], "greedy": []}
    for _ in range(args.repeats):
        for kind in ("baseline", "optimized"):
            t0 = time.perf_counter()
            r = execute_run(p, kind, backend=backend)
            timings[kind].append(int((time.perf_counter() - t0) * 1000))
            assert r["status"] == "COMPLETED", r["status"]
        t0 = time.perf_counter()
        execute_greedy(p, backend=backend)
        timings["greedy"].append(int((time.perf_counter() - t0) * 1000))
    base = execute_run(p, "baseline", backend=backend)
    opt = execute_run(p, "optimized", backend=backend)
    t0 = time.perf_counter()
    stress = run_stress(ds, tm, plan, base, opt, seed=2026, count=20, backend=backend)
    stress_ms = int((time.perf_counter() - t0) * 1000)

    grid = []
    for budget in (0, 150_000, 300_000, 450_000):
        for units in (0, 1, 2):
            for equity in (0, 10):
                pl = PlanSpec.model_validate({**DEFAULTS, "dataset_version_id": ds.manifest.id,
                                              "budget_pkr": budget, "max_new_units": units,
                                              "equity_min_pct": equity})
                pp = build_problem(ds, tm, pl)
                row = {"budget_pkr": budget, "max_new_units": units, "equity_min_pct": equity,
                       "baseline": summary(execute_run(pp, "baseline", backend=backend)),
                       "greedy": summary(execute_greedy(pp, backend=backend)),
                       "optimized": summary(execute_run(pp, "optimized", backend=backend))}
                g, o = row["greedy"], row["optimized"]
                if g["status"] == o["status"] == "COMPLETED":
                    row["optimized_minus_greedy_pp"] = round(o["coverage_pct"] - g["coverage_pct"], 2)
                grid.append(row)

    completed = [r[k] for r in grid for k in ("baseline", "greedy", "optimized")
                 if r[k]["status"] == "COMPLETED"]
    report = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "machine": {"cpu": cpu_model(), "logical_cpus": os.cpu_count(), "ram_gb": ram_gb(),
                    "os": f"{platform.system()} {platform.release()}",
                    "python": platform.python_version()},
        "solver": backend_version(backend),
        "dataset": {"id": ds.manifest.id, "sha256": ds.manifest.sha256,
                    "communities": len(ds.communities), "sites": len(ds.sites),
                    "edges": len(ds.edges)},
        "default_plan": plan.model_dump(mode="json"),
        "timings_ms": {k: {"runs": v, "median": statistics.median(v), "max": max(v)}
                       for k, v in timings.items()},
        "targets": {"default_solve_ms": 10_000, "stress_suite_ms": 60_000},
        "default_solve_within_target": max(timings["optimized"]) <= 10_000,
        "stress_suite_ms": stress_ms,
        "stress_within_target": stress_ms <= 60_000,
        "stress_failures": {"base": stress["summary"]["base"]["failed_cases"],
                            "alt": stress["summary"]["alt"]["failed_cases"]},
        "grid": grid,
        "audit_pass_rate_completed": (sum(1 for r in completed if r["audit_passed"])
                                      / len(completed)) if completed else None,
        "optimized_never_below_greedy": all(r.get("optimized_minus_greedy_pp", 0) >= -1e-9
                                            for r in grid),
    }
    out = ROOT / "docs" / "benchmark"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"benchmark-{backend}.json").write_text(json.dumps(report, indent=2) + "\n")

    lines = [f"# Benchmark ({report['solver']})", "",
             f"Generated {report['generated_at']} on {report['machine']['cpu']}, "
             f"{report['machine']['logical_cpus']} logical CPUs, {report['machine']['ram_gb']} GB "
             f"RAM, {report['machine']['os']}, Python {report['machine']['python']}.",
             f"Dataset `{ds.manifest.id}` sha256 `{ds.manifest.sha256[:16]}…` (synthetic).", "",
             "| Measure | Median ms | Max ms | Target |", "|---|---|---|---|"]
    for k, v in report["timings_ms"].items():
        tgt = "≤ 10,000" if k == "optimized" else "—"
        lines.append(f"| default {k} run | {v['median']} | {v['max']} | {tgt} |")
    lines.append(f"| 20-case stress suite (both plans) | {stress_ms} | {stress_ms} | ≤ 60,000 |")
    lines += ["", "## Grid (coverage within 45 min, %)", "",
              "| Budget PKR | Units | Equity floor | Baseline | Greedy | Optimized | Opt − greedy (pp) |",
              "|---|---|---|---|---|---|---|"]

    def cell(s: dict) -> str:
        if s["status"] != "COMPLETED":
            return s["status"]
        return f"{s['coverage_pct']} ({','.join(s['selected']) or '—'})"

    for r in grid:
        lines.append(f"| {r['budget_pkr']:,} | {r['max_new_units']} | {r['equity_min_pct']}% | "
                     f"{cell(r['baseline'])} | {cell(r['greedy'])} | {cell(r['optimized'])} | "
                     f"{r.get('optimized_minus_greedy_pp', '—')} |")
    lines += ["", f"Audit pass rate on completed runs: {report['audit_pass_rate_completed']:.0%}. "
              f"Optimized never below greedy: {report['optimized_never_below_greedy']}.",
              "Ties are reported as ties. NO_SOLUTION means the equity floor cannot be met; no "
              "numbers are shown for it."]
    (out / f"benchmark-{backend}.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
