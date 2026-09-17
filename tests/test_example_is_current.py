"""Committed examples must match what the generator produces today.

Generated code checked into git rots silently. These tests regenerate each
sample into a temporary directory and compare it byte for byte, ignoring only
the generation timestamp.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import META_GRAPH_OVERRIDES, META_GRAPH_SPEC, REPO_ROOT, SAMPLE_SPEC

from openapi_to_mcp import __version__
from openapi_to_mcp.generator import generate
from openapi_to_mcp.model import Service

REGENERATE_HINT = "run `make example` (or openapi_to_mcp generate --force) and commit the result"


def normalized(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.name != "tools.json":
        return text
    document = json.loads(text)
    document.get("generator", {}).pop("generated_at", None)
    return json.dumps(document, indent=2, ensure_ascii=False)


def _example_files(directory: Path) -> set[str]:
    return {
        str(path.relative_to(directory))
        for path in directory.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


def _assert_committed_matches(committed: Path, fresh: Path) -> None:
    expected = _example_files(fresh)
    actual = _example_files(committed)
    assert actual == expected, f"{committed} has extra or missing files; {REGENERATE_HINT}"

    for relative in sorted(expected):
        if normalized(committed / relative) != normalized(fresh / relative):
            pytest.fail(f"{relative} in {committed} is stale; {REGENERATE_HINT}")


def test_committed_tickets_example_exists() -> None:
    committed = REPO_ROOT / "examples" / "generated" / "tickets_mcp"
    assert (committed / "tools.json").is_file(), f"missing committed example; {REGENERATE_HINT}"


def test_committed_tickets_example_matches_a_fresh_generation(
    tickets_service: Service, tmp_path: Path
) -> None:
    fresh = generate(tickets_service, tmp_path / "tickets_mcp", generator_version=__version__)
    _assert_committed_matches(REPO_ROOT / "examples" / "generated" / "tickets_mcp", fresh.directory)


def test_committed_tickets_example_exposes_the_documented_tools() -> None:
    document = json.loads(
        (REPO_ROOT / "examples" / "generated" / "tickets_mcp" / "tools.json").read_text(encoding="utf-8")
    )
    names = [tool["name"] for tool in document["tools"]]
    assert "list_tickets" in names
    assert "get_ticket" in names


def test_committed_meta_graph_example_exists() -> None:
    committed = REPO_ROOT / "examples" / "generated" / "meta_graph_mcp"
    assert (committed / "tools.json").is_file(), f"missing committed example; {REGENERATE_HINT}"


def test_committed_meta_graph_example_matches_a_fresh_generation(
    meta_graph_service: Service, tmp_path: Path
) -> None:
    fresh = generate(meta_graph_service, tmp_path / "meta_graph_mcp", generator_version=__version__)
    _assert_committed_matches(REPO_ROOT / "examples" / "generated" / "meta_graph_mcp", fresh.directory)


def test_committed_meta_graph_example_exposes_social_page_tools() -> None:
    document = json.loads(
        (REPO_ROOT / "examples" / "generated" / "meta_graph_mcp" / "tools.json").read_text(encoding="utf-8")
    )
    names = [tool["name"] for tool in document["tools"]]
    for required in (
        "get_page",
        "list_page_feed",
        "create_page_post",
        "list_post_comments",
        "list_page_insights",
    ):
        assert required in names
    assert document["service"]["env_prefix"] == "META_GRAPH"
    assert document["service"]["base_url"] == "https://graph.facebook.com/v24.0"


def test_example_sources_used_by_make_example_are_where_the_makefile_says() -> None:
    """Guard the Makefile contract so `make example` stays the regen path."""
    assert SAMPLE_SPEC.is_file()
    assert META_GRAPH_SPEC.is_file()
    assert META_GRAPH_OVERRIDES.is_file()
