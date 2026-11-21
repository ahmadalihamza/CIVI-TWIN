"""Exports: JSON, CSV (formula-escaped) and printable HTML (SRS FR-12, §10.1)."""

from __future__ import annotations

import csv
import html
import io
import json
from typing import Any

from .evidence import build_packet, explain_run

BANNER = "SYNTHETIC DEMONSTRATION — fictional data, advisory planning sandbox only"
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


REAL_BANNER = "REAL PUBLIC DATA WITH STATED ASSUMPTIONS — advisory planning output, not an approved allocation"


def banner(manifest: dict[str, Any]) -> str:
    return BANNER if manifest.get("is_synthetic", True) else REAL_BANNER


def export_json(run: dict[str, Any], manifest: dict[str, Any]) -> str:
    payload = {
        "warning": banner(manifest),
        "dataset_manifest": manifest,
        "run": run,
        "evidence_packet": build_packet(run, manifest) if run.get("status") == "COMPLETED"
        else None,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)


def export_csv(run: dict[str, Any], manifest: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    meta = [
        ("warning", banner(manifest)), ("dataset_id", manifest["id"]),
        ("dataset_label", manifest["district_label"]),
        ("dataset_sha256", run["dataset_sha256"]), ("plan_hash", run["plan_hash"]),
        ("result_sha256", run.get("result_sha256")), ("run_id", run["run_id"]),
        ("kind", run["kind"]), ("status", run["status"]),
        ("solver_status", run["solver_status"]),
        ("solver", (run.get("engine") or {}).get("solver_version")),
        ("audit_passed", (run.get("audit") or {}).get("passed")),
    ]
    for k, v in meta:
        w.writerow([csv_safe(f"# {k}"), csv_safe(v)])
    w.writerow([])
    w.writerow(["section", "community_id", "site_id", "visits_per_week", "minutes"])
    for a in run.get("assignments", []):
        w.writerow(["assignment", csv_safe(a["community_id"]), csv_safe(a["site_id"]),
                    a["visits"], a["minutes"]])
    for u in run.get("unmet_by_community", []):
        w.writerow(["unmet", csv_safe(u["community_id"]), "", u["visits"], ""])
    w.writerow([])
    w.writerow(["metric", "value", "unit", "numerator", "denominator"])
    for k, v in (run.get("metrics") or {}).items():
        if k == "per_cluster":
            continue
        w.writerow([csv_safe(k), v["value"], csv_safe(v["unit"]), v["numerator"],
                    v["denominator"]])
    w.writerow([])
    w.writerow(["cluster", "demand", "served", "within_threshold", "unmet", "coverage_pct"])
    for c in (run.get("metrics") or {}).get("per_cluster", []):
        w.writerow([csv_safe(c["community_id"]), c["demand"], c["served"],
                    c["within_threshold"], c["unmet"], c["coverage_pct"]])
    return buf.getvalue()


def export_html(run: dict[str, Any], manifest: dict[str, Any],
                comparison_lines: list[str] | None = None) -> str:
    e = html.escape
    if run.get("status") != "COMPLETED":
        body = (f"<p><strong>Status: {e(str(run.get('status')))}</strong>. No allocation was "
                "computed, so no metrics are shown.</p>")
        for h in (run.get("error") or {}).get("hints", []):
            body += f"<p>{e(h)}</p>"
    else:
        packet = build_packet(run, manifest)
        expl = explain_run(packet, "en")
        m = run["metrics"]
        rows = "".join(
            f"<tr><td>{e(k)}</td><td>{e(str(v['value']))}</td><td>{e(v['unit'])}</td>"
            f"<td>{e(str(v['numerator']))}</td><td>{e(str(v['denominator']))}</td></tr>"
            for k, v in m.items() if k != "per_cluster")
        checks = "".join(
            f"<tr><td>{e(c['id'])}</td><td>{e(c['name'])}</td>"
            f"<td>{'PASS' if c['passed'] else 'FAIL'}</td></tr>" for c in run["audit"]["checks"])
        assumptions = "".join(f"<li>{e(a)}</li>" for a in manifest.get("assumptions", []))
        cmp_html = "".join(f"<li>{e(x)}</li>" for x in (comparison_lines or []))
        body = (
            "<h2>Summary</h2>" + "".join(f"<p>{e(s)}</p>" for s in expl["sentences"])
            + (f"<h2>Comparison with baseline</h2><ul>{cmp_html}</ul>" if cmp_html else "")
            + f"<h2>Metrics</h2><table><tr><th>Metric</th><th>Value</th><th>Unit</th>"
              f"<th>Numerator</th><th>Denominator</th></tr>{rows}</table>"
            + f"<h2>Independent audit</h2><table><tr><th>ID</th><th>Check</th><th>Result</th>"
              f"</tr>{checks}</table>"
            + f"<h2>Assumptions and limitations</h2><ul>{assumptions}"
              "<li>Results are hypothetical decision support, not medical advice or approved "
              "allocations.</li><li>Stress ranges are scenario ranges, not forecasts.</li></ul>"
        )
    plan = run.get("plan", {})
    plan_rows = "".join(f"<tr><td>{e(k)}</td><td>{e(str(v))}</td></tr>" for k, v in plan.items())
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>CIVITWIN report {e(run['run_id'])}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;color:#0f1f3d;
line-height:1.5;padding:0 1rem}}
.banner{{background:#fff4d6;border:2px solid #b7791f;padding:.6rem 1rem;font-weight:700}}
table{{border-collapse:collapse;width:100%;margin:.5rem 0 1rem}}
td,th{{border:1px solid #c9d3e0;padding:.3rem .5rem;text-align:left;font-size:.9rem}}
h1{{color:#0f2a4a}} h2{{color:#0f5e63;border-bottom:1px solid #c9d3e0}}
code{{word-break:break-all}}
</style></head><body>
<div class="banner">{e(banner(manifest))}</div>
<h1>CIVITWIN AI planning report</h1>
<p>Dataset: {e(manifest['district_label'])} (version {e(manifest['version'])}) ·
Run: {e(run['run_id'])} · Kind: {e(run['kind'])} · Status: {e(str(run['status']))} ·
Solver: {e(str(run.get('solver_status')))} · Time horizon: one modeled week</p>
<p>Dataset SHA-256: <code>{e(run['dataset_sha256'])}</code><br>
Plan hash: <code>{e(run['plan_hash'])}</code><br>
Result SHA-256: <code>{e(str(run.get('result_sha256')))}</code></p>
<h2>Confirmed plan</h2><table>{plan_rows}</table>
{body}
</body></html>"""
