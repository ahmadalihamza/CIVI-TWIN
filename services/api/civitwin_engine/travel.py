"""Community-to-site travel costs on the schematic network (SRS FR-03, §5.1).

Unreachable pairs are absent (never zero). Raw shortest-path minutes are kept so that
stress multipliers are applied before the single half-up rounding step.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import networkx as nx

from .dataset.schema import Dataset
from .hashing import round_half_up


@dataclass(frozen=True)
class TravelMatrix:
    dataset_sha256: str
    raw_minutes: dict[tuple[str, str], float]  # (community_id, site_id) -> unrounded minutes

    def minutes(self, travel_pct: int = 100) -> dict[tuple[str, str], int]:
        return {k: round_half_up(v * travel_pct / 100) for k, v in self.raw_minutes.items()}

    def unreachable(self, community_ids: list[str], site_ids: list[str]) -> list[tuple[str, str]]:
        return [(c, s) for c in community_ids for s in site_ids if (c, s) not in self.raw_minutes]


def _graph(ds: Dataset) -> nx.DiGraph:
    g = nx.DiGraph()
    g.add_nodes_from(n.id for n in ds.nodes)
    for e in ds.edges:
        for a, b in [(e.from_node, e.to_node)] + (
            [(e.to_node, e.from_node)] if e.direction == "two_way" else []
        ):
            # keep the fastest parallel edge
            if not g.has_edge(a, b) or g[a][b]["minutes"] > e.minutes:
                g.add_edge(a, b, minutes=e.minutes)
    return g


_CACHE: dict[str, TravelMatrix] = {}


def travel_matrix(ds: Dataset) -> TravelMatrix:
    """Deterministic Dijkstra from each community node; cached by dataset hash."""
    key = ds.manifest.sha256 or ""
    if key and key in _CACHE:
        return _CACHE[key]
    g = _graph(ds)
    raw: dict[tuple[str, str], float] = {}
    for c in sorted(ds.communities, key=lambda c: c.id):
        lengths = nx.single_source_dijkstra_path_length(g, c.node_id, weight="minutes")
        for s in sorted(ds.sites, key=lambda s: s.id):
            if s.node_id in lengths:
                raw[(c.id, s.id)] = float(lengths[s.node_id])
    tm = TravelMatrix(dataset_sha256=key, raw_minutes=raw)
    if key:
        _CACHE[key] = tm
    return tm


@lru_cache(maxsize=1)
def networkx_version() -> str:
    return nx.__version__
