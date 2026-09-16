"""Generation: what lands on disk, and whether the runtime can read it back."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openapi_to_mcp import __version__
from openapi_to_mcp.errors import OutputError
from openapi_to_mcp.generator import GeneratedProject, generate
from openapi_to_mcp.model import Service
from openapi_to_mcp.runtime.manifest import MANIFEST_VERSION, load_manifest

EXPECTED_FILES = {
    ".env.example",
    ".gitignore",
    "Dockerfile",
    "README.md",
    "mcp.example.json",
    "mcp_runtime/__init__.py",
    "mcp_runtime/auth.py",
    "mcp_runtime/config.py",
    "mcp_runtime/http.py",
    "mcp_runtime/manifest.py",
    "mcp_runtime/server.py",
    "requirements.txt",
    "server.py",
    "tools.json",
}


def relative_files(project: GeneratedProject) -> set[str]:
    return {str(path.relative_to(project.directory)) for path in project.files}


class TestProjectLayout:
    def test_generates_a_self_contained_project(self, generated_tickets: GeneratedProject) -> None:
        assert relative_files(generated_tickets) == EXPECTED_FILES

    def test_entry_point_only_imports_the_vendored_runtime(self, generated_tickets: GeneratedProject) -> None:
        source = generated_tickets.server_script.read_text(encoding="utf-8")
        assert "from mcp_runtime import run_stdio" in source
        assert "openapi_to_mcp" not in source

    def test_vendored_runtime_never_imports_the_generator(self, generated_tickets: GeneratedProject) -> None:
        for module in (generated_tickets.directory / "mcp_runtime").glob("*.py"):
            source = module.read_text(encoding="utf-8")
            assert "import openapi_to_mcp" not in source
            assert "from openapi_to_mcp" not in source

    def test_no_template_placeholder_survives_rendering(self, generated_tickets: GeneratedProject) -> None:
        rendered = [path for path in generated_tickets.files if path.parent == generated_tickets.directory]
        for path in rendered:
            assert "{{" not in path.read_text(encoding="utf-8"), path

    def test_secrets_are_documented_but_never_written(self, generated_tickets: GeneratedProject) -> None:
        env_example = (generated_tickets.directory / ".env.example").read_text(encoding="utf-8")
        assert "TICKETS_API_TOKEN=" in env_example
        assert "TICKETS_READ_ONLY" in env_example
        assert "mcp.json" in (generated_tickets.directory / ".gitignore").read_text(encoding="utf-8")

    def test_readme_lists_every_tool(
        self, generated_tickets: GeneratedProject, tickets_service: Service
    ) -> None:
        readme = (generated_tickets.directory / "README.md").read_text(encoding="utf-8")
        for name in tickets_service.tool_names:
            assert f"`{name}`" in readme

    def test_dockerfile_runs_as_a_non_root_user(self, generated_tickets: GeneratedProject) -> None:
        dockerfile = (generated_tickets.directory / "Dockerfile").read_text(encoding="utf-8")
        assert "USER mcp" in dockerfile


class TestManifest:
    def test_manifest_round_trips_through_the_runtime_loader(
        self, generated_tickets: GeneratedProject
    ) -> None:
        manifest = load_manifest(generated_tickets.directory / "tools.json")
        assert manifest.name == "tickets"
        assert manifest.env_prefix == "TICKETS"
        assert manifest.auth.kind == "bearer"
        assert [tool.name for tool in manifest.tools] == list(generated_tickets.tool_names)

    def test_manifest_records_the_http_binding_for_each_tool(
        self, generated_tickets: GeneratedProject
    ) -> None:
        manifest = load_manifest(generated_tickets.directory / "tools.json")
        get_ticket = manifest.tool("get_ticket")
        assert get_ticket is not None
        assert (get_ticket.method, get_ticket.path) == ("GET", "/tickets/{ticketId}")
        assert get_ticket.parameters[0].name == "ticketId"
        assert get_ticket.read_only is True

        create_ticket = manifest.tool("create_ticket")
        assert create_ticket is not None and create_ticket.body is not None
        assert create_ticket.body.content_type == "application/json"
        assert create_ticket.read_only is False

    def test_manifest_declares_its_version_and_provenance(self, generated_tickets: GeneratedProject) -> None:
        document = json.loads((generated_tickets.directory / "tools.json").read_text(encoding="utf-8"))
        assert document["manifest_version"] == MANIFEST_VERSION
        assert document["generator"]["version"] == __version__
        assert document["generator"]["generated_at"].startswith("20")

    def test_manifest_contains_no_credentials(self, generated_tickets: GeneratedProject) -> None:
        raw = (generated_tickets.directory / "tools.json").read_text(encoding="utf-8")
        assert '"kind": "bearer"' in raw
        assert "TICKETS_API_TOKEN" in raw  # the variable name, never a value
        assert "Bearer " not in raw


class TestOverwriteRules:
    def test_refuses_to_write_into_a_non_empty_directory(
        self, tickets_service: Service, tmp_path: Path
    ) -> None:
        target = tmp_path / "server"
        target.mkdir()
        (target / "notes.md").write_text("hand written", encoding="utf-8")
        with pytest.raises(OutputError, match="--force"):
            generate(tickets_service, target, generator_version=__version__)

    def test_force_regenerates_in_place(self, tickets_service: Service, tmp_path: Path) -> None:
        target = tmp_path / "server"
        generate(tickets_service, target, generator_version=__version__)
        (target / "tools.json").write_text("{}", encoding="utf-8")
        project = generate(tickets_service, target, generator_version=__version__, force=True)
        assert load_manifest(project.directory / "tools.json").name == "tickets"

    def test_rejects_a_file_where_the_directory_should_go(
        self, tickets_service: Service, tmp_path: Path
    ) -> None:
        target = tmp_path / "server"
        target.write_text("not a directory", encoding="utf-8")
        with pytest.raises(OutputError, match="not a directory"):
            generate(tickets_service, target, generator_version=__version__)
