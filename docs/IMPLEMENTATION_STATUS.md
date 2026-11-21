# Implementation status

## Local startup and GitHub Pages release (2026-11-21)

- The local app started on `127.0.0.1:8001` using a fresh `data/civitwin-local.db`. Port 8000 already had a listener. The local checkout retained its optional real-data inputs.
- The public build uses an isolated in-memory database and a synthetic dataset. It regenerates baseline, greedy, optimization, explanations, stress cases and downloads from the API, solver and audit. GitHub Pages serves a read-only snapshot (FR-01, FR-05–12, NFR-04–07, NFR-09). Scenario editing and persistence use the localhost app (FR-04, FR-13).
- Changed `.github/workflows/pages.yml`, `.gitignore`, `scripts/build_pages.py`, `services/api/civitwin_api/main.py`, `apps/web/{index.html,styles.css,app.js,desk.js}`, `tests/e2e/` and `README.md`. CI checks Python and JavaScript, runs the engine/API suite and runs the local and static browser tests before deployment.

Verification on Windows 10, Intel Core i5-4310M (4 logical processors), 11.88 GiB RAM, and Python 3.14.8:

| Command | Result |
|---|---|
| `uv venv --python 3.14 .venv-win` and `uv pip install --python .venv-win/Scripts/python.exe -r requirements.lock.txt -e . ruff` | Fresh Windows environment installed. `uv pip check --python .venv-win/Scripts/python.exe` found compatible dependencies. |
| `.venv-win/Scripts/python.exe -m pytest -q services/api/tests/test_golden.py` | 7 passed (T01). |
| `.venv-win/Scripts/python.exe -m pytest -q` | 100 passed, with one Starlette TestClient deprecation warning. The optional real-data tests use local data and skip on synthetic-only checkouts. |
| `.venv-win/Scripts/python.exe scripts/smoke.py --url http://127.0.0.1:8001` | Smoke OK. Optimized run completed with audit passed and 74.7% synthetic coverage. |
| `.venv-win/Scripts/python.exe -m compileall -q services/api scripts`, `node --check` on each web script, and `ruff check scripts/build_pages.py` | Passed. Full `ruff check services/api scripts --statistics` found 134 pre-existing lint findings. |
| `.venv-win/Scripts/python.exe scripts/build_pages.py dist/pages` | Audited snapshot built, with CP-SAT reporting OPTIMAL and 74.7% optimized coverage. |
| `node tests/e2e/browser.cjs local http://127.0.0.1:8001/` with `CIVITWIN_BROWSER_CHANNEL=msedge` | Scenario review, confirmation, audit, CSV and report reload passed (T14). |
| `node tests/e2e/browser.cjs pages http://127.0.0.1:8002/pages/` with `CIVITWIN_BROWSER_CHANNEL=msedge` | Read-only navigation, audit, language and map controls, stress view, nine downloads and the 375 px report layout passed. The browser made zero API requests (T14, partial T16). |
| `python benchmark.py --backend cpsat` with `PYTHONUTF8=1`, run from a temporary copy of `scripts/benchmark.py` | Median optimized solve 333 ms (max 405 ms), 20-case stress suite 3,466 ms, 100% audit pass rate on completed grid runs (T15, NFR-02). Historical reports are retained below. |

Docker Compose, automated full accessibility review and broader SRS release gates remain open.

Last updated: 2026-11-21 (decision-support analyses and human-centred features). Scope: hackathon MVP of the SRS P0 core. Everything below was
run on the reference machine; nothing is claimed that was not executed.

**Reference machine:** Intel Core i5-6200U (4 logical CPUs), 11 GB RAM visible, Kali Linux
7.2.15, Python 3.14.10. Versions: see `requirements.lock.txt` (OR-Tools 9.15.6755,
SciPy 1.17.1, FastAPI 0.143.3, Pydantic 2.14.1, NetworkX 3.4.2).

## Milestones

