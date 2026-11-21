"""SQLite persistence (SRS §8.2). JSON columns; results immutable once terminal."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT", "NO_SOLUTION", "INTERRUPTED",
            "INVALID"}

DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS dataset_versions (
  id TEXT PRIMARY KEY, district TEXT NOT NULL, version TEXT NOT NULL,
  sha256 TEXT NOT NULL UNIQUE, manifest_json TEXT NOT NULL, payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scenarios (
  id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES dataset_versions(id),
  plan_json TEXT NOT NULL, plan_hash TEXT NOT NULL, status TEXT NOT NULL,
  confirmed_at TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL REFERENCES scenarios(id), kind TEXT NOT NULL,
  status TEXT NOT NULL, stage TEXT, job_key TEXT, request_hash TEXT, solver_version TEXT,
  result_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS ix_runs_scenario ON runs(scenario_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_runs_job_key ON runs(job_key) WHERE job_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS stress_runs (
  id TEXT PRIMARY KEY, baseline_run_id TEXT NOT NULL REFERENCES runs(id),
  alternative_run_id TEXT NOT NULL REFERENCES runs(id), seed INTEGER NOT NULL,
  case_count INTEGER NOT NULL, status TEXT NOT NULL, results_json TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS event_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
  event TEXT NOT NULL, timestamp TEXT NOT NULL, actor_label TEXT NOT NULL,
  safe_metadata_json TEXT);
"""


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(DDL)
        with self._lock:
            row = self.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row is None:
                self.db.execute("INSERT INTO meta VALUES ('schema_version', ?)",
                                (str(SCHEMA_VERSION),))
            elif int(row["value"]) != SCHEMA_VERSION:
                raise RuntimeError("database schema version mismatch; back up and migrate")

    # -- helpers -------------------------------------------------------------
    def _tx(self, sql: str, args: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self._lock:
            self.db.execute("BEGIN")
            try:
                cur = self.db.execute(sql, args)
                self.db.execute("COMMIT")
                return cur
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    def event(self, entity_type: str, entity_id: str, event: str,
              meta: dict[str, Any] | None = None) -> None:
        self._tx("INSERT INTO event_log(entity_type, entity_id, event, timestamp, actor_label, "
                 "safe_metadata_json) VALUES (?,?,?,?,?,?)",
                 (entity_type, entity_id, event, now(), "planner (demo)",
                  json.dumps(meta or {})))

    # -- datasets ------------------------------------------------------------
    def upsert_dataset(self, ds_json: dict[str, Any]) -> None:
        m = ds_json["manifest"]
        with self._lock:
            row = self.db.execute("SELECT sha256 FROM dataset_versions WHERE id=?",
                                  (m["id"],)).fetchone()
            if row is not None:
                if row["sha256"] != m["sha256"]:
                    raise RuntimeError(f"dataset {m['id']} already stored with a different hash; "
                                       "datasets are immutable (use a new version id)")
                return
            self._tx("INSERT INTO dataset_versions VALUES (?,?,?,?,?,?,?)",
                     (m["id"], m["district_label"], m["version"], m["sha256"],
                      json.dumps(m), json.dumps(ds_json), now()))

    # -- scenarios -----------------------------------------------------------
    def create_scenario(self, sid: str, dataset_id: str, plan: dict[str, Any],
                        plan_hash: str) -> None:
        self._tx("INSERT INTO scenarios VALUES (?,?,?,?,?,?,?)",
                 (sid, dataset_id, json.dumps(plan), plan_hash, "VALIDATED", None, now()))
        self.event("scenario", sid, "VALIDATED", {"plan_hash": plan_hash})

    def get_scenario(self, sid: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT * FROM scenarios WHERE id=?", (sid,)).fetchone()
        if row is None:
            return None
        return {"scenario_id": row["id"], "dataset_id": row["dataset_id"],
                "plan": json.loads(row["plan_json"]), "plan_hash": row["plan_hash"],
                "status": row["status"], "confirmed_at": row["confirmed_at"],
                "created_at": row["created_at"]}

    def confirm_scenario(self, sid: str) -> None:
        self._tx("UPDATE scenarios SET status='CONFIRMED', confirmed_at=? WHERE id=?",
                 (now(), sid))
        self.event("scenario", sid, "CONFIRMED")

    # -- runs ----------------------------------------------------------------
    def create_run(self, rid: str, scenario_id: str, kind: str, job_key: str | None,
                   request_hash: str) -> None:
        t = now()
        self._tx("INSERT INTO runs(id, scenario_id, kind, status, stage, job_key, request_hash, "
                 "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                 (rid, scenario_id, kind, "QUEUED", "queued", job_key, request_hash, t, t))
        self.event("run", rid, "QUEUED", {"kind": kind})

    def run_by_job_key(self, key: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT id, request_hash FROM runs WHERE job_key=?",
                              (key,)).fetchone()
        return dict(row) if row else None

    def set_run_status(self, rid: str, status: str, stage: str | None = None) -> None:
        with self._lock:
            row = self.db.execute("SELECT status FROM runs WHERE id=?", (rid,)).fetchone()
            if row is None or row["status"] in TERMINAL:
                return  # terminal results are immutable
            self._tx("UPDATE runs SET status=?, stage=?, updated_at=? WHERE id=?",
                     (status, stage, now(), rid))

    def finish_run(self, rid: str, record: dict[str, Any]) -> None:
        with self._lock:
            row = self.db.execute("SELECT status FROM runs WHERE id=?", (rid,)).fetchone()
            if row is None or row["status"] in TERMINAL:
                return
            self._tx("UPDATE runs SET status=?, stage=?, solver_version=?, result_json=?, "
                     "updated_at=? WHERE id=?",
                     (record["status"], "done", (record.get("engine") or {}).get("solver_version"),
                      json.dumps(record), now(), rid))
        self.event("run", rid, record["status"])

    def get_run(self, rid: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
        if row is None:
            return None
        out = {"run_id": row["id"], "scenario_id": row["scenario_id"], "kind": row["kind"],
               "status": row["status"], "stage": row["stage"], "created_at": row["created_at"],
               "updated_at": row["updated_at"]}
        if row["result_json"]:
            out.update(json.loads(row["result_json"]))
            out["status"] = row["status"]
        return out

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT id, scenario_id, kind, status, created_at FROM runs ORDER BY created_at DESC, "
            "rowid DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def active_jobs(self) -> int:
        row = self.db.execute("SELECT COUNT(*) AS n FROM runs WHERE status IN "
                              "('QUEUED','RUNNING','AUDITING')").fetchone()
        srow = self.db.execute("SELECT COUNT(*) AS n FROM stress_runs WHERE status IN "
                               "('QUEUED','RUNNING')").fetchone()
        return int(row["n"]) + int(srow["n"])

    def interrupt_unfinished(self) -> int:
        """On restart, unfinished jobs become INTERRUPTED, never falsely completed."""
        t = now()
        c1 = self._tx("UPDATE runs SET status='INTERRUPTED', stage='interrupted', updated_at=? "
                      "WHERE status IN ('QUEUED','RUNNING','AUDITING')", (t,)).rowcount
        c2 = self._tx("UPDATE stress_runs SET status='INTERRUPTED', updated_at=? "
                      "WHERE status IN ('QUEUED','RUNNING')", (t,)).rowcount
        return c1 + c2

    # -- stress --------------------------------------------------------------
    def create_stress(self, sid: str, base: str, alt: str, seed: int, count: int) -> None:
        t = now()
        self._tx("INSERT INTO stress_runs VALUES (?,?,?,?,?,?,?,?,?)",
                 (sid, base, alt, seed, count, "QUEUED", None, t, t))

    def set_stress(self, sid: str, status: str, results: dict[str, Any] | None = None) -> None:
        with self._lock:
            row = self.db.execute("SELECT status FROM stress_runs WHERE id=?", (sid,)).fetchone()
            if row is None or row["status"] in TERMINAL:
                return
            self._tx("UPDATE stress_runs SET status=?, results_json=?, updated_at=? WHERE id=?",
                     (status, json.dumps(results) if results is not None else None, now(), sid))

    def get_stress(self, sid: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT * FROM stress_runs WHERE id=?", (sid,)).fetchone()
        if row is None:
            return None
        out = {"stress_run_id": row["id"], "baseline_run_id": row["baseline_run_id"],
               "alternative_run_id": row["alternative_run_id"], "seed": row["seed"],
               "case_count": row["case_count"], "status": row["status"],
               "created_at": row["created_at"]}
        if row["results_json"]:
            out["results"] = json.loads(row["results_json"])
        return out
