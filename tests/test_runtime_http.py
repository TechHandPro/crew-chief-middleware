"""Argument mapping, safety rails, and response shaping in the runtime HTTP layer."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from openapi_to_mcp.runtime.auth import Credentials
from openapi_to_mcp.runtime.config import Settings
from openapi_to_mcp.runtime.http import ApiClient
from openapi_to_mcp.runtime.manifest import BodyBinding, ParameterBinding, ToolBinding

BASE_URL = "https://api.example.com/v1"

LIST_TICKETS = ToolBinding(
    name="list_tickets",
    description="",
    input_schema={"type": "object", "properties": {}},
    method="GET",
    path="/tickets",
    parameters=(
        ParameterBinding(arg="status", name="status", location="query"),
        ParameterBinding(arg="tag", name="tag", location="query"),
        ParameterBinding(arg="include_closed", name="includeClosed", location="query"),
        ParameterBinding(arg="x_trace", name="X-Trace", location="header"),
    ),
)
GET_TICKET = ToolBinding(
    name="get_ticket",
    description="",
    input_schema={"type": "object", "properties": {}},
    method="GET",
    path="/tickets/{ticketId}",
    parameters=(ParameterBinding(arg="ticket_id", name="ticketId", location="path", required=True),),
)
CREATE_TICKET = ToolBinding(
    name="create_ticket",
    description="",
    input_schema={"type": "object", "properties": {}},
    method="POST",
    path="/tickets",
    body=BodyBinding(arg="body", content_type="application/json", required=True),
)
SUBMIT_FORM = ToolBinding(
    name="submit_form",
    description="",
    input_schema={"type": "object", "properties": {}},
    method="POST",
    path="/forms",
    body=BodyBinding(arg="body", content_type="application/x-www-form-urlencoded", required=True),
)


class Recorder:
    """Captures outgoing requests and replays canned responses."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.requests: list[httpx.Request] = []
        self._responses = list(responses) or [httpx.Response(200, json={"ok": True})]

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self._responses[min(len(self.requests) - 1, len(self._responses) - 1)]

        return httpx.MockTransport(handle)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]


def build_client(recorder: Recorder, **settings_kwargs: Any) -> ApiClient:
    settings = Settings(base_url=BASE_URL, max_retries=0, **settings_kwargs)
    credentials = Credentials(
        headers={"Authorization": "Bearer token-value-1234"}, secrets=("token-value-1234",)
    )
    return ApiClient(settings, credentials, transport=recorder.transport())


@pytest.mark.anyio
class TestRequestBuilding:
    async def test_query_parameters_use_their_wire_names_and_repeat_lists(self) -> None:
        recorder = Recorder()
        async with build_client(recorder) as client:
            await client.call(
                LIST_TICKETS, {"status": "open", "tag": ["billing", "vip"], "include_closed": False}
            )

        assert recorder.last.url.path == "/v1/tickets"
        assert recorder.last.url.params.multi_items() == [
            ("status", "open"),
            ("tag", "billing"),
            ("tag", "vip"),
            ("includeClosed", "false"),
        ]

    async def test_omitted_optional_arguments_are_not_sent(self) -> None:
        recorder = Recorder()
        async with build_client(recorder) as client:
            await client.call(LIST_TICKETS, {"status": None})
        assert recorder.last.url.params.multi_items() == []

    async def test_header_parameters_and_credentials_are_both_applied(self) -> None:
        recorder = Recorder()
        async with build_client(recorder) as client:
            await client.call(LIST_TICKETS, {"x_trace": "abc"})
        assert recorder.last.headers["X-Trace"] == "abc"
        assert recorder.last.headers["Authorization"] == "Bearer token-value-1234"

    async def test_path_parameters_are_url_encoded(self) -> None:
        recorder = Recorder()
        async with build_client(recorder) as client:
            await client.call(GET_TICKET, {"ticket_id": "TCK/42 x"})
        assert str(recorder.last.url) == f"{BASE_URL}/tickets/TCK%2F42%20x"

    async def test_json_bodies_are_serialized(self) -> None:
        recorder = Recorder(httpx.Response(201, json={"id": "TCK-1"}))
        async with build_client(recorder) as client:
            await client.call(CREATE_TICKET, {"body": {"subject": "Printer down", "tags": ["hardware"]}})
        assert json.loads(recorder.last.content) == {"subject": "Printer down", "tags": ["hardware"]}
        assert recorder.last.headers["content-type"] == "application/json"

    async def test_form_bodies_are_url_encoded(self) -> None:
        recorder = Recorder()
        async with build_client(recorder) as client:
            await client.call(SUBMIT_FORM, {"body": {"name": "alice", "admin": True}})
        assert recorder.last.content == b"name=alice&admin=true"

    async def test_redirects_are_not_followed_so_credentials_stay_put(self) -> None:
        recorder = Recorder(httpx.Response(302, headers={"location": "https://evil.example.com/"}))
        async with build_client(recorder) as client:
            result = await client.call(GET_TICKET, {"ticket_id": "TCK-1"})
        assert len(recorder.requests) == 1
        assert "HTTP 302" in result.text