| Milestone | Status | Notes |
|---|---|---|
| M0 Foundation | Partial | Repo, contracts, deterministic generator, schemas, seed script, docs, lockfile and CI workflow. Docker Compose is open. |
| M1 Engine | Done | Travel matrix, baseline, lexicographic solver (CP-SAT + HiGHS), independent audit, metrics. Golden fixture passes exactly on both backends. |
| M2 Backend | Done (MVP) | FastAPI REST contract, SQLite store, scenario confirmation by hash, bounded job executor, idempotency, export. Plain DDL with a schema-version guard instead of Alembic. |
| M3 Frontend | Done (MVP) | Offline HTML/CSS/JS dashboard served by FastAPI instead of Next.js (see deviations). All SRS screens covered. Redesigned 2026-11-21: app shell with sidebar navigation, progress stepper, hover tooltips on every chart, toasts, dumbbell chart per cluster, validated colour palette (dataviz validator: series blue/orange and the 5-step coverage scale pass). Second pass 2026-11-21: dark theme by default with a light toggle (both palettes validated), a dependency-free 3D canvas renderer (`apps/web/viz3d.js`: rotatable 3D coverage map with flow particles, 3D stress scenario cloud), isometric 3D coverage bars, count-up numbers, animated charts and page transitions. 3D is for overview; exact values stay in the 2D charts, tooltips and data tables. |
| M4 Robustness | Mostly done | Stress suite, greedy benchmark, evidence templates (EN/UR), error/no-solution states, benchmark recorded and Playwright E2E. Full automated accessibility testing is open. |
| M5 Optional AI | Partial | Offline rule-based EN/UR parser with injection tests. **No LLM adapter** (disabled by default; needs a provider decision and key). |
| M6 Release | Partial | Fresh Windows setup, smoke and browser checks passed. GitHub Pages pipeline configured. Broader SRS release gates, screenshots and pitch are open. |

## Added 2026-11-21: decision support and human-centred features

