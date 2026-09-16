"""Generate: write a standalone MCP server project for a discovered service.

The generated project is deliberately small: a ``tools.json`` manifest, a vendored
copy of :mod:`openapi_to_mcp.runtime` (as ``mcp_runtime``), and a ``server.py``
entry point. Regenerating a service rewrites data, not hand-edited logic.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path

from openapi_to_mcp.errors import OutputError
from openapi_to_mcp.manifest import build_manifest
from openapi_to_mcp.model import Auth, Service
from openapi_to_mcp.naming import module_name

RUNTIME_PACKAGE_NAME = "mcp_runtime"
MANIFEST_FILENAME = "tools.json"

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
_TEMPLATE_FILES = {
    "server.py.tmpl": "server.py",
    "requirements.txt.tmpl": "requirements.txt",
    "env.example.tmpl": ".env.example",
    "gitignore.tmpl": ".gitignore",
    "README.md.tmpl": "README.md",
    "mcp.example.json.tmpl": "mcp.example.json",
    "Dockerfile.tmpl": "Dockerfile",
}


@dataclass(frozen=True)
class GeneratedProject:
    """Where the server was written, and what it contains."""

    directory: Path
    files: tuple[Path, ...]
    tool_names: tuple[str, ...]

    @property
    def server_script(self) -> Path:
        return self.directory / "server.py"


def generate(
    service: Service,
    out_dir: str | Path,
    *,
    generator_version: str,
    force: bool = False,
    generated_at: datetime | None = None,
) -> GeneratedProject:
    """Write the generated MCP server project for ``service`` into ``out_dir``."""
    directory = Path(out_dir).expanduser()
    _prepare_directory(directory, force=force)

    manifest = build_manifest(service, generator_version=generator_version, generated_at=generated_at)
    written: list[Path] = [
        _write(directory / MANIFEST_FILENAME, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    ]

    context = _template_context(service, generator_version=generator_version)
    for template_name, output_name in _TEMPLATE_FILES.items():
        written.append(_write(directory / output_name, _render(template_name, context)))
    written.extend(_vendor_runtime(directory))

    return GeneratedProject(
        directory=directory,
        files=tuple(sorted(written)),
        tool_names=service.tool_names,
    )


def _prepare_directory(directory: Path, *, force: bool) -> None:
    if directory.exists():
        if not directory.is_dir():
            raise OutputError(f"{directory} exists and is not a directory")
        occupied = [entry.name for entry in directory.iterdir() if not entry.name.startswith(".")]
        if occupied and not force:
            raise OutputError(f"{directory} is not empty; pass --force to overwrite the generated files")
    directory.mkdir(parents=True, exist_ok=True)


def _vendor_runtime(directory: Path) -> list[Path]:
    """Copy the runtime package so the generated server has no dependency on this tool."""
    target = directory / RUNTIME_PACKAGE_NAME
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    runtime_root = resources.files("openapi_to_mcp.runtime")
    for entry in sorted(runtime_root.iterdir(), key=lambda item: item.name):
        if not entry.name.endswith(".py"):
            continue
        written.append(_write(target / entry.name, entry.read_text(encoding="utf-8")))
    if not any(path.name == "__init__.py" for path in written):
        raise OutputError("runtime package is missing __init__.py; the installation looks broken")
    return written


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _render(template_name: str, context: dict[str, str]) -> str:
    template = resources.files("openapi_to_mcp.templates").joinpath(template_name).read_text(encoding="utf-8")

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in context:
            raise OutputError(f"template {template_name} references unknown placeholder {{{{{key}}}}}")
        return context[key]

    return _PLACEHOLDER.sub(replace, template)


def _template_context(service: Service, *, generator_version: str) -> dict[str, str]:
    prefix = service.env_prefix
    return {
        "name": service.name,
        "module": module_name(service.name),
        "title": service.title,
        "api_version": service.version,
        "description": service.description.strip().splitlines()[0]
        if service.description.strip()
        else service.title,
        "env_prefix": prefix,
        "base_url": service.base_url or f"(not in the spec: set {prefix}_BASE_URL)",
        "base_url_json": service.base_url or "https://api.example.com",
        "runtime_package": RUNTIME_PACKAGE_NAME,
        "manifest_filename": MANIFEST_FILENAME,
        "generator_version": generator_version,
        "tool_count": str(len(service.tools)),
        "tool_table": _tool_table(service),
        "credential_env_lines": _credential_env_lines(service.auth),
        "credential_env_docs": _credential_env_docs(service.auth),
        "auth_kind": service.auth.kind,
        "example_tool": service.tools[0].name if service.tools else "list_items",
    }


def _tool_table(service: Service) -> str:
    rows = ["| Tool | Method | Path | Read-only |", "| --- | --- | --- | --- |"]
    rows.extend(
        f"| `{tool.name}` | {tool.method} | `{tool.path}` | {'yes' if tool.read_only else 'no'} |"
        for tool in service.tools
    )
    return "\n".join(rows)


def _credential_env_lines(auth: Auth) -> str:
    if auth.kind == "none":
        return "# This API declares no supported security scheme, so no credentials are sent."
    return "\n".join(f"{variable}=" for variable in auth.required_env)


def _credential_env_docs(auth: Auth) -> str:
    if auth.kind == "none":
        return "| _(none)_ | this API declares no supported security scheme |"
    labels = {
        "token": "bearer token (or a pre-obtained OAuth2 access token)",
        "api_key": "API key",
        "username": "basic auth username",
        "password": "basic auth password",
    }
    return "\n".join(
        f"| `{variable}` | {labels.get(key, 'credential')} |" for key, variable in sorted(auth.env.items())
    )
