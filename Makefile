# CIVITWIN AI — local commands. Windows users: see README (PowerShell equivalents).
PY ?= .venv/bin/python

.PHONY: setup seed dev test lint benchmark smoke reset-demo

setup:            ## create venv and install (reuses system packages if present)
	python3 -m venv --system-site-packages .venv
	$(PY) -m pip install -r requirements.lock.txt
	$(PY) -m pip install --no-deps --no-build-isolation -e .

seed:             ## write synthetic datasets + JSON schemas to data/ (idempotent)
	$(PY) scripts/seed.py

dev:              ## run API + web UI on http://127.0.0.1:8000
	$(PY) -m civitwin_api

test:             ## unit + integration tests on every installed solver backend
	$(PY) -m pytest -q

lint:             ## compile check (ruff is configured in pyproject; run it if installed)
	$(PY) -m compileall -q services/api scripts
	node --check apps/web/app.js
	-$(PY) -m ruff check services/api scripts

benchmark:        ## record timings and baseline/greedy/solver grid in docs/benchmark/
	$(PY) scripts/benchmark.py

smoke:            ## end-to-end check against a running server (make dev first)
	$(PY) scripts/smoke.py

reset-demo:       ## delete local demo DB after typed confirmation (backup kept)
	$(PY) scripts/reset_demo.py