| Feature | Where | Verification |
|---|---|---|
| Budget trade-off curve (coverage at PKR 0–8 lakh/week, for the plan's unit limit and with it relaxed; plain-language insights) — SRS P1 frontier visualisation | `civitwin_engine/analysis.py` `tradeoff_curve`, `POST /api/v1/runs/{id}/tradeoff`, Comparison page | `test_analysis.py` (golden points, monotone curve, every point audited), API test |
| "Why these sites?" — per opened site: visits served, clusters reached, leave-one-out loss (re-solved and audited) | `site_impact`, `GET /api/v1/runs/{id}/site-impact` | golden fixture: removing N loses exactly 40 visits (40 pp) |
| Community journeys — nearest-open-site travel time before/after per cluster, illustrative stories from modeled numbers, list of clusters still beyond the threshold | Comparison page, Report "People and places" | manual browser check |
| Planner's review — reviewer, role, decision, field notes, synthetic-data acknowledgement; stored only in the browser; printed in the report | Comparison page, Report | manual browser check |
| Quick scenario presets, welcome tour (English + Urdu headings), time-of-day greeting, "Our approach" page (principles, audience, pilot path) | Scenario builder, sidebar, About | manual browser check |

Analyses run through the same single job worker as solves and are cached per plan/run.

Visual design (2026-11-21, later): warm "paper" (light) and "evening" (dark, default) themes, serif headings (local Charter/Libertine fonts), a hand-drawn SVG landscape in the hero (marked "Illustration · not a real place"), bilingual English/Urdu navigation, a note from the team, and calmer motion (no glows, pulsing rings or gradient text). Chart palettes re-validated on the new surfaces; the light coverage scale now starts one step darker (#6da7ec) to keep 2:1 contrast.

## Deviations from the SRS (and why)

| SRS | Built | Reason |
|---|---|---|
| OR-Tools CP-SAT engine | CP-SAT preferred, plus HiGHS (SciPy) fallback behind the same neutral model | Network download speed was ~2 KB/s; HiGHS was already installed. Both run the same model; tests run on both; stage values matched on all checked scenarios. |
| Next.js + TypeScript + Tailwind UI | Static HTML/CSS/JS served by FastAPI | No npm downloads possible at that network speed; also runs fully offline with no build step. |
| SQLAlchemy + Alembic migrations | `sqlite3` with DDL and a schema-version check | Simpler for the MVP; migration path still needed before schema changes. |
| Python 3.11+ via lockfile | System Python 3.14 venv with `--system-site-packages` | Reuses packages already installed; verified versions pinned in `requirements.lock.txt`. |
| Demand range 40–160 visits/week | 30–110 | With 40–160, demand was about 2× existing capacity and every plan looked poor. Recorded in the dataset manifest. |
| Candidate N07 ineligible (first choice) | N05 ineligible | N07 was the only nearby site for 3 clusters, which made every equity floor infeasible. N05's exclusion strands no cluster. Recorded in the manifest. |

## Decisions that close SRS gaps (from docs/ARCHITECTURE.md §7)

| ID | Decision | Where |
|---|---|---|
| D1 | Stress failures only occur with an equity floor > 0; UI explains this and offers a coverage-target shortfall count | `stress.py`, Stress Lab |
| D2 | Demand range recalibrated to 30–110 | `dataset/generator.py` |
| D3 | One scalar demand and one scalar travel multiplier per stress case | `stress.py` |
| D4 | Half-up rounding once: demand after all multipliers (exact integer arithmetic); travel after shortest path × multiplier | `hashing.py`, `optimizer/problem.py`, `travel.py` |
| D5 | Dataset hash excludes the manifest's own `sha256` | `dataset/validation.py` |
| D6 | PlanSpec `seed` = solver seed; dataset seed in manifest; stress seed in the stress request | `planspec.py` |
| D7 | Greedy: zero-cost candidates rank first, ties by ID | `greedy.py` |
| D8 | `min_coverage_pct` added for `cost_efficient` | `planspec.py` |
| D9 | `policy_independent_hash()` available for future cross-policy comparison | `planspec.py` |
| D10 | Equity-first moves m to the front; other stages keep order | `optimizer/solve.py` |
| D11 | Separate scenario and run states; audit failure → `FAILED`; timed-out incumbent → `COMPLETED` with `optimality: not_proven`; restart → `INTERRUPTED` | `run.py`, `civitwin_api/store.py` |
| D12 | 1 running job, up to 5 waiting, then HTTP 429 | `civitwin_api/main.py` |
| D13 | `Idempotency-Key` header; custom handlers give the SRS error envelope (400/404/409/413/422/429) | `civitwin_api/main.py` |
| D14 | `within_i` defined as within-threshold assigned visits of cluster i | `optimizer/solve.py`, `audit.py` |

## Functional requirements

| ID | Status | Evidence |
|---|---|---|
| FR-01 Load immutable dataset, show source/scope/date/synthetic | Done | Data Explorer; `test_dataset.py`; immutability enforced in store |
| FR-02 Validated import, row-level errors, reject whole import | Done (JSON; API only) | `POST /datasets/import`; `test_t06_*`, `test_import_rejects_bad_dataset`. CSV adapters not built. No import screen. |
| FR-03 Travel costs, unreachable excluded | Done | `travel.py`; `test_t03_disconnected_cluster_is_unmet` |
| FR-04 Scenario editor with typed bounds | Done | Scenario Builder; strict PlanSpec; `test_invalid_plan_errors` |
| FR-05 Baseline with same rules | Done | `test_golden_baseline` |
| FR-06 Optimization with all constraints | Done | `test_golden_optimized`, T02, T04, ineligible test |
| FR-07 Independent audit, block publication | Done | 12 checks A01–A12; `test_t07_*` (5 tamper types + hash-only) |
| FR-08 Compare, flag incompatible | Done | `compare.py`; `test_t08_*` (engine + API 409) |
| FR-09 Reproducible stress tests | Done | `test_t09_*`, failure counting with floor |
| FR-10 Metric definitions, evidence IDs, solver status, limitations | Done | Evidence packet; Comparison and Report screens |
| FR-11 Deterministic NL summary offline | Done (EN + draft UR) | `evidence.py`; Urdu needs fluent review |
| FR-12 Export JSON/CSV/HTML with hashes and provenance | Done | `test_export.py`, API export tests |
| FR-13 Persist history; cancel/timeout without partial results | Done | SQLite; `test_t13_cancel_terminal_and_restart` |
| FR-14 (P1) Parse EN/UR into PlanSpec with review | Partial | Rule-based parser + confirmation; no LLM; no Pashto |
| FR-15 (P1) Three-policy comparison | Partial | All 3 policies solvable and selectable (presets include Equity first); budget trade-off curve added; side-by-side policy view not built |
| FR-16 (P2) Multi-user auth | Not started | — |

## Non-functional requirements

| ID | Status | Notes |
|---|---|---|
| NFR-01 Local, offline in template mode | Done | No external requests; UI has no CDN. Docker Compose not built. |
| NFR-02 Solve ≤ 10 s, stress ≤ 60 s | Met | CP-SAT: default optimized median 177 ms, 20-case stress 2,029 ms. HiGHS: 1,116 ms and 2,422 ms. |
| NFR-03 Strict schemas, bounded workloads | Done | extra=forbid, strict scalars, caps, 2 MB body limit, queue cap |
| NFR-04 No patient-level or precise location data | Done | Synthetic aggregate data only |
| NFR-05 Secrets server-side | Done (trivially) | No secrets used; `.env` ignored; `.env.example` names only |
| NFR-06 Local bind | Done | 127.0.0.1 default; same-origin UI, no CORS opened |
| NFR-07 Provenance, hashes, audit trail | Done | Dataset/plan/result/packet hashes; `event_log` table |
| NFR-08 Accessibility | Partial | Labels, focus styles, skip link, status = icon + label (never colour alone), data tables behind every chart, keyboard-reachable tooltips on tiles, reduced-motion support, 375 px layout without page overflow on all six pages (checked in the browser). No automated a11y test. |
| NFR-09 No fabricated results on failure | Done | NO_SOLUTION/FAILED carry no metrics (tests) |
| NFR-10 Backup before reset/migration | Partial | `reset_demo.py` backs up; no migrations yet |

## Acceptance tests

| Test | Status |
|---|---|
| T01 Golden fixture | Pass (both backends) |
| T02 Zero budget / max units 0 | Pass |
| T03 Disconnected graph | Pass |
| T04 Capacity saturation | Pass |
| T05 Impossible equity floor | Pass |
| T06 Duplicate/bad import | Pass |
| T07 Tampered output | Pass |
| T08 Mismatched comparison | Pass |
| T09 Stress reproducibility | Pass |
| T10 Offline and model failure | Partial: offline path tested; no model adapter exists to fail |
| T11 Parser injection / invalid input | Pass (rule-based parser) |
| T12 Export | Pass |
| T13 Job state / cancel / restart | Pass |
| T14 End-to-end browser | Playwright local check passed for review, confirmation, audited comparison, CSV export and report reload. |
| T15 Performance | Recorded: `docs/benchmark/benchmark-{cpsat,highs}.{md,json}` |
| T16 UI / accessibility | Manual check only |

## Commands run and results (2026-11-20)

```text
.venv/bin/python -m pytest -q                       -> 95 passed (cpsat + highs), 2026-11-21
.venv/bin/python scripts/benchmark.py --backend cpsat  -> written, all targets met
.venv/bin/python scripts/benchmark.py --backend highs  -> written, all targets met
.venv/bin/python scripts/smoke.py                   -> SMOKE OK (COMPLETED, audit passed)
.venv/bin/python -m compileall -q services/api scripts -> ok
node --check apps/web/app.js                         -> ok
ruff                                                 -> not run (not installed; download too slow)
```

Benchmark grid (both backends): audit pass rate 100% on completed runs; optimized never below
greedy; equity floor 10% is infeasible for every grid budget ≤ PKR 450,000 / ≤ 2 units
(needs ≥ 5 units, PKR 590,000) — reported as NO_SOLUTION, not hidden.

## Blockers and open items

1. Docker Compose and automated full accessibility checks.
2. LLM adapter (optional M5): needs a provider/model decision and an API key from the user.
3. Pashto; fluent review of Urdu strings.
4. CSV dataset import adapter and an import screen.
5. Alembic migrations before any schema change.
6. Resolve the existing Ruff findings.
