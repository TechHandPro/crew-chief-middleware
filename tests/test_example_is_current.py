"""The committed example must match what the generator produces today.

Generated code checked into git rots silently. This test regenerates the sample
into a temporary directory and compares it byte for byte, ignoring only the
generation timestamp.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import REPO_ROOT

from openapi_to_mcp import __version__
from openapi_to_mcp.generator import generate
from openapi_to_mcp.model import Service

COMMITTED_EXAMPLE = REPO_ROOT / "examples" / "generated" / "tickets_mcp"
REGENERATE_HINT = "run `make example` (or openapi_to_mcp generate --force) and commit the result"


def normalized(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.name != "tools.json":
        return text
    document = json.loads(text)
    document.get("generator", {}).pop("generated_at", None)
    return json.dumps(document, indent=2, ensure_ascii=False)


def test_committed_example_exists() -> None:
    assert (COMMITTED_EXAMPLE / "tools.json").is_file(), f"missing committed example; {REGENERATE_HINT}"


def test_committed_example_matches_a_fresh_generation(tickets_service: Service, tmp_path: Path) -> None:
    fresh = generate(tickets_service, tmp_path / "tickets_mcp", generator_version=__version__)

    expected = {str(path.relative_to(fresh.directory)) for path in fresh.files}
    actual = {
        str(path.relative_to(COMMITTED_EXAMPLE))
        for path in COMMITTED_EXAMPLE.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    assert actual == expected, f"the committed example has extra or missing files; {REGENERATE_HINT}"

    for relative in sorted(expected):
        if normalized(COMMITTED_EXAMPLE / relative) != normalized(fresh.directory / relative):
            pytest.fail(f"{relative} in the committed example is stale; {REGENERATE_HINT}")


def test_committed_example_exposes_the_documented_tools() -> None:
    document = json.loads((COMMITTED_EXAMPLE / "tools.json").read_text(encoding="utf-8"))
    names = [tool["name"] for tool in document["tools"]]
    assert "list_tickets" in names
    assert "get_ticket" in names
