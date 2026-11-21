"""Solver-independent planning instance built from dataset + travel + PlanSpec."""

from __future__ import annotations

from dataclasses import dataclass

from ..dataset.schema import Dataset
from ..hashing import scale_half_up
from ..planspec import PlanSpec, validate_against_dataset
from ..travel import TravelMatrix

INT64_SAFE = 2**62


@dataclass(frozen=True)
class Problem:
    dataset_sha256: str
    plan_hash: str
    plan: PlanSpec
    community_ids: tuple[str, ...]
    demand: dict[str, int]
    site_ids: tuple[str, ...]
    site_type: dict[str, str]
    capacity: dict[str, int]
    cost: dict[str, int]
    eligible: dict[str, bool]
    travel: dict[tuple[str, str], int]  # reachable pairs only
    stress_demand_pct: int = 100
    stress_travel_pct: int = 100
    is_synthetic: bool = True

    @property
    def threshold(self) -> int:
        return self.plan.threshold_minutes

    @property
    def total_demand(self) -> int:
        return sum(self.demand.values())

    @property
    def existing_ids(self) -> list[str]:
        return [s for s in self.site_ids if self.site_type[s] == "existing"]

    @property
    def candidate_ids(self) -> list[str]:
        return [s for s in self.site_ids if self.site_type[s] == "candidate"]

    @property
    def eligible_candidate_ids(self) -> list[str]:
        return [s for s in self.candidate_ids if self.eligible[s]]

    def within(self, c: str, s: str) -> bool:
        t = self.travel.get((c, s))
        return t is not None and t <= self.threshold


class ProblemError(ValueError):
    pass


def build_problem(
    ds: Dataset,
    tm: TravelMatrix,
    plan: PlanSpec,
    *,
    stress_demand_pct: int = 100,
    stress_travel_pct: int = 100,
) -> Problem:
    if plan.dataset_version_id != ds.manifest.id:
        raise ProblemError(
            f"plan targets dataset {plan.dataset_version_id!r} but {ds.manifest.id!r} is loaded"
        )
    if tm.dataset_sha256 != ds.manifest.sha256:
        raise ProblemError("travel matrix was computed for a different dataset")

    communities = sorted(ds.communities, key=lambda c: c.id)
    sites = sorted(ds.sites, key=lambda s: s.id)
    # Demand multiplier(s) applied with one half-up rounding (decision D4).
    demand = {
        c.id: scale_half_up(c.demand_visits_per_week, plan.demand_multiplier_pct, stress_demand_pct)
        for c in communities
    }
    travel = tm.minutes(stress_travel_pct)

    eligible_n = sum(1 for s in sites if s.type == "candidate" and s.eligible)
    try:
        validate_against_dataset(plan, eligible_n, sum(demand.values()))
    except ValueError as exc:
        raise ProblemError(str(exc)) from None

    # 64-bit overflow guard for the largest linear expressions (SRS §5.3).
    total_d = sum(demand.values())
    max_t = max(travel.values(), default=0)
    bounds = [
        max_t * total_d,
        10_000 * max(demand.values(), default=0),
        sum(s.fixed_cost_pkr for s in sites) + plan.budget_pkr,
    ]
    if max(bounds) >= INT64_SAFE:
        raise ProblemError("model coefficients exceed safe 64-bit bounds")

    return Problem(
        dataset_sha256=ds.manifest.sha256 or "",
        plan_hash=plan.plan_hash(),
        plan=plan,
        community_ids=tuple(c.id for c in communities),
        demand=demand,
        site_ids=tuple(s.id for s in sites),
        site_type={s.id: s.type for s in sites},
        capacity={s.id: s.capacity_per_week for s in sites},
        cost={s.id: s.fixed_cost_pkr for s in sites},
        eligible={s.id: s.eligible for s in sites},
        travel=travel,
        stress_demand_pct=stress_demand_pct,
        stress_travel_pct=stress_travel_pct,
        is_synthetic=ds.manifest.is_synthetic,
    )
