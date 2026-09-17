"""TNT #330 factory dogfood: fail-closed smoke, READ_ONLY kill-switch, no leaked secrets."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from tests.conftest import REPO_ROOT
from tests.test_generated_server_e2e import FakeApi
from tests.test_meta_graph_example import WRITE_TOOLS

from openapi_to_mcp import __version__
from openapi_to_mcp.generator import generate
from openapi_to_mcp.model import Service

SMOKE = REPO_ROOT / "scripts" / "factory_smoke.py"
FACTORY_DOC = REPO_ROOT / "docs" / "FACTORY_LOOP.md"
META_OUT = REPO_ROOT / "examples" / "generated" / "meta_graph_mcp"
SECRET = "factory-smoke-secret-token-9f3a1c"
_STRIP_SUFFIXES = ("_API_TOKEN", "_READ_ONLY")
_STRIP_KEYS = frozenset({"READ_ONLY", "FACTORY_LIVE", "SMOKE_WRITES", "NAME", "OUT", "SPEC"})


def _smoke_env(extra: Mapping[str, str]) -> dict[str, str]:
    cleaned = {
        key: value
        for key, value in os.environ.items()
        if key not in _STRIP_KEYS and not any(key.endswith(suffix) for suffix in _STRIP_SUFFIXES)
    }
    cleaned.update(extra)
    return cleaned


def run_smoke(*args: str, env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed interpreter and repo-owned script
        [sys.executable, str(SMOKE), *args],
        cwd=REPO_ROOT,
        env=_smoke_env(env or {}),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _combined(result: subprocess.CompletedProcess[str]) -> str:
    return f"{result.stdout}\n{result.stderr}"


class StatusApi:
    """Local vendor stand-in that returns a fixed status, optionally echoing the bearer token."""

    def __init__(self, status: int, echo_token: bool = False) -> None:
        self.status = status
        self.echo_token = echo_token
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args: object) -> None:
                pass

            def do_GET(self) -> None:
                auth = self.headers.get("Authorization", "")
                token = auth.removeprefix("Bearer ").strip()
                body = (
                    f'{{"ok": false, "echo": "{token}"}}'.encode()
                    if owner.echo_token
                    else b'{"error": "denied"}'
                )
                self.send_response(owner.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self) -> StatusApi:
        Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self._server.shutdown()
        self._server.server_close()


class TestFactorySmokeFailClosed:
    def test_script_exists(self) -> None:
        assert SMOKE.is_file(), "scripts/factory_smoke.py is the operator smoke for TNT #330"

    def test_missing_token_fails_closed_for_meta_graph_default(self) -> None:
        result = run_smoke(env={"FACTORY_LIVE": "0"})
        text = _combined(result)

        assert result.returncode != 0
        assert "FAIL" in text
        assert "META_GRAPH_API_TOKEN" in text
        assert "PASS" not in result.stdout
        assert SECRET not in text

    def test_missing_generated_server_fails(self, tmp_path: Path) -> None:
        result = run_smoke(
            "--name",
            "meta_graph",
            "--out",
            str(tmp_path / "absent"),
            env={"META_GRAPH_API_TOKEN": SECRET, "FACTORY_LIVE": "0"},
        )
        text = _combined(result)
        assert result.returncode != 0
        assert "FAIL" in text
        assert SECRET not in text

    def test_read_only_off_without_smoke_writes_is_the_kill_switch(self) -> None:
        result = run_smoke(
            env={
                "META_GRAPH_API_TOKEN": SECRET,
                "FACTORY_LIVE": "0",
                "READ_ONLY": "0",
            }
        )
        text = _combined(result)
        assert result.returncode != 0
        assert "FAIL" in text
        assert "READ_ONLY" in text
        assert SECRET not in text


class TestFactorySmokePassPath:
    def test_offline_gate_passes_with_token_and_defaults_read_only(self) -> None:
        result = run_smoke(env={"META_GRAPH_API_TOKEN": SECRET, "FACTORY_LIVE": "0"})
        text = _combined(result)

        assert result.returncode == 0, text
        assert "PASS" in result.stdout
        assert "READ_ONLY=1" in text
        assert SECRET not in text
        for write_tool in WRITE_TOOLS:
            assert write_tool in (META_OUT / "tools.json").read_text(encoding="utf-8")

    def test_token_is_never_echoed_even_when_live_response_repeats_it(
        self, tickets_service: Service, tmp_path: Path
    ) -> None:
        project = generate(tickets_service, tmp_path / "tickets", generator_version=__version__)
        with StatusApi(status=200, echo_token=True) as api:
            result = run_smoke(
                "--name",
                "tickets",
                "--out",
                str(project.directory),
                env={
                    "TICKETS_API_TOKEN": SECRET,
                    "TICKETS_BASE_URL": api.base_url,
                    "FACTORY_LIVE": "1",
                },
            )
        text = _combined(result)
        assert result.returncode == 0, text
        assert "PASS" in result.stdout
        assert SECRET not in text
        assert "Bearer" not in text

    def test_live_vendor_error_is_fail_and_redacted(self, tickets_service: Service, tmp_path: Path) -> None:
        project = generate(tickets_service, tmp_path / "tickets", generator_version=__version__)
        with StatusApi(status=401, echo_token=True) as api:
            result = run_smoke(
                "--name",
                "tickets",
                "--out",
                str(project.directory),
                env={
                    "TICKETS_API_TOKEN": SECRET,
                    "TICKETS_BASE_URL": api.base_url,
                    "FACTORY_LIVE": "1",
                },
            )
        text = _combined(result)
        assert result.returncode != 0
        assert "FAIL" in text
        assert "401" in text
        assert SECRET not in text

    def test_live_tickets_against_a_local_api_passes(self, tickets_service: Service, tmp_path: Path) -> None:
        project = generate(tickets_service, tmp_path / "tickets", generator_version=__version__)
        with FakeApi() as api:
            result = run_smoke(
                "--name",
                "tickets",
                "--out",
                str(project.directory),
                env={
                    "TICKETS_API_TOKEN": SECRET,
                    "TICKETS_BASE_URL": api.base_url,
                    "FACTORY_LIVE": "1",
                },
            )
        text = _combined(result)
        assert result.returncode == 0, text
        assert "PASS" in result.stdout
        assert "list_tickets" in text
        assert SECRET not in text


class TestFactoryMakefileAndDocs:
    def test_make_factory_is_the_meta_graph_dogfood_path(self) -> None:
        result = subprocess.run(  # noqa: S603 - repository Makefile
            ["make", "-n", "factory"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        assert "list-tools" in output
        assert "generate" in output
        assert "meta-graph-pages-openapi.yaml" in output
        assert "meta-graph-pages-overrides.yaml" in output
        assert "factory_smoke" in output

    def test_factory_loop_doc_is_the_crew_runbook(self) -> None:
        text = FACTORY_DOC.read_text(encoding="utf-8")
        lowered = text.lower()
        for needle in (
            "#330",
            "read_only",
            "kill-switch",
            "orange-prompt",
            "vault",
            "non-prod",
            "timebox",
            "failure",
            "meta-graph",
            "meta_graph_api_token",
            "never commit",
        ):
            assert needle in lowered, f"docs/FACTORY_LOOP.md must explain {needle!r}"
        assert "EAA" not in text
        assert "EAAB" not in text
