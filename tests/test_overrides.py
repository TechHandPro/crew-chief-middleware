"""Specialization: filtering, renaming, and re-describing discovered tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from openapi_to_mcp.errors import GeneratorError
from openapi_to_mcp.model import Service
from openapi_to_mcp.overrides import Overrides, apply_overrides, load_overrides, merge_overrides


def test_include_globs_keep_only_matching_tools(tickets_service: Service) -> None:
    curated, _ = apply_overrides(tickets_service, Overrides(include=("list_*", "get_ticket")))
    assert curated.tool_names == ("list_tickets", "get_ticket", "list_ticket_comments")


def test_exclude_globs_drop_matching_tools(tickets_service: Service) -> None:
    curated, _ = apply_overrides(tickets_service, Overrides(exclude=("delete_*", "update_*")))
    assert "delete_ticket" not in curated.tool_names
    assert "update_ticket" not in curated.tool_names


def test_exclude_wins_over_include(tickets_service: Service) -> None:
    curated, _ = apply_overrides(
        tickets_service, Overrides(include=("*ticket*",), exclude=("delete_ticket",))
    )
    assert "delete_ticket" not in curated.tool_names


def test_unrelated_tool_data_survives_curation(tickets_service: Service) -> None:
    curated, _ = apply_overrides(tickets_service, Overrides(include=("get_ticket",)))
    assert curated.tool("get_ticket").input_schema == tickets_service.tool("get_ticket").input_schema
    assert curated.auth == tickets_service.auth


def test_filtering_everything_is_an_error(tickets_service: Service) -> None:
    with pytest.raises(GeneratorError, match="every tool was filtered out"):
        apply_overrides(tickets_service, Overrides(include=("nothing_matches",)))


def test_file_overrides_rename_describe_and_hide(tickets_service: Service, tmp_path: Path) -> None:
    overrides_file = tmp_path / "overrides.yaml"
    overrides_file.write_text(
        """
exclude:
  - delete_ticket
tools:
  list_tickets:
    name: search_tickets
    description: Search the service desk.
  add_ticket_comment:
    hidden: true
""",
        encoding="utf-8",
    )

    curated, warnings = apply_overrides(tickets_service, load_overrides(overrides_file))

    assert "search_tickets" in curated.tool_names
    assert "list_tickets" not in curated.tool_names
    assert curated.tool("search_tickets").description == "Search the service desk."
    assert "delete_ticket" not in curated.tool_names
    assert "add_ticket_comment" not in curated.tool_names
    assert warnings == ()


def test_overrides_for_unknown_tools_warn_about_the_typo(tickets_service: Service, tmp_path: Path) -> None:
    overrides_file = tmp_path / "overrides.yaml"
    overrides_file.write_text("tools:\n  list_tickest:\n    hidden: true\n", encoding="utf-8")
    _, warnings = apply_overrides(tickets_service, load_overrides(overrides_file))
    assert warnings == ("overrides mention unknown tool 'list_tickest'",)


def test_renaming_two_tools_to_the_same_name_is_rejected(tickets_service: Service, tmp_path: Path) -> None:
    overrides_file = tmp_path / "overrides.yaml"
    overrides_file.write_text(
        "tools:\n  list_tickets:\n    name: tickets\n  get_ticket:\n    name: tickets\n", encoding="utf-8"
    )
    with pytest.raises(GeneratorError, match="duplicate tool names"):
        apply_overrides(tickets_service, load_overrides(overrides_file))


def test_invalid_rename_is_rejected_at_load_time(tmp_path: Path) -> None:
    overrides_file = tmp_path / "overrides.yaml"
    overrides_file.write_text("tools:\n  list_tickets:\n    name: 'not valid!'\n", encoding="utf-8")
    with pytest.raises(GeneratorError, match="not a valid tool name"):
        load_overrides(overrides_file)


def test_missing_overrides_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(GeneratorError, match="overrides file not found"):
        load_overrides(tmp_path / "absent.yaml")


def test_command_line_globs_layer_on_top_of_the_file(tmp_path: Path) -> None:
    overrides_file = tmp_path / "overrides.yaml"
    overrides_file.write_text("exclude: [delete_ticket]\n", encoding="utf-8")
    merged = merge_overrides(load_overrides(overrides_file), include=("get_*",), exclude=("update_*",))
    assert merged.include == ("get_*",)
    assert merged.exclude == ("delete_ticket", "update_*")


def test_no_overrides_returns_the_service_untouched(tickets_service: Service) -> None:
    curated, warnings = apply_overrides(tickets_service, Overrides())
    assert curated is tickets_service
    assert warnings == ()
