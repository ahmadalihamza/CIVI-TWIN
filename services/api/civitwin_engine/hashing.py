"""Canonical JSON and SHA-256 helpers (SRS §4.3, §7.2)."""

from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Any


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, UTF-8 characters kept."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_of(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def round_half_up(value: float | int | Decimal) -> int:
    """Round half away from zero for non-negative values (documented rounding rule)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def scale_half_up(value: int, *pcts: int) -> int:
    """value * p1/100 * p2/100 ... rounded half-up once, using exact integer arithmetic."""
    num = value
    den = 1
    for p in pcts:
        num *= p
        den *= 100
    return (2 * num + den) // (2 * den)
