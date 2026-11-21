"""Dataset contracts (SRS §4.1). Aggregate, non-identifying planning data only."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, Strict

# Scalars are strict (no "5" -> 5, no 5.5 -> 5, no True -> 1); containers accept JSON lists.
SInt = Annotated[int, Strict()]
SStr = Annotated[str, Strict()]
SBool = Annotated[bool, Strict()]
SFloat = Annotated[float, Strict()]

# Resource caps (SRS §10.1).
MAX_NODES = 500
MAX_COMMUNITIES = 200
MAX_SITES = 100
MAX_EDGES = 5000
MAX_DEMAND_PER_COMMUNITY = 1_000_000
MAX_CAPACITY_PER_SITE = 1_000_000
MAX_COST_PKR = 100_000_000
MAX_EDGE_MINUTES = 10_000


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Node(_Strict):
    id: SStr = Field(min_length=1, max_length=64)
    label: SStr = Field(max_length=120)
    # Schematic display positions only; not real coordinates.
    display_x: SFloat
    display_y: SFloat


class Edge(_Strict):
    from_node: SStr = Field(min_length=1, max_length=64)
    to_node: SStr = Field(min_length=1, max_length=64)
    minutes: SFloat = Field(gt=0, le=MAX_EDGE_MINUTES)
    direction: Literal["two_way", "one_way"]


class Community(_Strict):
    id: SStr = Field(min_length=1, max_length=64)
    label: SStr = Field(max_length=120)
    demand_visits_per_week: SInt = Field(ge=0, le=MAX_DEMAND_PER_COMMUNITY)
    population: SInt | None = Field(default=None, ge=0)
    zone_class: Literal["central", "rural", "remote"]
    node_id: SStr = Field(min_length=1, max_length=64)


class Site(_Strict):
    id: SStr = Field(min_length=1, max_length=64)
    label: SStr = Field(max_length=120)
    type: Literal["existing", "candidate"]
    node_id: SStr = Field(min_length=1, max_length=64)
    capacity_per_week: SInt = Field(ge=0, le=MAX_CAPACITY_PER_SITE)
    fixed_cost_pkr: SInt = Field(ge=0, le=MAX_COST_PKR)
    eligible: SBool


class ProvenanceRecord(_Strict):
    entity: SStr
    field: SStr
    source: SStr
    method: Literal["synthetic", "observed", "estimated"]
    timestamp: SStr
    caveat: SStr


class DatasetManifest(_Strict):
    id: SStr = Field(min_length=1, max_length=64)
    version: SStr = Field(min_length=1, max_length=32)
    district_label: SStr
    is_synthetic: SBool
    source_url: SStr | None = None
    source_date: SStr
    license: SStr
    sha256: SStr | None = None
    assumptions: tuple[str, ...] = ()
    model_scope: SStr
    generator: dict[str, int | str | list[int]] | None = None


class Dataset(_Strict):
    manifest: DatasetManifest
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    communities: tuple[Community, ...]
    sites: tuple[Site, ...]
    provenance: tuple[ProvenanceRecord, ...] = ()

    def community(self, cid: str) -> Community:
        return next(c for c in self.communities if c.id == cid)

    def site(self, sid: str) -> Site:
        return next(s for s in self.sites if s.id == sid)
