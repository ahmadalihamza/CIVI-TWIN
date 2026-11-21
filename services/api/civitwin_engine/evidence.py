"""Evidence packets and deterministic template explanations (SRS FR-10, FR-11, §7.3).

Templates are authoritative: every number is read from the audited result through an
evidence path. Urdu text is a draft translation that needs review by a fluent speaker.
"""

from __future__ import annotations

from typing import Any

from .hashing import sha256_of

URDU_REVIEW_NOTE = "Urdu wording is a draft and needs review by a fluent speaker."


def build_packet(run: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    if run.get("status") != "COMPLETED":
        raise ValueError("evidence packets are only built for COMPLETED, audited runs")
    m = run["metrics"]
    metrics = {}
    for key, v in m.items():
        if key == "per_cluster":
            continue
        metrics[key] = {**v, "evidence_id": f"result.metrics.{key}.value"}
    packet = {
        "run_id": run["run_id"],
        "kind": run["kind"],
        "dataset_id": manifest["id"],
        "dataset_label": manifest["district_label"],
        "is_synthetic": manifest["is_synthetic"],
        "dataset_sha256": run["dataset_sha256"],
        "plan_hash": run["plan_hash"],
        "result_sha256": run["result_sha256"],
        "model_version": run["model_version"],
        "solver_status": run["solver_status"],
        "optimality": run["optimality"],
        "engine": run["engine"],
        "audit_passed": run["audit"]["passed"],
        "audit_checks": len(run["audit"]["checks"]),
        "plan": run["plan"],
        "selected_candidate_ids": run["selected_candidate_ids"],
        "metrics": metrics,
        "assumptions": list(manifest.get("assumptions", [])),
        "time_horizon": "one modeled week",
    }
    packet["packet_sha256"] = sha256_of(packet)
    return packet


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.1f}%"


def _num(v: float | int | None) -> str:
    if v is None:
        return "n/a"
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.1f}"


def _sites(ids: list[str], lang: str) -> str:
    if not ids:
        return "no new sites" if lang == "en" else "کوئی نیا مرکز نہیں"
    return ", ".join(ids)


