"""Shared fixtures: the sample spec, a discovered service, and a generated project."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from openapi_to_mcp import __version__
from openapi_to_mcp.discovery import discover
from openapi_to_mcp.generator import GeneratedProject, generate
from openapi_to_mcp.model import Service
from openapi_to_mcp.overrides import apply_overrides, load_overrides
from openapi_to_mcp.spec_loader import load_spec

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_SPEC = REPO_ROOT / "examples" / "tickets-openapi.yaml"
META_GRAPH_SPEC = REPO_ROOT / "examples" / "meta-graph-pages-openapi.yaml"
META_GRAPH_OVERRIDES = REPO_ROOT / "examples" / "meta-graph-pages-overrides.yaml"


@pytest.fixture(scope="session")
def sample_spec() -> dict[str, Any]:
    return load_spec(SAMPLE_SPEC)


@pytest.fixture
def tickets_service(sample_spec: dict[str, Any]) -> Service:
    return discover(sample_spec, name="tickets").service


@pytest.fixture
def generated_tickets(tickets_service: Service, tmp_path: Path) -> GeneratedProject:
    return generate(tickets_service, tmp_path / "tickets", generator_version=__version__)


@pytest.fixture(scope="session")
def meta_graph_spec() -> dict[str, Any]:
    return load_spec(META_GRAPH_SPEC)


@pytest.fixture
def meta_graph_service(meta_graph_spec: dict[str, Any]) -> Service:
    discovered = discover(meta_graph_spec, name="meta_graph").service
    curated, _ = apply_overrides(discovered, load_overrides(META_GRAPH_OVERRIDES))
    return curated
