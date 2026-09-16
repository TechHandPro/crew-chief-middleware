"""End to end: a generated server, launched as a subprocess, talking to a real API.

This is the test that proves the deliverable. It starts a throwaway HTTP server,
generates the tickets project, launches ``python server.py`` the way an MCP client
would, and drives it over stdio.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from openapi_to_mcp.generator import GeneratedProject

TOKEN = "test-token-abc123"
TICKET = {"id": "TCK-42", "subject": "Printer offline", "status": "open"}
STARTUP_TIMEOUT_SECONDS = 30


class FakeApi:
    """A minimal stand-in for a vendor API that records what it received."""

    def __init__(self) -> None:
        self.requests: list[dict[str, str]] = []
        recorder = self.requests

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args: object) -> None:
                pass

            def _record(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                recorder.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "authorization": self.headers.get("Authorization", ""),
                        "body": self.rfile.read(length).decode("utf-8") if length else "",
                    }
                )

            def _reply(self, status: int, payload: object) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                self._record()
                if self.path.startswith("/tickets/"):
                    self._reply(200, TICKET)
                else:
                    self._reply(200, {"items": [TICKET], "nextCursor": None})

            def do_POST(self) -> None:
                self._record()
                self._reply(201, TICKET)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self) -> FakeApi:
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def fake_api() -> Iterator[FakeApi]:
    with FakeApi() as api:
        yield api


def stdio_parameters(project: GeneratedProject, base_url: str, **extra_env: str) -> StdioServerParameters:
    env = {
        **os.environ,
        "TICKETS_API_TOKEN": TOKEN,
        "TICKETS_BASE_URL": base_url,
        **extra_env,
    }
    return StdioServerParameters(command=sys.executable, args=[str(project.server_script)], env=env)


def start_server(project: GeneratedProject, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the generated server with no MCP client attached, to observe startup only."""
    return subprocess.run(  # noqa: S603 - fixed command, test-owned arguments
        [sys.executable, str(project.server_script)],
        env=env,
        input="",
        capture_output=True,
        text=True,
        timeout=STARTUP_TIMEOUT_SECONDS,
        check=False,
    )


@pytest.mark.anyio
async def test_generated_server_lists_and_calls_tools_over_stdio(
    generated_tickets: GeneratedProject, fake_api: FakeApi
) -> None:
    async with Client(stdio_parameters(generated_tickets, fake_api.base_url)) as client:
        listing = await client.list_tools()
        listed = await client.call_tool("list_tickets", {"status": "open", "tag": ["vip"], "limit": 5})
        fetched = await client.call_tool("get_ticket", {"ticket_id": "TCK-42"})
        created = await client.call_tool("create_ticket", {"body": {"subject": "Printer offline"}})
        missing_argument = await client.call_tool("get_ticket", {})

    assert [tool.name for tool in listing.tools] == list(generated_tickets.tool_names)

    assert listed.is_error is False
    assert json.loads(listed.content[0].text)["items"][0]["id"] == "TCK-42"
    assert fetched.is_error is False
    assert created.is_error is False
    assert missing_argument.is_error is True
    assert "requires the 'ticket_id' argument" in missing_argument.content[0].text

    calls = {(request["method"], request["path"].split("?")[0]) for request in fake_api.requests}
    assert ("GET", "/tickets") in calls
    assert ("GET", "/tickets/TCK-42") in calls
    assert ("POST", "/tickets") in calls
    assert all(request["authorization"] == f"Bearer {TOKEN}" for request in fake_api.requests)
    assert json.loads(next(r for r in fake_api.requests if r["method"] == "POST")["body"]) == {
        "subject": "Printer offline"
    }
    query = next(r["path"] for r in fake_api.requests if r["path"].startswith("/tickets?"))
    assert query == "/tickets?status=open&tag=vip&limit=5"

    # The failed call did not reach the API: argument validation happens locally.
    assert len([r for r in fake_api.requests if r["path"].startswith("/tickets/")]) == 1


@pytest.mark.anyio
async def test_read_only_mode_hides_write_tools_in_a_real_process(
    generated_tickets: GeneratedProject, fake_api: FakeApi
) -> None:
    parameters = stdio_parameters(generated_tickets, fake_api.base_url, TICKETS_READ_ONLY="1")
    async with Client(parameters) as client:
        names = [tool.name for tool in (await client.list_tools()).tools]
        blocked = await client.call_tool("create_ticket", {"body": {"subject": "nope"}})

    assert names == ["list_tickets", "get_ticket", "list_ticket_comments"]
    assert blocked.is_error is True
    assert not [request for request in fake_api.requests if request["method"] == "POST"]


def test_a_missing_credential_stops_startup_instead_of_calling_the_api(
    generated_tickets: GeneratedProject, fake_api: FakeApi
) -> None:
    env = {key: value for key, value in os.environ.items() if key != "TICKETS_API_TOKEN"}
    env["TICKETS_BASE_URL"] = fake_api.base_url

    finished = start_server(generated_tickets, env)

    assert finished.returncode == 1
    assert "TICKETS_API_TOKEN" in finished.stderr
    assert finished.stdout == ""
    assert fake_api.requests == []


def test_plaintext_http_to_a_remote_host_is_refused_at_startup(generated_tickets: GeneratedProject) -> None:
    env = {**os.environ, "TICKETS_API_TOKEN": TOKEN, "TICKETS_BASE_URL": "http://api.example.com"}

    finished = start_server(generated_tickets, env)

    assert finished.returncode == 1
    assert "TICKETS_ALLOW_INSECURE_HTTP" in finished.stderr
