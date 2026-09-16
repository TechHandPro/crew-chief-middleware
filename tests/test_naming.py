"""Tool, argument, and environment variable naming."""

from __future__ import annotations

import pytest

from openapi_to_mcp.naming import env_prefix, to_snake_case, tool_name, unique_name


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("listTickets", "list_tickets"),
        ("list-ticket-comments", "list_ticket_comments"),
        ("Ticket ID", "ticket_id"),
        ("HTTPResponseCode", "http_response_code"),
        ("tickets/{ticketId}", "tickets_ticket_id"),
        ("X-Request-Id", "x_request_id"),
        ("2fa", "n_2fa"),
        ("class", "class_"),
        ("!!!", "unnamed"),
    ],
)
def test_to_snake_case(value: str, expected: str) -> None:
    assert to_snake_case(value) == expected


def test_tool_name_prefers_operation_id() -> None:
    assert tool_name("listTickets", "GET", "/tickets") == "list_tickets"


def test_tool_name_falls_back_to_method_and_path_with_readable_path_params() -> None:
    assert (
        tool_name(None, "DELETE", "/tickets/{ticketId}/tags/{tag}")
        == "delete_tickets_by_ticket_id_tags_by_tag"
    )


def test_tool_name_ignores_a_blank_operation_id() -> None:
    assert tool_name("   ", "GET", "/tickets") == "get_tickets"


def test_unique_name_suffixes_only_on_collision() -> None:
    assert unique_name("get_ticket", []) == "get_ticket"
    assert unique_name("get_ticket", ["get_ticket"]) == "get_ticket_2"
    assert unique_name("get_ticket", ["get_ticket", "get_ticket_2"]) == "get_ticket_3"


def test_env_prefix_is_upper_snake_case() -> None:
    assert env_prefix("connectwise-manage") == "CONNECTWISE_MANAGE"
    assert env_prefix("") == "API"
