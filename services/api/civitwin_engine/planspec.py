"""PlanSpec contract (SRS §7.2) with the documented additions (min_coverage_pct)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .hashing import sha256_of

Policy = Literal["coverage_first", "equity_first", "cost_efficient"]

DEFAULTS = {
    "budget_pkr": 300_000,
    "max_new_units": 2,
    "threshold_minutes": 45,
    "demand_multiplier_pct": 100,
    "equity_min_pct": 0,
    "policy": "coverage_first",
    "seed": 2026,
    "min_coverage_pct": None,
}


class PlanSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    dataset_version_id: str = Field(min_length=1, max_length=64)
    budget_pkr: int = Field(ge=0, le=100_000_000)
    max_new_units: int = Field(ge=0, le=50)
    threshold_minutes: int = Field(ge=1, le=240)
    demand_multiplier_pct: int = Field(ge=1, le=300)
    equity_min_pct: int = Field(ge=0, le=100)
    policy: Policy
    # Solver random seed only. Dataset and stress seeds are separate (decision D6).
    seed: int = Field(ge=0, le=2_147_483_647)
    # Required only for the cost_efficient policy (decision D8).
    min_coverage_pct: int | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _policy_fields(self) -> PlanSpec:
        if self.policy == "cost_efficient" and self.min_coverage_pct is None:
            raise ValueError("cost_efficient policy requires min_coverage_pct")
        if self.policy != "cost_efficient" and self.min_coverage_pct is not None:
            raise ValueError("min_coverage_pct is only used by the cost_efficient policy")
        return self

    def plan_hash(self) -> str:
        return sha256_of(self.model_dump(mode="json"))

    def policy_independent_hash(self) -> str:
        d = self.model_dump(mode="json")
        d.pop("policy")
        d.pop("min_coverage_pct")
        return sha256_of(d)


def validate_against_dataset(plan: PlanSpec, eligible_candidates: int, total_demand: int) -> None:
    """Semantic checks that need the dataset (SRS §5.3, §7.2)."""
    if plan.max_new_units > eligible_candidates:
        raise ValueError(
            f"max_new_units ({plan.max_new_units}) exceeds eligible candidates "
            f"({eligible_candidates})"
        )
    if total_demand <= 0:
        raise ValueError("total demand is zero; there is nothing to plan")
