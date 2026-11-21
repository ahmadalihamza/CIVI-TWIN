"""Solver-neutral integer linear model plus two lexicographic backends.

Backends:
  * "cpsat" — Google OR-Tools CP-SAT (SRS §3.2 preferred engine), 1 worker, fixed seed.
  * "highs" — HiGHS MILP via scipy.optimize.milp (fallback when OR-Tools is not
    installed). mip_rel_gap = 0, so OPTIMAL means proven optimal.

Both receive the same variables, constraints and objective stages. Every result is
checked afterwards by the independent audit, whichever backend produced it.
"""

from __future__ import annotations

import math
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

Coeffs = dict[int, int]


@dataclass
class LinModel:
    names: list[str] = field(default_factory=list)
    lb: list[int] = field(default_factory=list)
    ub: list[int] = field(default_factory=list)
    rows: list[tuple[Coeffs, float, float]] = field(default_factory=list)

    def var(self, name: str, lb: int, ub: int) -> int:
        self.names.append(name)
        self.lb.append(lb)
        self.ub.append(ub)
        return len(self.names) - 1

    def add(self, coeffs: Coeffs, lo: float = -math.inf, hi: float = math.inf) -> None:
        coeffs = {k: v for k, v in coeffs.items() if v != 0}
        self.rows.append((coeffs, lo, hi))


@dataclass(frozen=True)
class Expr:
    coeffs: Coeffs
    const: int = 0

    def value(self, x: list[int]) -> int:
        return self.const + sum(c * x[i] for i, c in self.coeffs.items())


@dataclass
class StageOutcome:
    kind: str  # SOLVED | INFEASIBLE | TIMED_OUT | CANCELLED | FAILED
    values: list[int] | None
    stage_log: list[dict[str, Any]]
    stopped_reason: str | None
    backend: str
    backend_version: str


def available_backends() -> list[str]:
    out = []
    try:
        import ortools  # noqa: F401

        out.append("cpsat")
    except ImportError:
        pass
    try:
        from scipy.optimize import milp  # noqa: F401

        out.append("highs")
    except ImportError:
        pass
    return out


def default_backend() -> str:
    forced = os.environ.get("CIVITWIN_SOLVER", "").strip().lower()
    avail = available_backends()
    if forced:
        if forced not in avail:
            raise RuntimeError(f"solver backend {forced!r} not available (have {avail})")
        return forced
    if not avail:
        raise RuntimeError("no solver backend installed (need ortools or scipy)")
    return avail[0]


def backend_version(backend: str) -> str:
    if backend == "cpsat":
        import ortools

        return f"ortools-cpsat {ortools.__version__}"
    import scipy

    return f"scipy-highs {scipy.__version__}"


def _not_run(stages: list[tuple[str, str]], labels: dict[str, str]) -> list[dict[str, Any]]:
    return [{"stage": n, "sense": s, "label": labels[n], "status": "NOT_RUN", "value": None}
            for n, s in stages]


def solve_lexicographic(
    model: LinModel,
    exprs: dict[str, Expr],
    stages: list[tuple[str, str]],
    labels: dict[str, str],
    *,
    time_limit_s: float,
    seed: int,
    backend: str,
    cancel: threading.Event | None = None,
) -> StageOutcome:
    if backend == "cpsat":
        runner = _CpSat(model, seed)
    elif backend == "highs":
        runner = _Highs(model)
    else:
        raise ValueError(f"unknown backend {backend!r}")
    version = backend_version(backend)

    t0 = time.monotonic()
    deadline = t0 + time_limit_s
    incumbent: list[int] | None = None
    log: list[dict[str, Any]] = []
    for idx, (name, sense) in enumerate(stages):
        if cancel is not None and cancel.is_set():
            return StageOutcome("CANCELLED", None, log, "cancelled", backend, version)
        remaining = deadline - time.monotonic()
        if remaining <= 0.05:
            if incumbent is None:
                return StageOutcome("TIMED_OUT", None, log, "time limit", backend, version)
            log += _not_run(stages[idx:], labels)
            return StageOutcome("SOLVED", incumbent, log, "time limit reached before stage "
                                f"{name}", backend, version)
        e = exprs[name]
        status, x, bound = runner.solve(e, sense, remaining, incumbent)
        if status in ("OPTIMAL", "FEASIBLE"):
            assert x is not None
            incumbent = x
            val = e.value(x)
            entry: dict[str, Any] = {"stage": name, "sense": sense, "label": labels[name],
                                     "status": status, "value": val}
            if status == "OPTIMAL":
                log.append(entry)
                runner.fix(e, val)
                continue
            if bound is not None:
                entry["bound"] = bound
            log.append(entry)
            log += _not_run(stages[idx + 1:], labels)
            return StageOutcome("SOLVED", incumbent, log,
                                f"stage {name} returned FEASIBLE (not proven optimal)",
                                backend, version)
        if status == "INFEASIBLE" and incumbent is None:
            return StageOutcome("INFEASIBLE", None, log, "infeasible", backend, version)
        if status == "FAILED":
            return StageOutcome("FAILED", None, log, "solver error", backend, version)
        if incumbent is None:
            return StageOutcome("TIMED_OUT", None, log, f"stage {name}: {status}", backend,
                                version)
        log += _not_run(stages[idx:], labels)
        return StageOutcome("SOLVED", incumbent, log, f"stage {name} returned {status}",
                            backend, version)
    return StageOutcome("SOLVED", incumbent, log, None, backend, version)


