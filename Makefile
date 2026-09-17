.PHONY: help install test lint format example demo clean

PYTHON ?= python3
SPEC ?= examples/tickets-openapi.yaml
EXAMPLE_OUT ?= examples/generated/tickets_mcp
META_SPEC ?= examples/meta-graph-pages-openapi.yaml
META_OVERRIDES ?= examples/meta-graph-pages-overrides.yaml
META_EXAMPLE_OUT ?= examples/generated/meta_graph_mcp

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "} {printf "  %-10s %s\n", $$1, $$2}'

install: ## editable install with dev extras
	$(PYTHON) -m pip install -e ".[dev]"

test: ## run the test suite
	$(PYTHON) -m pytest

lint: ## static checks
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m ruff format --check src tests

format: ## apply formatting
	$(PYTHON) -m ruff format src tests
	$(PYTHON) -m ruff check --fix src tests

example: ## regenerate committed example servers (tickets + Meta Graph Pages)
	$(PYTHON) -m openapi_to_mcp generate --spec $(SPEC) --out $(EXAMPLE_OUT) --name tickets --force
	$(PYTHON) -m openapi_to_mcp generate --spec $(META_SPEC) --out $(META_EXAMPLE_OUT) --name meta_graph --overrides $(META_OVERRIDES) --force

demo: ## show the tools the sample specs produce
	$(PYTHON) -m openapi_to_mcp list-tools --spec $(SPEC) --name tickets
	$(PYTHON) -m openapi_to_mcp list-tools --spec $(META_SPEC) --name meta_graph --overrides $(META_OVERRIDES)

clean:
	rm -rf out build dist .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
