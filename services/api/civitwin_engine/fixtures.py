"""Deterministic mathematical fixtures (SRS §11.1). Not district statistics."""

from __future__ import annotations

from .dataset.schema import Community, Dataset, DatasetManifest, Edge, Node, Site
from .dataset.validation import with_hash
from .planspec import PlanSpec


def golden_dataset() -> Dataset:
    """Clusters A/B (60/40); existing E cap 60; candidate N cap 40, cost 100.

    Travel: A-E 10, B-E 50, A-N 40, B-N 10 (indirect paths are all longer).
    """
    nodes = (
        Node(id="nA", label="A", display_x=0, display_y=0),
        Node(id="nB", label="B", display_x=10, display_y=0),
        Node(id="nE", label="E", display_x=0, display_y=10),
        Node(id="nN", label="N", display_x=10, display_y=10),
    )
    edges = (
        Edge(from_node="nA", to_node="nE", minutes=10, direction="two_way"),
        Edge(from_node="nB", to_node="nE", minutes=50, direction="two_way"),
        Edge(from_node="nA", to_node="nN", minutes=40, direction="two_way"),
        Edge(from_node="nB", to_node="nN", minutes=10, direction="two_way"),
    )
    communities = (
        Community(id="A", label="A", demand_visits_per_week=60, zone_class="central",
                  node_id="nA"),
        Community(id="B", label="B", demand_visits_per_week=40, zone_class="rural",
                  node_id="nB"),
    )
    sites = (
        Site(id="E", label="E", type="existing", node_id="nE", capacity_per_week=60,
             fixed_cost_pkr=0, eligible=True),
        Site(id="N", label="N", type="candidate", node_id="nN", capacity_per_week=40,
             fixed_cost_pkr=100, eligible=True),
    )
    manifest = DatasetManifest(
        id="fixture-golden-v1", version="1", district_label="Golden fixture",
        is_synthetic=True, source_date="2026-11-20", license="CC0-1.0",
        model_scope="Mathematical test fixture (SRS §11.1).",
    )
    return with_hash(Dataset(manifest=manifest, nodes=nodes, edges=edges,
                             communities=communities, sites=sites))


def golden_plan(**overrides: object) -> PlanSpec:
    base = {
        "dataset_version_id": "fixture-golden-v1", "budget_pkr": 100, "max_new_units": 1,
        "threshold_minutes": 30, "demand_multiplier_pct": 100, "equity_min_pct": 0,
        "policy": "coverage_first", "seed": 2026, "min_coverage_pct": None,
    }
    base.update(overrides)
    return PlanSpec.model_validate(base)