@pytest.mark.anyio
class TestArgumentValidation:
    async def test_a_missing_required_path_argument_is_reported_without_a_request(self) -> None:
        recorder = Recorder()
        async with build_client(recorder) as client:
            result = await client.call(GET_TICKET, {})
        assert result.is_error and "requires the 'ticket_id' argument" in result.text
        assert recorder.requests == []

    async def test_an_empty_path_argument_is_rejected(self) -> None:
        recorder = Recorder()
        async with build_client(recorder) as client:
            result = await client.call(GET_TICKET, {"ticket_id": ""})
        assert result.is_error and recorder.requests == []

    async def test_unknown_arguments_are_rejected_and_the_accepted_ones_listed(self) -> None:
        recorder = Recorder()
        async with build_client(recorder) as client:
            result = await client.call(GET_TICKET, {"ticketId": "TCK-1"})
        assert result.is_error
        assert "unknown argument(s) for get_ticket: ticketId" in result.text
        assert "Accepted arguments: ticket_id" in result.text
        assert recorder.requests == []

    async def test_a_missing_required_body_is_reported(self) -> None:
        recorder = Recorder()
        async with build_client(recorder) as client:
            result = await client.call(CREATE_TICKET, {})
        assert result.is_error and "requires the 'body' argument" in result.text

    async def test_read_only_mode_blocks_writes_before_they_leave_the_process(self) -> None:
        recorder = Recorder()
        async with build_client(recorder, read_only=True) as client:
            result = await client.call(CREATE_TICKET, {"body": {"subject": "x"}})
        assert result.is_error and "read-only mode" in result.text
        assert recorder.requests == []


@pytest.mark.anyio
class TestResponseHandling:
    async def test_json_objects_are_returned_as_text_and_structured_content(self) -> None:
        recorder = Recorder(httpx.Response(200, json={"id": "TCK-1", "status": "open"}))
        async with build_client(recorder) as client:
            result = await client.call(GET_TICKET, {"ticket_id": "TCK-1"})
        assert result.is_error is False
        assert result.structured == {"id": "TCK-1", "status": "open"}
        assert json.loads(result.text)["status"] == "open"

    async def test_json_arrays_are_wrapped_so_structured_content_stays_an_object(self) -> None:
        recorder = Recorder(httpx.Response(200, json=[{"id": "TCK-1"}, {"id": "TCK-2"}]))
        async with build_client(recorder) as client:
            result = await client.call(LIST_TICKETS, {})
        assert result.structured == {"items": [{"id": "TCK-1"}, {"id": "TCK-2"}], "count": 2}

    async def test_error_statuses_become_tool_errors_with_the_body_attached(self) -> None:
        recorder = Recorder(httpx.Response(404, json={"error": "no such ticket"}))
        async with build_client(recorder) as client:
            result = await client.call(GET_TICKET, {"ticket_id": "TCK-9"})
        assert result.is_error
        assert "HTTP 404 from GET /tickets/{ticketId}" in result.text
        assert "no such ticket" in result.text

    async def test_empty_bodies_report_the_status(self) -> None:
        recorder = Recorder(httpx.Response(204))
        async with build_client(recorder) as client:
            result = await client.call(GET_TICKET, {"ticket_id": "TCK-1"})
        assert result.is_error is False and "204" in result.text

    async def test_oversized_responses_are_truncated(self) -> None:
        payload = json.dumps({"items": ["x" * 100] * 100})
        recorder = Recorder(httpx.Response(200, text=payload, headers={"content-type": "application/json"}))
        async with build_client(recorder, max_response_bytes=2048) as client:
            result = await client.call(LIST_TICKETS, {})
        assert "[truncated to 2048 bytes]" in result.text
        assert result.structured is None

    async def test_non_json_responses_come_back_as_text(self) -> None:
        recorder = Recorder(httpx.Response(200, text="plain report", headers={"content-type": "text/plain"}))
        async with build_client(recorder) as client:
            result = await client.call(GET_TICKET, {"ticket_id": "TCK-1"})
        assert result.text == "plain report" and result.structured is None

    async def test_credentials_never_appear_in_error_text(self) -> None:
        recorder = Recorder(httpx.Response(401, text="rejected token token-value-1234"))
        async with build_client(recorder) as client:
            result = await client.call(GET_TICKET, {"ticket_id": "TCK-1"})
        assert "token-value-1234" not in result.text
        assert "***" in result.text

    async def test_network_failures_become_tool_errors(self) -> None:
        def explode(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        settings = Settings(base_url=BASE_URL, max_retries=0)
        async with ApiClient(settings, Credentials(), transport=httpx.MockTransport(explode)) as client:
            result = await client.call(GET_TICKET, {"ticket_id": "TCK-1"})
        assert result.is_error and "connection refused" in result.text


@pytest.mark.anyio
class TestRetries:
    async def test_idempotent_requests_retry_on_a_retryable_status(self) -> None:
        recorder = Recorder(
            httpx.Response(503, text="busy"),
            httpx.Response(200, json={"id": "TCK-1"}),
        )
        settings = Settings(base_url=BASE_URL, max_retries=1)
        async with ApiClient(settings, Credentials(), transport=recorder.transport()) as client:
            result = await client.call(GET_TICKET, {"ticket_id": "TCK-1"})
        assert len(recorder.requests) == 2
        assert result.is_error is False

    async def test_writes_are_never_retried(self) -> None:
        recorder = Recorder(httpx.Response(503, text="busy"))
        settings = Settings(base_url=BASE_URL, max_retries=3)
        async with ApiClient(settings, Credentials(), transport=recorder.transport()) as client:
            result = await client.call(CREATE_TICKET, {"body": {"subject": "x"}})
        assert len(recorder.requests) == 1
        assert result.is_error

    async def test_client_errors_are_not_retried(self) -> None:
        recorder = Recorder(httpx.Response(400, text="bad request"))
        settings = Settings(base_url=BASE_URL, max_retries=3)
        async with ApiClient(settings, Credentials(), transport=recorder.transport()) as client:
            await client.call(GET_TICKET, {"ticket_id": "TCK-1"})
        assert len(recorder.requests) == 1
