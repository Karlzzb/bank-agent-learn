PYTHON := .venv/bin/python

.PHONY: setup seed run test lint cli langfuse-prices eval eval-real diagrams

setup:
	python3.12 -m venv .venv
	$(PYTHON) -m pip install -e ".[dev]"

seed:
	$(PYTHON) -m bank_agent.core.seed

run: seed
	$(PYTHON) -m bank_agent.launcher

langfuse-prices:
	$(PYTHON) -m bank_agent.langfuse_setup

cli: seed
	$(PYTHON) -m bank_agent.cli

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m ruff format --check src tests

eval:
	$(PYTHON) -m evals.run

eval-real:
	$(PYTHON) -m evals.run --real

diagrams:
	bash scripts/render-diagrams.sh
