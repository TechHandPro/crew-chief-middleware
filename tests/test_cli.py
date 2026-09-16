"""The operator-facing CLI: generate, list-tools, and how failures are reported."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import SAMPLE_SPEC

from openapi_to_mcp.cli import main
from openapi_to_mcp.runtime.manifest import load_manifest


def test_generate_writes_a_runnable_project(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "tickets"
    exit_code = main(["generate", "--spec", str(SAMPLE_SPEC), "--out", str(out), "--name", "tickets"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert (out / "server.py").is_file()
    assert load_manifest(out / "tools.json").name == "tickets"
    assert "Generated 7 tools" in captured.out
    assert "TICKETS_API_TOKEN" in captured.out


def test_generate_honours_curation_and_naming_flags(tmp_path: Path) -> None:
    out = tmp_path / "tickets"
    exit_code = main(
        [
            "generate",
            "--spec",
            str(SAMPLE_SPEC),
            "--out",
            str(out),
            "--name",
            "help-desk",
            "--include",
            "list_*",
            "--include",
            "get_ticket",
            "--exclude",
            "list_ticket_comments",
            "--base-url",
            "https://staging.example.com",
            "--quiet",
        ]
    )

    manifest = load_manifest(out / "tools.json")
    assert exit_code == 0
    assert [tool.name for tool in manifest.tools] == ["list_tickets", "get_ticket"]
    assert manifest.base_url == "https://staging.example.com"
    assert manifest.env_prefix == "HELP_DESK"


def test_generate_refuses_to_clobber_then_accepts_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "tickets"
    out.mkdir()
    (out / "server.py").write_text("hand written", encoding="utf-8")
    arguments = ["generate", "--spec", str(SAMPLE_SPEC), "--out", str(out), "--name", "tickets"]

    assert main(arguments) == 1
    assert "--force" in capsys.readouterr().err
    assert main([*arguments, "--force", "--quiet"]) == 0
    assert "run_stdio" in (out / "server.py").read_text(encoding="utf-8")


def test_generate_reports_a_missing_spec_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        ["generate", "--spec", str(tmp_path / "absent.yaml"), "--out", str(tmp_path / "out"), "--name", "x"]
    )
    assert exit_code == 1
    assert "spec file not found" in capsys.readouterr().err


def test_generate_rejects_a_non_openapi_document(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec = tmp_path / "swagger.json"
    spec.write_text(json.dumps({"swagger": "2.0", "paths": {}}), encoding="utf-8")
    exit_code = main(["generate", "--spec", str(spec), "--out", str(tmp_path / "out"), "--name", "x"])
    assert exit_code == 1
    assert "Swagger 2.0" in capsys.readouterr().err


def test_list_tools_prints_a_table(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["list-tools", "--spec", str(SAMPLE_SPEC), "--name", "tickets"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Example Tickets API (1.4.0) -> 7 tools, auth: bearer" in output
    assert "list_tickets" in output and "GET    /tickets" in output


def test_list_tools_json_is_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["list-tools", "--spec", str(SAMPLE_SPEC), "--name", "tickets", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["service"]["required_env"] == ["TICKETS_API_TOKEN"]
    assert {
        "name": "get_ticket",
        "method": "GET",
        "path": "/tickets/{ticketId}",
        "read_only": True,
    }.items() <= next(tool for tool in payload["tools"] if tool["name"] == "get_ticket").items()


def test_list_tools_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    main(["list-tools", "--spec", str(SAMPLE_SPEC)])
    assert list(tmp_path.iterdir()) == []


def test_bare_invocation_shows_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "usage: openapi_to_mcp" in capsys.readouterr().out
