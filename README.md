# CIVITWIN AI — synthetic planning sandbox (hackathon MVP)

> **SYNTHETIC DEMONSTRATION.** Every number in this app comes from fictional data for
> "Bajaur — synthetic planning sandbox". It is advisory decision support only: not medical
> advice, not an approved allocation, not a statement about real district services.

CIVITWIN turns a planning question (English or Urdu) into a structured plan, the planner
confirms the exact plan, and an optimization solver finds the allocation of new health units
that maximises access within a travel-time threshold under budget, unit and capacity limits.
**The solver decides, an independent audit verifies every number, and the explanation is
filled from the audited result.** No language model computes or writes any number.

Specification: [docs/SRS.md](docs/SRS.md) · Design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ·
Status and requirement checklist: [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md)

## GitHub Pages demo

[Open the public CIVITWIN demo](https://ahmadalihamza.github.io/CIVI-TWIN/). It shows a fixed,
synthetic scenario with audited baseline, greedy and optimized runs, 20 stress cases, and
HTML/JSON/CSV reports. GitHub Actions regenerates the demo from the real solver and verifier.
Use the local FastAPI app to edit assumptions, run scenarios and save a history.

Preview the same static build locally after setup with `python scripts/build_pages.py dist/pages`
and `python -m http.server 8002 --bind 127.0.0.1 --directory dist/pages`.

## Quick start (Linux / macOS)

Requires Python 3.11+ (verified on 3.14.10). Works offline once dependencies are installed.

```bash
make setup      # venv + dependencies (see requirements.lock.txt)
make seed       # optional: writes data/demo, data/fixtures, data/schemas
make dev        # http://127.0.0.1:8000  (UI + API; API docs at /api/docs)
```

In a second terminal:

```bash
make test       # 95 tests, both solver backends if installed
make smoke      # end-to-end check against the running server
make benchmark  # timings + baseline/greedy/solver grid -> docs/benchmark/
```

Without Make: `.venv/bin/python -m civitwin_api`, `.venv/bin/python -m pytest -q`,
`.venv/bin/python scripts/smoke.py`, `.venv/bin/python scripts/benchmark.py`.

### Windows (PowerShell)

Use Python 3.14 with the locked dependency set. These commands create a Windows environment
in `.venv-win`, which can coexist with a copied Linux `.venv`.

```powershell
py -3.14 -m venv .venv-win
.venv-win\Scripts\python -m pip install -r requirements.lock.txt
.venv-win\Scripts\python -m pip install --no-deps -e .
.venv-win\Scripts\python -m civitwin_api
```

If port 8000 is in use, set `$env:API_PORT = '8001'` before launching. If Python 3.14 was
installed through `uv`, use `uv venv --python 3.14 .venv-win` and `uv pip install --python
.venv-win/Scripts/python.exe -r requirements.lock.txt -e .` for setup. With the API running,
open the localhost address printed by Uvicorn and use a second terminal for verification.

```powershell
.venv-win\Scripts\python -m pytest -q
.venv-win\Scripts\python scripts/smoke.py --url http://127.0.0.1:8000
```

### Solver backends

* **OR-Tools CP-SAT** (preferred, SRS §3.2) — used automatically when `ortools` is installed.
* **HiGHS via SciPy** (fallback) — used when OR-Tools is missing. `mip_rel_gap = 0`, so
  "OPTIMAL" still means proven optimal.

Force one with `CIVITWIN_SOLVER=cpsat` or `CIVITWIN_SOLVER=highs`. The backend and version are
recorded in every result, export and benchmark. Both backends give identical objective values
on the checked scenarios, and the test suite runs on both.

## Interface

Dark theme by default (sun/moon button switches to light). The coverage map and the stress results have
rotatable **3D views** (drag to rotate, double-click to reset, buttons for auto-rotate, labels and zoom);
the coverage map also has a 2D view. Exact numbers are always in tooltips, 2D charts and data tables.
Animations respect the operating system's *reduce motion* setting, and 3D scenes pause when off screen.

## 3-minute demo script

1. **Overview** — problem, the synthetic-data badge, dataset tiles (24 clusters, 5 existing
   sites, 8 candidate zones, 7 eligible) and the latest result.
2. **Scenario builder** — click the Urdu example `بجٹ ۳ لاکھ روپے، دو نئے مراکز، ۴۵ منٹ`.
   The offline parser shows what it understood and which defaults it used. In the
   **Plan summary** panel choose **Review plan**, point at the plan hash, then **Confirm & run**.
   The stepper and run cards show Queued → Solving → Auditing → Done.
3. **Comparison** — headline coverage figure, KPI tiles (baseline and greedy for reference),
   coverage map (hover anything), coverage-by-cluster chart, Urdu/English explanation and the
   12-check audit panel.
4. **What if?** — move the budget slider, review, confirm: results update in a few seconds.
5. **Equity** — in the builder set equity floor 10%: the run is reported **infeasible**
   with a diagnostic ("needs at least 5 new units, PKR 590,000/week"). Then click the example
   "Every cluster at least 10%, 7 lakh budget, 5 new units" to see a feasible plan where every
   cluster is served. Nothing is relaxed automatically.
   Scroll down for **Why these sites?** (what each new site does and what is lost without it),
   **Community journeys** (travel time before → after, and who is still far from care),
   the **Budget trade-off** curve (what each extra lakh buys) and the **Planner's review**
   (the human decision, printed in the report).
6. **Stress lab** — 20 fixed-seed cases (demand ×80–130%, travel ×90–140%) with
   scenario ranges and failure counts.
7. **Report** — printable report and JSON/CSV exports with dataset, plan and result hashes.

Results on this machine for the default plan (PKR 300,000/week, 2 units, 45 min) are in
[docs/benchmark/benchmark-cpsat.md](docs/benchmark/benchmark-cpsat.md): within-threshold
coverage 48.6% (baseline) → 73.1% (greedy) → 74.7% (optimized, N04 + N07). These are
modeled visits on synthetic data, not causal or real-world improvements.

## Layout

```text
services/api/civitwin_engine/   pure-Python engine (no web/DB/AI imports)
  dataset/ travel.py optimizer/ audit.py metrics.py greedy.py stress.py
  parser.py evidence.py export.py compare.py run.py planspec.py
services/api/civitwin_api/      FastAPI app, SQLite store, job executor
services/api/tests/             unit + integration tests (pytest)
apps/web/                       offline dashboard (HTML/CSS/JS, no CDN, no build step)
data/{demo,fixtures,schemas}/   generated synthetic data and JSON schemas
scripts/                        seed, benchmark, smoke, reset_demo
docs/                           SRS, architecture, status, benchmark reports
```

## Limitations (read before presenting)

* Synthetic data only; schematic network, not real roads or terrain.
* Demand is modeled visits per week, not people; costs are illustrative weekly PKR.
* The baseline is a modeled baseline, not observed practice.
* Fairness metrics reflect the chosen policy; they do not guarantee fairness.
* No language model is connected (AI model disabled). Natural-language input uses an
  offline rule-based English/Urdu parser. Urdu text needs review by a fluent speaker.
* Local single-user demo: no authentication. Binds to 127.0.0.1 only. Do not expose publicly.

Full list of what is and is not done: [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md).

## Reset the demo

`make reset-demo` (asks you to type RESET, keeps a backup of `data/civitwin.db`).
If the synthetic generator changes, reset is required because stored datasets are immutable.
# CIVI-TWIN
# Civi-Twin