class _CpSat:
    def __init__(self, lm: LinModel, seed: int):
        from ortools.sat.python import cp_model

        self.cp = cp_model
        self.m = cp_model.CpModel()
        self.v = [self.m.new_int_var(lb, ub, n) for n, lb, ub in zip(lm.names, lm.lb, lm.ub)]
        for coeffs, lo, hi in lm.rows:
            self._row(coeffs, lo, hi)
        self.s = cp_model.CpSolver()
        self.s.parameters.num_workers = 1
        self.s.parameters.random_seed = seed % 2_147_483_647

    def _lin(self, coeffs: Coeffs) -> Any:
        return sum(c * self.v[i] for i, c in coeffs.items())

    def _row(self, coeffs: Coeffs, lo: float, hi: float) -> None:
        if not coeffs:
            if lo > 0 or hi < 0:
                self.m.add_bool_or([])  # constant infeasible row
            return
        lo_i = -(2**62) if lo == -math.inf else int(math.ceil(lo))
        hi_i = 2**62 if hi == math.inf else int(math.floor(hi))
        self.m.add_linear_constraint(self._lin(coeffs), lo_i, hi_i)

    def solve(self, e: Expr, sense: str, remaining: float, hint: list[int] | None):
        self.m.clear_objective()
        obj = self._lin(e.coeffs) if e.coeffs else 0
        if sense == "max":
            self.m.maximize(obj)
        else:
            self.m.minimize(obj)
        self.m.clear_hints()
        if hint is not None:
            for var, val in zip(self.v, hint):
                self.m.add_hint(var, val)
        self.s.parameters.max_time_in_seconds = max(remaining, 0.05)
        st = self.s.solve(self.m)
        cp = self.cp
        if st in (cp.OPTIMAL, cp.FEASIBLE):
            x = [int(self.s.value(v)) for v in self.v]
            bound = None
            if st == cp.FEASIBLE:
                bound = int(round(self.s.best_objective_bound)) + e.const
            return ("OPTIMAL" if st == cp.OPTIMAL else "FEASIBLE"), x, bound
        if st == cp.INFEASIBLE:
            return "INFEASIBLE", None, None
        if st == cp.MODEL_INVALID:
            return "FAILED", None, None
        return "UNKNOWN", None, None

    def fix(self, e: Expr, val: int) -> None:
        self._row(e.coeffs, val - e.const, val - e.const)


class _Highs:
    def __init__(self, lm: LinModel):
        self.lm = lm
        self.rows = list(lm.rows)

    def solve(self, e: Expr, sense: str, remaining: float, hint: list[int] | None):
        import numpy as np
        from scipy.optimize import Bounds, LinearConstraint, milp
        from scipy.sparse import coo_matrix

        n = len(self.lm.names)
        c = np.zeros(n)
        for i, a in e.coeffs.items():
            c[i] = -a if sense == "max" else a
        rows, cols, data, lo, hi = [], [], [], [], []
        for r, (coeffs, rlo, rhi) in enumerate(self.rows):
            if not coeffs:
                if rlo > 0 or rhi < 0:
                    return "INFEASIBLE", None, None
                continue
            for i, a in coeffs.items():
                rows.append(len(lo))
                cols.append(i)
                data.append(a)
            lo.append(rlo)
            hi.append(rhi)
        cons = []
        if lo:
            a_mat = coo_matrix((data, (rows, cols)), shape=(len(lo), n)).tocsr()
            cons = [LinearConstraint(a_mat, np.array(lo, float), np.array(hi, float))]
        res = milp(
            c,
            constraints=cons,
            integrality=np.ones(n),
            bounds=Bounds(np.array(self.lm.lb, float), np.array(self.lm.ub, float)),
            options={"time_limit": max(remaining, 0.05), "mip_rel_gap": 0.0, "disp": False,
                     "presolve": True},
        )
        if res.x is not None and res.status in (0, 1):
            x = [int(round(v)) for v in res.x]
            return ("OPTIMAL" if res.status == 0 else "FEASIBLE"), x, None
        if res.status == 2:
            return "INFEASIBLE", None, None
        if res.status == 1:
            return "UNKNOWN", None, None
        return "FAILED", None, None

    def fix(self, e: Expr, val: int) -> None:
        self.rows.append((dict(e.coeffs), val - e.const, val - e.const))