def explain_run(packet: dict[str, Any], lang: str = "en") -> dict[str, Any]:
    m = packet["metrics"]
    p = packet["plan"]
    status_word = ("proven optimal" if packet["optimality"] == "proven"
                   else "feasible but not proven optimal")
    worst_id = m["worst_cluster_coverage_pct"].get("community_id") or "n/a"
    kind_en = {"baseline": "the modeled baseline (existing sites only)",
               "optimized": "the optimized plan", "greedy": "the greedy benchmark plan"}
    kind_ur = {"baseline": "موجودہ مراکز پر مبنی ماڈل شدہ بنیادی صورتحال",
               "optimized": "بہتر بنایا گیا منصوبہ", "greedy": "سادہ (گریڈی) موازنہ منصوبہ"}
    if lang == "ur":
        text = [
            f"{kind_ur.get(packet['kind'], packet['kind'])} میں ہفتہ وار "
            f"{_num(m['total_demand']['value'])} وزٹس میں سے "
            f"{_num(m['within_threshold_visits']['value'])} وزٹس "
            f"({_pct(m['coverage_pct']['value'])}) {p['threshold_minutes']} منٹ کے اندر ہیں۔",
            f"{_num(m['unmet']['value'])} وزٹس پوری نہیں ہو پاتیں "
            f"({_pct(m['unmet_rate_pct']['value'])})۔",
            f"سب سے کم سہولت والا کلسٹر {worst_id} ہے، جس کی کوریج "
            f"{_pct(m['worst_cluster_coverage_pct']['value'])} ہے۔",
            f"نئے مراکز: {_sites(packet['selected_candidate_ids'], 'ur')}۔ ہفتہ وار لاگت "
            f"PKR {_num(m['cost_pkr']['value'])} ہے، بجٹ PKR {_num(p['budget_pkr'])}۔",
            f"سولور کی حیثیت: {packet['solver_status']}۔ آزاد آڈٹ: "
            f"{'کامیاب' if packet['audit_passed'] else 'ناکام'}"
            f" ({packet['audit_checks']} جانچیں)۔",
            ("یہ مصنوعی (فرضی) ڈیٹا پر مبنی مثال ہے، حقیقی ضلعی اعداد و شمار نہیں۔" if packet["is_synthetic"]
             else "یہ حقیقی عوامی ڈیٹا اور واضح مفروضوں پر مبنی مشاورتی تجزیہ ہے، منظور شدہ فیصلہ نہیں۔"),
        ]
        note = URDU_REVIEW_NOTE
    else:
        text = [
            f"Under {kind_en.get(packet['kind'], packet['kind'])}, "
            f"{_num(m['within_threshold_visits']['value'])} of "
            f"{_num(m['total_demand']['value'])} weekly visits "
            f"({_pct(m['coverage_pct']['value'])}) are within {p['threshold_minutes']} minutes.",
            f"{_num(m['unmet']['value'])} visits remain unmet "
            f"({_pct(m['unmet_rate_pct']['value'])}); served visits average "
            f"{_num(m['mean_travel_min']['value'])} minutes of travel.",
            f"The worst-served cluster is {worst_id} at "
            f"{_pct(m['worst_cluster_coverage_pct']['value'])} coverage.",
            f"New sites: {_sites(packet['selected_candidate_ids'], 'en')}. Weekly cost is PKR "
            f"{_num(m['cost_pkr']['value'])} of a PKR {_num(p['budget_pkr'])} budget.",
            f"Solver status: {packet['solver_status']} ({status_word}). Independent audit: "
            f"{'passed' if packet['audit_passed'] else 'failed'} "
            f"({packet['audit_checks']} checks).",
            ("Synthetic demonstration data; this is not a statement about real district services." if packet["is_synthetic"]
             else "Real public data with stated assumptions (population split, utilisation, capacity, costs); advisory, not an approved allocation."),
        ]
        note = None
    return {
        "language": lang,
        "source": "template",
        "sentences": text,
        "evidence_ids": [
            "result.metrics.within_threshold_visits.value", "result.metrics.total_demand.value",
            "result.metrics.coverage_pct.value", "result.metrics.unmet.value",
            "result.metrics.unmet_rate_pct.value", "result.metrics.mean_travel_min.value",
            "result.metrics.worst_cluster_coverage_pct.value", "result.metrics.cost_pkr.value",
            "result.selected_candidate_ids", "result.solver_status", "result.audit.passed",
        ],
        "review_note": note,
        "packet_sha256": packet["packet_sha256"],
    }


def explain_comparison(cmp: dict[str, Any], base: dict[str, Any], alt: dict[str, Any],
                       lang: str = "en") -> list[str]:
    d = cmp["deltas"]
    acpv = cmp["additional_cost_per_added_covered_visit"]["value"]
    bm, am = base["metrics"], alt["metrics"]
    if lang == "ur":
        out = [
            f"کوریج {_pct(bm['coverage_pct']['value'])} سے {_pct(am['coverage_pct']['value'])} "
            f"ہو جاتی ہے ({d['coverage_pp']:+.1f} فیصدی پوائنٹس)۔",
            f"پوری نہ ہونے والی وزٹس {_num(bm['unmet']['value'])} سے "
            f"{_num(am['unmet']['value'])} ہو جاتی ہیں۔",
            f"اضافی ہفتہ وار لاگت PKR {_num(d['cost_pkr'])}"
            + (f"، یعنی ہر اضافی بروقت وزٹ پر تقریباً PKR {_num(acpv)}۔" if acpv is not None
               else "۔"),
        ]
    else:
        out = [
            f"Within-threshold coverage moves from {_pct(bm['coverage_pct']['value'])} to "
            f"{_pct(am['coverage_pct']['value'])} ({d['coverage_pp']:+.1f} percentage points).",
            f"Unmet visits change from {_num(bm['unmet']['value'])} to "
            f"{_num(am['unmet']['value'])} per week.",
            f"Additional weekly cost is PKR {_num(d['cost_pkr'])}"
            + (f", about PKR {_num(acpv)} per added within-threshold visit." if acpv is not None
               else "; coverage did not improve, so no cost per added visit is reported."),
        ]
    if cmp["tie_or_worse"]:
        out.append("The alternative does not improve coverage over the baseline."
                   if lang == "en" else "متبادل منصوبہ بنیادی صورتحال سے بہتر کوریج نہیں دیتا۔")
    return out
