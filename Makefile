.PHONY: help install test lint format example demo factory factory-list factory-generate factory-smoke clean

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
	$(PYTHON) -m ruff check src tests scripts
	$(PYTHON) -m ruff format --check src tests scripts

format: ## apply formatting
	$(PYTHON) -m ruff format src tests scripts
	$(PYTHON) -m ruff check --fix src tests scripts

example: ## regenerate committed example servers (tickets + Meta Graph Pages)
	$(PYTHON) -m openapi_to_mcp generate --spec $(SPEC) --out $(EXAMPLE_OUT) --name tickets --force
	$(PYTHON) -m openapi_to_mcp generate --spec $(META_SPEC) --out $(META_EXAMPLE_OUT) --name meta_graph --overrides $(META_OVERRIDES) --force

demo: ## show the tools the sample specs produce
	$(PYTHON) -m openapi_to_mcp list-tools --spec $(SPEC) --name tickets
	$(PYTHON) -m openapi_to_mcp list-tools --spec $(META_SPEC) --name meta_graph --overrides $(META_OVERRIDES)

# One Meta Graph dogfood path, not a multi-vendor factory product.
# `make example` keeps SPEC=tickets. Command-line SPEC=/NAME=/OUT=/OVERRIDES=
# still override these target-specific defaults (GNU make).
factory factory-list factory-generate factory-smoke: SPEC = $(META_SPEC)
factory factory-list factory-generate factory-smoke: NAME = meta_graph
factory factory-list factory-generate factory-smoke: OUT = $(META_EXAMPLE_OUT)
factory factory-list factory-generate factory-smoke: OVERRIDES = $(META_OVERRIDES)

factory-list: ## preview tools (Meta Graph factory default)
	$(PYTHON) -m openapi_to_mcp list-tools --spec $(SPEC) --name $(NAME) $(and $(OVERRIDES),--overrides $(OVERRIDES))

factory-generate: ## regenerate the factory server (Meta Graph default)
	$(PYTHON) -m openapi_to_mcp generate --spec $(SPEC) --out $(OUT) --name $(NAME) $(and $(OVERRIDES),--overrides $(OVERRIDES)) --force

factory-smoke: ## fail-closed READ_ONLY smoke (requires NAME_API_TOKEN)
	NAME=$(NAME) OUT=$(OUT) $(PYTHON) scripts/factory_smoke.py

factory: factory-list factory-generate factory-smoke ## discover → generate → smoke (Meta Graph default)

clean:
	rm -rf out build dist .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
