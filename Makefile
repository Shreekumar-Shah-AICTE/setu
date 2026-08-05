# SETU — Makefile
# Zero-setup demo:  pip install -r requirements.txt  &&  make demo
#
# PYTHON defaults to whatever `python` is on PATH (use your venv).
PYTHON ?= python
HOST ?= 127.0.0.1
PORT ?= 8000

.DEFAULT_GOAL := help
.PHONY: help install migrate seed simulate evaluate ablation demo serve run test \
        preflight screenshots clean fresh

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	 awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install:  ## Install runtime dependencies
	$(PYTHON) -m pip install -r requirements.txt

migrate:  ## Create/upgrade the database schema
	$(PYTHON) -m alembic upgrade head

seed:  ## Load departments, keywords, officers, holidays, golden set, settings
	$(PYTHON) -m app.cli seed

simulate:  ## Generate a realistic month of backdated grievances
	$(PYTHON) -m app.cli simulate --days 30 --count 220 --seed 42

evaluate:  ## Run the evaluation harness on the held-out test split
	$(PYTHON) -m app.cli evaluate

ablation:  ## Run the five-config ablation study
	$(PYTHON) -m app.cli evaluate --ablation

preflight:  ## Connectivity + readiness checker
	$(PYTHON) scripts/preflight.py

demo: migrate seed simulate evaluate  ## Full demo: migrate -> seed -> simulate -> evaluate -> serve
	@echo ""
	@echo "  SETU is seeded and evaluated. Starting the server..."
	@echo "  Open http://$(HOST):$(PORT)/  (admin at /admin)"
	@echo ""
	$(MAKE) serve

serve:  ## Run the web server (production-ish, single worker)
	$(PYTHON) -m uvicorn app.main:app --host $(HOST) --port $(PORT)

run:  ## Run the web server with autoreload (development)
	$(PYTHON) -m uvicorn app.main:app --host $(HOST) --port $(PORT) --reload

test:  ## Run the test suite
	$(PYTHON) -m pytest -q

screenshots:  ## Capture UI screenshots with headless Chromium (dev tool)
	$(PYTHON) scripts/capture_screenshots.py

clean:  ## Remove caches and generated demo artifacts
	rm -rf .pytest_cache **/__pycache__ .mypy_cache .ruff_cache
	rm -f outbox/*.eml outbox/*.html

fresh: clean  ## Clean AND drop the database (destructive)
	rm -f setu.db setu.db-wal setu.db-shm
