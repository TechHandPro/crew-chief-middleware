"""The MCP surface: what a client sees when it lists and calls tools."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from mcp.client import Client

from openapi_to_mcp.generator import GeneratedProject
from openapi_to_mcp.runtime.auth import Credentials
from openapi_to_mcp.runtime.config import Settings
from openapi_to_mcp.runtime.http import ApiClient, ToolResult
from openapi_to_mcp.runtime.manifest import Manifest, load_manifest
from openapi_to_mcp.runtime.server import LocalTool, build_server

BASE_URL = "https://tickets.example.com/api/v1"

pytestmark = pytest.mark.anyio


@pytest.fixture
def manifest(generated_tickets: GeneratedProject) -> Manifest:
    return load_manifest(generated_tickets.directory / "tools.json")


def api_client(handler, **settings_kwargs) -> ApiClient:
    settings = Settings(base_url=BASE_URL, max_retries=0, **settings_kwargs)
    credentials = Credentials(
        headers={"Authorization": "Bearer token-value-1234"}, secrets=("token-value-1234",)
    )
    return ApiClient(settings, credentials, transport=httpx.MockTransport(handler))


class TestToolListing:
    async def test_every_manifest_tool_is_advertised_with_its_schema(self, manifest: Manifest) -> None:
        async with api_client(lambda request: httpx.Response(200, json={})) as api:
            server = build_server(manifest, Settings(base_url=BASE_URL), api)
            async with Client(server) as client:
                listing = await client.list_tools()

        names = [tool.name for tool in listing.tools]
        assert names == [tool.name for tool in manifest.tools]
        get_ticket = next(tool for tool in listing.tools if tool.name == "get_ticket")
        assert get_ticket.input_schema["required"] == ["ticket_id"]
        assert get_ticket.description.startswith("Get one ticket")
        assert get_ticket.annotations is not None and get_ticket.annotations.read_only_hint is True

    async def test_read_only_mode_hides_mutating_tools(self, manifest: Manifest) -> None:
        settings = Settings(base_url=BASE_URL, read_only=True)
        async with api_client(lambda request: httpx.Response(200, json={}), read_only=True) as api:
            server = build_server(manifest, settings, api)
            async with Client(server) as client:
                names = [tool.name for tool in (await client.list_tools()).tools]

        assert names == ["list_tickets", "get_ticket", "list_ticket_comments"]

    async def test_customize_narrows_the_advertised_tools(self, manifest: Manifest) -> None:
        async with api_client(lambda request: httpx.Response(200, json={})) as api:
            server = build_server(
                manifest,
                Settings(base_url=BASE_URL),
                api,
                customize=lambda tools: [tool for tool in tools if tool.name == "get_ticket"],
            )
            async with Client(server) as client:
                names = [tool.name for tool in (await client.list_tools()).tools]

        assert names == ["get_ticket"]

    async def test_server_instructions_point_agents_away_from_the_browser(self, manifest: Manifest) -> None:
        async with api_client(lambda request: httpx.Response(200, json={})) as api:
            server = build_server(manifest, Settings(base_url=BASE_URL), api)
            async with Client(server) as client:
                instructions = client.instructions or ""

        assert "browser automation" in instructions
        assert BASE_URL in instructions


class TestToolCalls:
    async def test_calling_a_tool_performs_the_documented_request(self, manifest: Manifest) -> None:
        seen: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"id": "TCK-42", "status": "open"})

        async with api_client(handle) as api:
            server = build_server(manifest, Settings(base_url=BASE_URL), api)
            async with Client(server) as client:
                result = await client.call_tool("get_ticket", {"ticket_id": "TCK-42"})

        assert seen[0].method == "GET"
        assert str(seen[0].url) == f"{BASE_URL}/tickets/TCK-42"
        assert result.is_error is False
        assert json.loads(result.content[0].text)["id"] == "TCK-42"
        assert result.structured_content == {"id": "TCK-42", "status": "open"}

    async def test_api_errors_surface_as_tool_errors_not_transport_failures(self, manifest: Manifest) -> None:
        async with api_client(lambda request: httpx.Response(500, text="boom")) as api:
            server = build_server(manifest, Settings(base_url=BASE_URL), api)
            async with Client(server) as client:
                result = await client.call_tool("get_ticket", {"ticket_id": "TCK-42"})

        assert result.is_error is True
        assert "HTTP 500" in result.content[0].text

    async def test_unknown_tools_are_reported_with_the_available_names(self, manifest: Manifest) -> None:
        async with api_client(lambda request: httpx.Response(200, json={})) as api:
            server = build_server(manifest, Settings(base_url=BASE_URL), api)
            async with Client(server) as client:
                result = await client.call_tool("teleport", {})

        assert result.is_error is True
        assert "unknown tool 'teleport'" in result.content[0].text
        assert "get_ticket" in result.content[0].text

    async def test_write_tools_are_rejected_in_read_only_mode_even_if_named_directly(
        self, manifest: Manifest
    ) -> None:
        settings = Settings(base_url=BASE_URL, read_only=True)
        async with api_client(lambda request: httpx.Response(200, json={}), read_only=True) as api:
            server = build_server(manifest, settings, api)
            async with Client(server) as client:
                result = await client.call_tool("delete_ticket", {"ticket_id": "TCK-42"})

        assert result.is_error is True


class TestSpecialization:
    async def test_hand_written_tools_are_served_next_to_generated_ones(self, manifest: Manifest) -> None:
        async def digest(arguments: dict) -> ToolResult:
            return ToolResult(
                text=f"digest for {arguments['owner']}", structured={"owner": arguments["owner"]}
            )

        extra = LocalTool(
            name="open_ticket_digest",
            description="Summarize the open queue for one owner.",
            handler=digest,
            input_schema={
                "type": "object",
                "properties": {"owner": {"type": "string"}},
                "required": ["owner"],
            },
        )

        async with api_client(lambda request: httpx.Response(200, json={})) as api:
            server = build_server(manifest, Settings(base_url=BASE_URL), api, extra_tools=[extra])
            async with Client(server) as client:
                names = [tool.name for tool in (await client.list_tools()).tools]
                result = await client.call_tool("open_ticket_digest", {"owner": "alice"})

        assert "open_ticket_digest" in names
        assert result.content[0].text == "digest for alice"
        assert result.structured_content == {"owner": "alice"}

    async def test_a_failing_hand_written_tool_does_not_take_the_server_down(
        self, manifest: Manifest
    ) -> None:
        async def broken(_arguments: dict) -> ToolResult:
            raise RuntimeError("not implemented yet")

        extra = LocalTool(name="broken", description="", handler=broken)

        async with api_client(lambda request: httpx.Response(200, json={})) as api:
            server = build_server(manifest, Settings(base_url=BASE_URL), api, extra_tools=[extra])
            async with Client(server) as client:
                failure = await client.call_tool("broken", {})
                still_alive = await client.list_tools()

        assert failure.is_error is True
        assert "not implemented yet" in failure.content[0].text
        assert still_alive.tools


def test_generated_manifest_is_loadable_from_its_directory(generated_tickets: GeneratedProject) -> None:
    assert Path(generated_tickets.directory / "tools.json").is_file()
