"""Dataset validation and hashing (SRS FR-01, FR-02, §4.3).

Invalid imports are rejected as a whole with machine-readable, row-level errors.
Nothing is imputed: missing optional fields stay unknown, missing roads mean unreachable.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from pydantic import ValidationError

from ..hashing import sha256_of
from .schema import (
    MAX_COMMUNITIES,
    MAX_EDGES,
    MAX_NODES,
    MAX_SITES,
    Dataset,
)


class DatasetValidationError(ValueError):
    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        super().__init__(f"dataset rejected: {len(errors)} error(s)")


def dataset_hash(ds: Dataset) -> str:
    """SHA-256 of the canonical dataset, excluding the manifest's own sha256 field."""
    payload = ds.model_dump(mode="json")
    payload["manifest"]["sha256"] = None
    payload["nodes"] = sorted(payload["nodes"], key=lambda n: n["id"])
    payload["communities"] = sorted(payload["communities"], key=lambda c: c["id"])
    payload["sites"] = sorted(payload["sites"], key=lambda s: s["id"])
    payload["edges"] = sorted(
        payload["edges"],
        key=lambda e: (e["from_node"], e["to_node"], e["direction"], e["minutes"]),
    )
    payload["provenance"] = sorted(
        payload["provenance"], key=lambda p: (p["entity"], p["field"], p["source"])
    )
    return sha256_of(payload)


def with_hash(ds: Dataset) -> Dataset:
    manifest = ds.manifest.model_copy(update={"sha256": dataset_hash(ds)})
    return ds.model_copy(update={"manifest": manifest})


def _pydantic_errors(exc: ValidationError) -> list[dict[str, Any]]:
    out = []
    for e in exc.errors():
        loc = list(e["loc"])
        entity = str(loc[0]) if loc else "dataset"
        row = loc[1] if len(loc) > 1 and isinstance(loc[1], int) else None
        field = ".".join(str(p) for p in loc[2:] if not isinstance(p, int)) if row is not None \
            else ".".join(str(p) for p in loc[1:])
        out.append(
            {"entity": entity, "row": row, "field": field or None,
             "code": e["type"], "message": e["msg"]}
        )
    return out


def validate_dataset(raw: dict[str, Any], *, require_hash_match: bool = True) -> Dataset:
    """Parse and semantically validate a dataset bundle. Raises DatasetValidationError."""
    try:
        ds = Dataset.model_validate(raw)
    except ValidationError as exc:
        raise DatasetValidationError(_pydantic_errors(exc)) from None

    errors: list[dict[str, Any]] = []

    def err(entity: str, row: int | None, field: str | None, code: str, msg: str) -> None:
        errors.append({"entity": entity, "row": row, "field": field, "code": code, "message": msg})

    caps = [("nodes", ds.nodes, MAX_NODES), ("edges", ds.edges, MAX_EDGES),
            ("communities", ds.communities, MAX_COMMUNITIES), ("sites", ds.sites, MAX_SITES)]
    for name, items, cap in caps:
        if len(items) > cap:
            err(name, None, None, "too_many", f"{len(items)} {name} exceeds cap {cap}")

    for name, items in (("nodes", ds.nodes), ("communities", ds.communities), ("sites", ds.sites)):
        counts = Counter(i.id for i in items)
        for idx, item in enumerate(items):
            if counts[item.id] > 1:
                err(name, idx, "id", "duplicate_id", f"duplicate id {item.id!r}")

    clash = {c.id for c in ds.communities} & {s.id for s in ds.sites}
    for cid in sorted(clash):
        err("communities", None, "id", "id_clash", f"id {cid!r} used by a community and a site")

    node_ids = {n.id for n in ds.nodes}
    for idx, e in enumerate(ds.edges):
        for fld in ("from_node", "to_node"):
            if getattr(e, fld) not in node_ids:
                err("edges", idx, fld, "unknown_node", f"unknown node {getattr(e, fld)!r}")
        if e.from_node == e.to_node:
            err("edges", idx, "to_node", "self_loop", "edge connects a node to itself")
    for name, items in (("communities", ds.communities), ("sites", ds.sites)):
        for idx, item in enumerate(items):
            if item.node_id not in node_ids:
                err(name, idx, "node_id", "unknown_node", f"unknown node {item.node_id!r}")

    if not ds.communities:
        err("communities", None, None, "empty", "dataset has no communities")
    if not any(s.type == "existing" for s in ds.sites) and not any(
        s.type == "candidate" for s in ds.sites
    ):
        err("sites", None, None, "empty", "dataset has no sites")

    if errors:
        raise DatasetValidationError(errors)

    computed = dataset_hash(ds)
    if ds.manifest.sha256 is not None and require_hash_match and ds.manifest.sha256 != computed:
        raise DatasetValidationError(
            [{"entity": "manifest", "row": None, "field": "sha256", "code": "hash_mismatch",
              "message": f"manifest sha256 does not match content (computed {computed})"}]
        )
    return with_hash(ds)
