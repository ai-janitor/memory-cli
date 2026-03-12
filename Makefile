# Makefile for memory-cli
# Graph-based memory CLI for AI agents
# Entry point: memory (installed via pyproject.toml console_scripts)
# Python package: src/memory_cli/
# Dependencies: llama-cpp-python, sqlite-vec, pysqlite3, anthropic

.PHONY: install build test lint clean run

# -- Environment variables --
# ANTHROPIC_API_KEY  — required for heavy search and conversation ingestion (Haiku calls)
# MEMORY_DB          — optional override for DB path (equivalent to --db flag)

PYTHON ?= python3
PIP ?= pip
PYTEST ?= pytest
RUFF ?= ruff

# -- Targets --

install:
	$(PIP) install -e ".[dev]"

build:
	$(PYTHON) -m build

test:
	$(PYTEST) tests/ -v --tb=short

lint:
	$(RUFF) check src/ tests/
	$(RUFF) format --check src/ tests/

clean:
	rm -rf build/ dist/ *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true

run:
	$(PYTHON) -m memory_cli.cli.entrypoint_and_argv_dispatch $(ARGS)
