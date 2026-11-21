"""Offline rule-based plan parser for English and Urdu requests (SRS FR-14, §7.2).

It only fills PlanSpec fields. It never executes anything, never clamps out-of-range
values (validation reports them), and lists every default it used so the planner can
review the draft before confirming. Text that is not a planning parameter is ignored
and flagged.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from .planspec import DEFAULTS, PlanSpec

PARSER_VERSION = "rule-based-1.0"

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_EN_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
             "eight": 8, "nine": 9, "ten": 10, "a single": 1}
_UR_WORDS = {"ایک": 1, "دو": 2, "تین": 3, "چار": 4, "پانچ": 5, "چھ": 6, "سات": 7, "آٹھ": 8}
_MULT = {"lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
         "crore": 10_000_000, "crores": 10_000_000, "million": 1_000_000,
         "thousand": 1_000, "hazar": 1_000, "k": 1_000,
         "لاکھ": 100_000, "کروڑ": 10_000_000, "ہزار": 1_000}

NUM = r"(\d+(?:[.,]\d+)*)"
MULT = r"(lakhs?|lacs?|crores?|million|thousand|hazar|k(?![a-z])|لاکھ|کروڑ|ہزار)"
CURRENCY = r"(?:rs\.?|pkr|rupees?|روپے|روپیہ)"
UNIT_NOUN = (r"(?:new\s+|نئے\s+|نئی\s+)?(?:health\s+)?(?:units?|sites?|cent(?:re|er)s?|"
             r"facilit(?:y|ies)|clinics?|bhus?|مراکز|مرکز|یونٹس|یونٹ|کلینک|سینٹر|سنٹر)")

_INJECTION = re.compile(
    r"ignore|instruction|system prompt|jailbreak|delete|drop\s+table|\bsql\b|shell|rm\s+-rf|"
    r"execute|password|api[\s_-]?key|token|curl|http[s]?://|<script",
    re.IGNORECASE,
)
_EQUITY_CTX = re.compile(
    r"every|each|all|no\s+(?:cluster|village|community|area)|any\s+(?:cluster|village)|minimum|"
    r"at\s+least|floor|equity|fair|ہر|کم\s*از\s*کم|انصاف|سب", re.IGNORECASE)
_DEMAND_CTX = re.compile(r"demand|visits|patients|load|طلب|مریض", re.IGNORECASE)
_UP = re.compile(r"increase|rise|rises|grow|grows|more|up|higher|اضافہ|بڑھ|زیادہ", re.IGNORECASE)
_DOWN = re.compile(r"decrease|drop|fall|falls|less|down|lower|reduce|کمی|گھٹ", re.IGNORECASE)
_COVERAGE_CTX = re.compile(r"coverage|covered|cover|کوریج|رسائی", re.IGNORECASE)


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _normalize(text: str) -> str:
    t = text.translate(_DIGITS).lower()
    for w, n in _EN_WORDS.items():
        t = re.sub(rf"\b{w}\b", str(n), t)
    # Urdu number words only when directly followed by a unit noun ("دو" also means "give").
    for w, n in _UR_WORDS.items():
        t = re.sub(rf"(?<!\S){w}(?=\s+(?:نئے\s+|نئی\s+)?(?:مراکز|مرکز|یونٹ|کلینک|سینٹر))", str(n), t)
    return t


def _language(text: str) -> str:
    urdu = len(re.findall(r"[؀-ۿ]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if urdu and latin:
        return "mixed"
    return "ur" if urdu else "en"


def parse_request(text: str, dataset_version_id: str) -> dict[str, Any]:
    raw = text or ""
    t = _normalize(raw[:2000])
    found: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    used_spans: list[tuple[int, int]] = []

    def take(field: str, value: Any, m: re.Match[str]) -> None:
        if field not in found:
            found[field] = {"value": value, "text": m.group(0).strip()}
            used_spans.append(m.span())

    def overlaps(m: re.Match[str]) -> bool:
        return any(m.start() < e and s < m.end() for s, e in used_spans)

    # Budget: explicit budget word, or a money expression (multiplier or currency marker).
    not_other = rf"(?!\s*(?:%|percent|فیصد|minutes?|mins?|منٹ|hours?|{UNIT_NOUN}))"
    for pat in (
        rf"{CURRENCY}\s*{NUM}\s*{MULT}?",
        rf"{NUM}\s*{MULT}\s*(?:{CURRENCY})?",
        rf"{NUM}\s*{CURRENCY}",
        rf"(?:budget|بجٹ)[^\d]{{0,25}}{NUM}{not_other}\s*{MULT}?",
    ):
        for m in re.finditer(pat, t):
            if overlaps(m):
                continue
            groups = [g for g in m.groups() if g]
            val = _num(groups[0])
            mult = next((_MULT[g] for g in groups[1:] if g in _MULT), 1)
            take("budget_pkr", int(round(val * mult)), m)
            break
        if "budget_pkr" in found:
            break

    m = re.search(rf"{NUM}\s*{UNIT_NOUN}", t)
    if m and not overlaps(m):
        take("max_new_units", int(_num(m.group(1))), m)
    elif re.search(r"\bno\s+new\s+(?:units?|sites?|cent(?:re|er)s?|facilit)", t):
        found["max_new_units"] = {"value": 0, "text": "no new units"}

    m = re.search(rf"{NUM}\s*(?:minutes?|mins?|منٹ)", t)
    if m and not overlaps(m):
        take("threshold_minutes", int(round(_num(m.group(1)))), m)
    else:
        m = re.search(rf"{NUM}\s*(?:hours?|hrs?|گھنٹے|گھنٹہ)", t)
        if m and not overlaps(m):
            take("threshold_minutes", int(round(_num(m.group(1)) * 60)), m)

    # Policy
    if re.search(r"equity\s*first|fairness\s*first|fair(?:est)?\s+plan|most\s+fair|"
                 r"انصاف\s*کو\s*ترجیح|انصاف\s*پہلے", t):
        found["policy"] = {"value": "equity_first", "text": "equity first"}
    elif re.search(r"cost[\s-]*efficient|cheapest|lowest\s+cost|minimi[sz]e\s+cost|کم\s*لاگت|"
                   r"سستا", t):
        found["policy"] = {"value": "cost_efficient", "text": "cost efficient"}
    elif re.search(r"coverage\s*first|maximi[sz]e\s+coverage|زیادہ\s*سے\s*زیادہ\s*کوریج", t):
        found["policy"] = {"value": "coverage_first", "text": "coverage first"}

    # Percentages: demand change, coverage target (cost-efficient) or equity floor.
    for m in re.finditer(rf"{NUM}\s*(?:%|percent|per\s+cent|فیصد)", t):
        if overlaps(m):
            continue
        n = _num(m.group(1))
        ctx = t[max(0, m.start() - 45): m.end() + 45]
        if _DEMAND_CTX.search(ctx):
            if _UP.search(ctx):
                take("demand_multiplier_pct", int(round(100 + n)), m)
            elif _DOWN.search(ctx):
                take("demand_multiplier_pct", int(round(100 - n)), m)
            else:
                take("demand_multiplier_pct", int(round(n)), m)
                warnings.append(f"Read '{m.group(0).strip()}' as demand at {int(n)}% of the "
                                "baseline. Edit it if you meant a change.")
        elif found.get("policy", {}).get("value") == "cost_efficient" and _COVERAGE_CTX.search(ctx):
            take("min_coverage_pct", int(round(n)), m)
        elif _EQUITY_CTX.search(ctx):
            take("equity_min_pct", int(round(n)), m)
        else:
            warnings.append(f"Could not tell what '{m.group(0).strip()}' refers to; it was "
                            "ignored.")

    if _INJECTION.search(raw):
        warnings.append("The request contains text that is not a planning parameter (for "
                        "example instructions, code or links). It was ignored; only the "
                        "fields shown below are used.")

    draft: dict[str, Any] = {"dataset_version_id": dataset_version_id}
    defaults_used = []
    for k, v in DEFAULTS.items():
        if k in found:
            draft[k] = found[k]["value"]
        else:
            draft[k] = v
            if k != "min_coverage_pct":
                defaults_used.append(k)
    if draft["policy"] == "cost_efficient" and draft["min_coverage_pct"] is None:
        warnings.append("The cost-efficient policy needs a minimum coverage target (for example "
                        "'at least 60% coverage'). Please add one or choose another policy.")
    if draft["policy"] != "cost_efficient":
        draft["min_coverage_pct"] = None

    field_errors: list[dict[str, str]] = []
    plan_hash = None
    try:
        plan = PlanSpec.model_validate(draft)
        plan_hash = plan.plan_hash()
    except ValidationError as exc:
        for e in exc.errors():
            field_errors.append({"field": ".".join(str(p) for p in e["loc"]) or "plan",
                                 "message": e["msg"]})

    if not found:
        warnings.append("No planning values were recognised. Use the form, or try e.g. "
                        "'Rs 3 lakh per week, 2 new units, within 45 minutes'.")

    return {
        "parser": PARSER_VERSION,
        "language": _language(raw),
        "draft": draft,
        "recognized": found,
        "defaults_used": defaults_used,
        "warnings": warnings,
        "field_errors": field_errors,
        "valid": not field_errors,
        "plan_hash": plan_hash,
        "needs_confirmation": True,
    }
