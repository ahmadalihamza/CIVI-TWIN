"""T12: exports carry provenance and escape formulas; explanations come from evidence."""

import csv
import io
import json

from civitwin_engine.evidence import build_packet, explain_run
from civitwin_engine.export import csv_safe, export_csv, export_html, export_json
from civitwin_engine.fixtures import golden_dataset, golden_plan
from civitwin_engine.optimizer.problem import build_problem
from civitwin_engine.run import execute_run
from civitwin_engine.travel import travel_matrix


def _run(backend):
    ds = golden_dataset()
    r = execute_run(build_problem(ds, travel_matrix(ds), golden_plan()), "optimized",
                    backend=backend)
    return ds.manifest.model_dump(mode="json"), r


def test_csv_formula_escaping():
    assert csv_safe("=1+1") == "'=1+1"
    assert csv_safe("@SUM(A1)") == "'@SUM(A1)"
    assert csv_safe("-2") == "'-2"
    assert csv_safe("C01") == "C01"
    assert csv_safe(5) == 5


def test_exports_include_hashes_and_warning(backend):
    manifest, r = _run(backend)
    j = json.loads(export_json(r, manifest))
    assert "SYNTHETIC" in j["warning"]
    assert j["run"]["dataset_sha256"] == manifest["sha256"]
    assert j["evidence_packet"]["result_sha256"] == r["result_sha256"]
    rows = list(csv.reader(io.StringIO(export_csv(r, manifest))))
    flat = {row[0]: row[1] for row in rows if len(row) >= 2 and row[0].startswith("# ")}
    assert any("dataset_sha256" in k for k in flat)
    assert any("plan_hash" in k for k in flat)
    page = export_html(r, manifest)
    assert "SYNTHETIC DEMONSTRATION" in page and r["result_sha256"] in page
    assert "<script" not in page


def test_html_escapes_labels(backend):
    manifest, r = _run(backend)
    manifest = {**manifest, "district_label": "<script>alert(1)</script>"}
    assert "<script>alert" not in export_html(r, manifest)


def test_explanation_numbers_come_from_packet(backend):
    manifest, r = _run(backend)
    packet = build_packet(r, manifest)
    en = explain_run(packet, "en")
    assert "100 of 100 weekly visits (100.0%)" in en["sentences"][0]
    assert en["source"] == "template"
    ur = explain_run(packet, "ur")
    assert ur["review_note"] and "100.0%" in ur["sentences"][0]
