"""FastAPI app: REST contract (SRS §8.1), bounded job executor, offline web UI.

Run locally:  python -m civitwin_api   (binds 127.0.0.1 by default)
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from civitwin_engine.analysis import coordination, site_impact, tradeoff_curve
from civitwin_engine.compare import IncompatibleComparison, compare_runs
from civitwin_engine.dataset.generator import generate_demo_dataset
from civitwin_engine.dataset.schema import Dataset
from civitwin_engine.dataset.validation import DatasetValidationError, validate_dataset
from civitwin_engine.evidence import build_packet, explain_comparison, explain_run
from civitwin_engine.export import export_csv, export_html, export_json
from civitwin_engine.greedy import execute_greedy
from civitwin_engine.hashing import sha256_of
from civitwin_engine.optimizer.linmodel import available_backends, backend_version, default_backend
from civitwin_engine.optimizer.problem import ProblemError, build_problem
from civitwin_engine.parser import parse_request
from civitwin_engine.planspec import PlanSpec
from civitwin_engine.run import MODEL_VERSION, SYNTHETIC_WARNING, execute_run
from civitwin_engine.stress import MAX_CASES, run_stress
from civitwin_engine.travel import TravelMatrix, travel_matrix

from .store import TERMINAL, Store

ROOT = Path(__file__).resolve().parents[3]
WEB_DIR = ROOT / "apps" / "web"
DB_PATH = os.environ.get("CIVITWIN_DB", str(ROOT / "data" / "civitwin.db"))
SOLVER_TIMEOUT = float(os.environ.get("SOLVER_TIMEOUT_SECONDS", "10"))
STRESS_TIMEOUT = float(os.environ.get("STRESS_TIMEOUT_SECONDS", "150"))
REAL_DIR = ROOT / "data" / "real"
REAL_FILES = [("bajaur_real_walk_v1.json", "bajaur_geo_walk.json"), ("bajaur_real_v1.json", "bajaur_geo.json")]
DEFAULT_PLANS = {
    "demo-bajaur-v1": {"budget_pkr": 300_000, "max_new_units": 2, "threshold_minutes": 45},
    "bajaur-real-walk-v1": {"budget_pkr": 600_000, "max_new_units": 6, "threshold_minutes": 60},
    "bajaur-real-v1": {"budget_pkr": 600_000, "max_new_units": 6, "threshold_minutes": 30},
}
AI_ENABLED = os.environ.get("AI_ENABLED", "false").lower() == "true"
MAX_QUEUED = 5
MAX_UPLOAD_BYTES = 2 * 1024 * 1024


# -- request bodies (module level so FastAPI can resolve annotations) ------
class ParseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=2000)
    dataset_version_id: str = "demo-bajaur-v1"

class ScenarioBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan: dict[str, Any]

class ConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_hash: str

class RunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["baseline", "optimized", "greedy"]
    plan_hash: str

class CompareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_run_id: str
    alt_run_id: str
    lang: Literal["en", "ur"] = "en"

class StressBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_run_id: str
    alt_run_id: str
    seed: int = Field(default=2026, ge=0, le=2_147_483_647)
    count: int = Field(default=20, ge=1, le=MAX_CASES)
    coverage_target_pct: float | None = Field(default=None, ge=0, le=100)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str,
                 field_errors: list[dict[str, Any]] | None = None):
        self.status, self.code, self.message = status, code, message
        self.field_errors = field_errors or []


class State:
    def __init__(self, db_path: str, *, load_real: bool = True):
        self.store = Store(db_path)
        self.interrupted_on_start = self.store.interrupt_unfinished()
        self.datasets: dict[str, tuple[Dataset, TravelMatrix]] = {}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="civitwin-job")
        self.cancel: dict[str, threading.Event] = {}
        self.backend = default_backend()
        self.analysis_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self.geo: dict[str, Path] = {}
        for data_file, geo_file in REAL_FILES if load_real else ():
            if (REAL_DIR / data_file).exists():
                ds = validate_dataset(json.loads((REAL_DIR / data_file).read_text(encoding="utf-8")))
                self.add_dataset(ds)
                if (REAL_DIR / geo_file).exists():
                    self.geo[ds.manifest.id] = REAL_DIR / geo_file
        self.add_dataset(generate_demo_dataset())

    def add_dataset(self, ds: Dataset) -> None:
        self.store.upsert_dataset(ds.model_dump(mode="json"))
        self.datasets[ds.manifest.id] = (ds, travel_matrix(ds))

    def dataset(self, did: str) -> tuple[Dataset, TravelMatrix]:
        if did not in self.datasets:
            raise ApiError(404, "dataset_not_found", f"dataset {did!r} not found")
        return self.datasets[did]


def create_app(db_path: str | None = None, *, load_real: bool = True) -> FastAPI:
    app = FastAPI(title="CIVITWIN AI", version=MODEL_VERSION,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    state = State(db_path or DB_PATH, load_real=load_real)
    app.state.civitwin = state

    # -- error envelope ------------------------------------------------------
    def envelope(request: Request, status: int, code: str, message: str,
                 field_errors: list[dict[str, Any]] | None = None) -> JSONResponse:
        rid = getattr(request.state, "request_id", None)
        return JSONResponse(status_code=status, content={
            "code": code, "message": message, "field_errors": field_errors or [],
            "request_id": rid})

    @app.middleware("http")
    async def request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = uuid.uuid4().hex[:12]
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > MAX_UPLOAD_BYTES:
            return envelope(request, 413, "payload_too_large", "Request body exceeds 2 MB.")
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        if not request.url.path.startswith("/api/"):
            # UI assets: always revalidate (ETag) so an updated UI never mixes with a cached one.
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError) -> JSONResponse:
        return envelope(request, exc.status, exc.code, exc.message, exc.field_errors)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        fe = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]}
              for e in exc.errors()]
        malformed = any(e["type"] == "json_invalid" for e in exc.errors())
        return envelope(request, 400 if malformed else 422,
                        "malformed_request" if malformed else "invalid_request",
                        "Request body is not valid JSON." if malformed
                        else "Request failed validation.", fe)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return envelope(request, exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        return envelope(request, 500, "internal_error", "Unexpected server error.")

    api = "/api/v1"

    # -- health --------------------------------------------------------------
    @app.get(f"{api}/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(f"{api}/ready")
    def ready() -> dict[str, Any]:
        state.store.db.execute("SELECT 1").fetchone()
        return {"status": "ready", "datasets": sorted(state.datasets),
                "solver_backends": available_backends(), "solver_in_use": state.backend}

    @app.get(f"{api}/system")
    def system() -> dict[str, Any]:
        return {
            "model_version": MODEL_VERSION,
            "demo_mode": True,
            "solver_backend": state.backend,
            "solver_version": backend_version(state.backend),
            "available_backends": available_backends(),
            "ai_model_enabled": AI_ENABLED,
            "parser": "offline rule-based (English/Urdu)",
            "solver_timeout_s": SOLVER_TIMEOUT,
            "stress_timeout_s": STRESS_TIMEOUT,
            "interrupted_on_start": state.interrupted_on_start,
            "warning": SYNTHETIC_WARNING,
        }

    # -- datasets ------------------------------------------------------------
    @app.get(f"{api}/datasets")
    def list_datasets() -> list[dict[str, Any]]:
        out = []
        for did, (ds, _) in state.datasets.items():
            m = ds.manifest.model_dump(mode="json")
            m["default_plan"] = DEFAULT_PLANS.get(did, {"budget_pkr": 300_000, "max_new_units": 2, "threshold_minutes": 45})
            m["has_map"] = did in state.geo
            m["travel_mode"] = "foot" if "walk" in did else ("car" if did in state.geo else "schematic")
            out.append(m)
        return out

    def _geo(did: str) -> dict[str, Any]:
        state.dataset(did)
        if did not in state.geo:
            raise ApiError(404, "no_map", f"dataset {did!r} has no real map layers")
        return json.loads(state.geo[did].read_text(encoding="utf-8"))

    @app.get(f"{api}/datasets/{{did}}/geo")
    def dataset_geo(did: str) -> dict[str, Any]:
        return _geo(did)

    @app.get(f"{api}/datasets/{{did}}")
    def get_dataset(did: str) -> dict[str, Any]:
        ds, tm = state.dataset(did)
        out = ds.model_dump(mode="json")
        mins = tm.minutes()
        cids = [c.id for c in ds.communities]
        sids = [s.id for s in ds.sites]
        out["travel"] = {
            "minutes": [{"community_id": c, "site_id": s, "minutes": mins[(c, s)]}
                        for c in cids for s in sids if (c, s) in mins],
            "unreachable_pairs": len(tm.unreachable(cids, sids)),
            "method": ("Dijkstra shortest path on schematic network; rounded half-up once" if ds.manifest.is_synthetic
                       else "OSRM travel time on OpenStreetMap routes plus walk to the network; rounded half-up once"),
        }
        out["validation_warnings"] = [
            f"Community {c} cannot reach any site." for c in cids
            if not any((c, s) in mins for s in sids)]
        return out

    @app.post(f"{api}/datasets/import", status_code=201)
    async def import_dataset(request: Request) -> dict[str, Any]:
        body = await request.body()
        if len(body) > MAX_UPLOAD_BYTES:
            raise ApiError(413, "payload_too_large", "Dataset exceeds 2 MB.")
        try:
            raw = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ApiError(400, "malformed_request", "Dataset must be a JSON document.") from None
        if not isinstance(raw, dict):
            raise ApiError(422, "invalid_dataset", "Dataset must be a JSON object.")
        try:
            ds = validate_dataset(raw)
        except DatasetValidationError as exc:
            raise ApiError(422, "invalid_dataset", "Import rejected; nothing was stored.",
                           exc.errors) from None
        if ds.manifest.id in state.datasets:
            raise ApiError(409, "dataset_exists", "Dataset id already exists; datasets are "
                           "immutable, use a new id or version.")
        state.add_dataset(ds)
        return ds.manifest.model_dump(mode="json")

    # -- plans and scenarios ---------------------------------------------------
    @app.post(f"{api}/plans/parse")
    def parse_plan(body: ParseBody) -> dict[str, Any]:
        state.dataset(body.dataset_version_id)
        out = parse_request(body.text, body.dataset_version_id)
        out["ai_model_used"] = False
        return out

    def _validated_plan(raw: dict[str, Any]) -> PlanSpec:
        try:
            plan = PlanSpec.model_validate(raw)
        except ValidationError as exc:
            raise ApiError(422, "invalid_plan", "Plan failed validation.", [
                {"field": ".".join(str(p) for p in e["loc"]) or "plan", "message": e["msg"]}
                for e in exc.errors()]) from None
        ds, tm = state.dataset(plan.dataset_version_id)
        try:
            build_problem(ds, tm, plan)
        except ProblemError as exc:
            raise ApiError(422, "invalid_plan", str(exc)) from None
        return plan

    @app.post(f"{api}/scenarios", status_code=201)
    def create_scenario(body: ScenarioBody) -> dict[str, Any]:
        plan = _validated_plan(body.plan)
        sid = f"scn-{uuid.uuid4().hex[:10]}"
        state.store.create_scenario(sid, plan.dataset_version_id, plan.model_dump(mode="json"),
                                    plan.plan_hash())
        return state.store.get_scenario(sid)  # type: ignore[return-value]

    @app.get(f"{api}/scenarios/{{sid}}")
    def get_scenario(sid: str) -> dict[str, Any]:
        scn = state.store.get_scenario(sid)
        if scn is None:
            raise ApiError(404, "scenario_not_found", f"scenario {sid!r} not found")
        return scn

    @app.post(f"{api}/scenarios/{{sid}}/confirm")
    def confirm(sid: str, body: ConfirmBody) -> dict[str, Any]:
        scn = get_scenario(sid)
        if body.plan_hash != scn["plan_hash"]:
            raise ApiError(409, "plan_hash_mismatch", "The plan changed since it was reviewed. "
                           "Review the current plan and confirm again.")
        if scn["status"] != "CONFIRMED":
            state.store.confirm_scenario(sid)
        return get_scenario(sid)

    # -- runs ----------------------------------------------------------------
    def _run_job(rid: str, scn: dict[str, Any], kind: str, cancel: threading.Event) -> None:
        store = state.store
        try:
            if cancel.is_set():
                store.finish_run(rid, {"run_id": rid, "kind": kind, "status": "CANCELLED",
                                       "solver_status": "CANCELLED"})
                return
            store.set_run_status(rid, "RUNNING", "solving")
            plan = PlanSpec.model_validate(scn["plan"])
            ds, tm = state.dataset(plan.dataset_version_id)
            p = build_problem(ds, tm, plan)

            def on_stage(stage: str) -> None:
                store.set_run_status(rid, "AUDITING" if stage == "auditing" else "RUNNING", stage)

            if kind == "greedy":
                rec = execute_greedy(p, backend=state.backend, time_limit_s=SOLVER_TIMEOUT,
                                     scenario_id=scn["scenario_id"])
            else:
                rec = execute_run(p, kind, time_limit_s=SOLVER_TIMEOUT, backend=state.backend,
                                  cancel=cancel, scenario_id=scn["scenario_id"],
                                  on_stage=on_stage)
            rec["run_id"] = rid
            store.finish_run(rid, rec)
        except Exception as exc:  # never publish partial results
            store.finish_run(rid, {"run_id": rid, "kind": kind, "status": "FAILED",
                                   "solver_status": "ERROR",
                                   "error": {"reason": f"{type(exc).__name__}: run failed",
                                             "hints": []}})
        finally:
            state.cancel.pop(rid, None)

    @app.post(f"{api}/scenarios/{{sid}}/runs", status_code=202)
    def submit_run(sid: str, body: RunBody,
                   idempotency_key: str | None = Header(default=None)) -> dict[str, Any]:
        scn = get_scenario(sid)
        if scn["status"] != "CONFIRMED":
            raise ApiError(409, "not_confirmed", "Confirm the plan before running it.")
        if body.plan_hash != scn["plan_hash"]:
            raise ApiError(409, "plan_hash_mismatch", "Plan hash does not match the confirmed "
                           "plan.")
        req_hash = sha256_of({"scenario": sid, **body.model_dump()})
        if idempotency_key:
            prior = state.store.run_by_job_key(idempotency_key)
            if prior:
                if prior["request_hash"] != req_hash:
                    raise ApiError(409, "idempotency_conflict", "Idempotency-Key was already "
                                   "used with a different request.")
                return state.store.get_run(prior["id"])  # type: ignore[return-value]
        if state.store.active_jobs() > MAX_QUEUED:
            raise ApiError(429, "job_limit", "Too many queued jobs; wait for one to finish.")
        rid = f"run-{uuid.uuid4().hex[:10]}"
        state.store.create_run(rid, sid, body.kind, idempotency_key, req_hash)
        ev = threading.Event()
        state.cancel[rid] = ev
        state.executor.submit(_run_job, rid, scn, body.kind, ev)
        return state.store.get_run(rid)  # type: ignore[return-value]

    @app.get(f"{api}/runs")
    def list_runs(limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
        return state.store.list_runs(limit)

    @app.get(f"{api}/runs/{{rid}}")
    def get_run(rid: str) -> dict[str, Any]:
        run = state.store.get_run(rid)
        if run is None:
            raise ApiError(404, "run_not_found", f"run {rid!r} not found")
        return run

    @app.post(f"{api}/runs/{{rid}}/cancel")
    def cancel_run(rid: str) -> dict[str, Any]:
        run = get_run(rid)
        if run["status"] in TERMINAL:
            raise ApiError(409, "already_terminal", f"run is already {run['status']}")
        ev = state.cancel.get(rid)
        if ev is not None:
            ev.set()
        return {"run_id": rid, "cancel_requested": True}

    def _completed(rid: str) -> dict[str, Any]:
        run = get_run(rid)
        if run["status"] != "COMPLETED":
            raise ApiError(409, "not_completed", f"run {rid} is {run['status']}, not COMPLETED")
        return run

    def _manifest(run: dict[str, Any]) -> dict[str, Any]:
        ds, _ = state.dataset(run["plan"]["dataset_version_id"])
        return ds.manifest.model_dump(mode="json")

    @app.get(f"{api}/runs/{{rid}}/explanation")
    def explanation(rid: str, lang: Literal["en", "ur"] = "en") -> dict[str, Any]:
        run = _completed(rid)
        packet = build_packet(run, _manifest(run))
        return {"packet": packet, "explanation": explain_run(packet, lang),
                "ai_model_used": False}

    @app.get(f"{api}/runs/{{rid}}/export")
    def export(rid: str, format: Literal["json", "csv", "html"] = "json",
               compare_to: str | None = None) -> Response:
        run = get_run(rid)
        if run["status"] not in TERMINAL:
            raise ApiError(409, "not_terminal", "Run has not finished.")
        manifest = _manifest(run)
        if format == "json":
            return Response(export_json(run, manifest), media_type="application/json",
                            headers={"Content-Disposition":
                                     f'attachment; filename="{rid}.json"'})
        if format == "csv":
            return PlainTextResponse(export_csv(run, manifest), media_type="text/csv",
                                     headers={"Content-Disposition":
                                              f'attachment; filename="{rid}.csv"'})
        lines = None
        if compare_to and run["status"] == "COMPLETED":
            base = get_run(compare_to)
            try:
                lines = explain_comparison(compare_runs(base, run), base, run, "en")
            except IncompatibleComparison:
                lines = None
        return HTMLResponse(export_html(run, manifest, lines))

    # -- decision-support analyses (serialized through the single job worker) ---
    def _analysis(kind: str, rid: str, fn) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        run = _completed(rid)
        key = (kind, run["plan_hash"] if kind == "tradeoff" else rid)
        if key not in state.analysis_cache:
            if state.store.active_jobs() > MAX_QUEUED:
                raise ApiError(429, "job_limit", "Too many queued jobs; wait for one to finish.")
            plan = PlanSpec.model_validate(run["plan"])
            ds, tm = state.dataset(plan.dataset_version_id)
            try:
                state.analysis_cache[key] = state.executor.submit(fn, ds, tm, plan, run).result(timeout=120)
            except ValueError as exc:
                raise ApiError(409, "analysis_not_possible", str(exc)) from None
        return state.analysis_cache[key]

    @app.post(f"{api}/runs/{{rid}}/tradeoff")
    def tradeoff(rid: str) -> dict[str, Any]:
        return _analysis("tradeoff", rid, lambda ds, tm, plan, run: tradeoff_curve(
            ds, tm, plan, backend=state.backend, time_limit_s=STRESS_TIMEOUT))

    @app.get(f"{api}/runs/{{rid}}/coordination")
    def coordinate(rid: str, base_run_id: str | None = None) -> dict[str, Any]:
        run = _completed(rid)
        did = run["plan"]["dataset_version_id"]
        base = get_run(base_run_id) if base_run_id else None
        if base and base.get("plan_hash") != run["plan_hash"]:
            raise ApiError(409, "incompatible_runs", "Baseline must belong to the same confirmed plan.")
        return coordination(run, _geo(did), base)

    @app.get(f"{api}/runs/{{rid}}/site-impact")
    def impact(rid: str) -> dict[str, Any]:
        return _analysis("impact", rid, lambda ds, tm, plan, run: site_impact(
            ds, tm, plan, run, backend=state.backend))

    # -- comparisons ---------------------------------------------------------
    @app.post(f"{api}/comparisons")
    def comparison(body: CompareBody) -> dict[str, Any]:
        base, alt = get_run(body.base_run_id), get_run(body.alt_run_id)
        try:
            cmp = compare_runs(base, alt)
        except IncompatibleComparison as exc:
            raise ApiError(409, "incompatible_comparison", str(exc)) from None
        cmp["explanation"] = explain_comparison(cmp, base, alt, body.lang)
        return cmp

    # -- stress --------------------------------------------------------------
    def _stress_job(sid: str, body: StressBody, base: dict[str, Any],
                    alt: dict[str, Any]) -> None:
        try:
            state.store.set_stress(sid, "RUNNING")
            plan = PlanSpec.model_validate(base["plan"])
            ds, tm = state.dataset(plan.dataset_version_id)
            res = run_stress(ds, tm, plan, base, alt, seed=body.seed, count=body.count,
                             time_limit_s=STRESS_TIMEOUT, backend=state.backend,
                             coverage_target_pct=body.coverage_target_pct)
            state.store.set_stress(sid, "TIMED_OUT" if res["timed_out"] else "COMPLETED", res)
        except Exception as exc:
            state.store.set_stress(sid, "FAILED", {"error": f"{type(exc).__name__}"})

    @app.post(f"{api}/stress-runs", status_code=202)
    def submit_stress(body: StressBody) -> dict[str, Any]:
        base, alt = _completed(body.base_run_id), _completed(body.alt_run_id)
        if base["plan_hash"] != alt["plan_hash"] or base["dataset_sha256"] != alt["dataset_sha256"]:
            raise ApiError(409, "incompatible_runs", "Stress tests need two runs of the same "
                           "confirmed plan and dataset.")
        if state.store.active_jobs() > MAX_QUEUED:
            raise ApiError(429, "job_limit", "Too many queued jobs; wait for one to finish.")
        sid = f"str-{uuid.uuid4().hex[:10]}"
        state.store.create_stress(sid, base["run_id"], alt["run_id"], body.seed, body.count)
        state.executor.submit(_stress_job, sid, body, base, alt)
        return state.store.get_stress(sid)  # type: ignore[return-value]

    @app.get(f"{api}/stress-runs/{{sid}}")
    def get_stress(sid: str) -> dict[str, Any]:
        out = state.store.get_stress(sid)
        if out is None:
            raise ApiError(404, "stress_run_not_found", f"stress run {sid!r} not found")
        return out

    # -- offline web UI ------------------------------------------------------
    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

    return app


def main() -> None:
    import uvicorn

    host = os.environ.get("API_HOST", "127.0.0.1")
    port = int(os.environ.get("API_PORT", "8000"))
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
