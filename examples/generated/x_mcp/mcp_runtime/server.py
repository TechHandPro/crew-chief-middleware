"""Connect: serve a manifest as MCP tools over stdio.

Tools are described by data (the manifest), not by generated Python functions, so
the same runtime serves any spec and specialization stays additive: filter or
reorder the manifest tools with ``customize``, or add hand-written tools with
``extra_tools``.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from .auth import MissingCredentialError, credentials_from_env
from .config import ConfigError, Settings, settings_from_env
from .http import ApiClient, ToolResult
from .manifest import Manifest, ManifestError, ToolBinding, load_manifest

ToolHandler = Callable[[dict[str, Any]], Awaitable["ToolResult | str"]]
Customize = Callable[[list[ToolBinding]], Sequence[ToolBinding]]

#: Named after the package so a vendored copy (``mcp_runtime``) logs under its own name.
_LOGGER_ROOT = __name__.split(".")[0]
logger = logging.getLogger(f"{_LOGGER_ROOT}.runtime")


@dataclass(frozen=True)
class LocalTool:
    """A hand-written tool served alongside the generated ones.

    This is the specialization seam: wrap several API calls into one high-level
    tool without editing the manifest.
    """

    name: str
    description: str
    handler: ToolHandler
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    read_only: bool = True


def build_server(
    manifest: Manifest,
    settings: Settings,
    client: ApiClient,
    *,
    extra_tools: Sequence[LocalTool] = (),
    customize: Customize | None = None,
) -> Server[None]:
    """Build an MCP server exposing ``manifest``'s tools through ``client``."""
    bindings = [tool for tool in manifest.tools if not (settings.read_only and not tool.read_only)]
    if customize is not None:
        bindings = list(customize(bindings))

    local_tools = {tool.name: tool for tool in extra_tools}
    by_name = {tool.name: tool for tool in bindings}
    descriptors = [_descriptor(tool) for tool in bindings] + [_local_descriptor(tool) for tool in extra_tools]

    async def on_list_tools(_ctx: Any, _params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=descriptors)

    async def on_call_tool(_ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        arguments = dict(params.arguments or {})
        local = local_tools.get(params.name)
        if local is not None:
            return _to_call_result(await _run_local(local, arguments))

        binding = by_name.get(params.name)
        if binding is None:
            known = ", ".join(sorted([*by_name, *local_tools])) or "none"
            return _error(f"unknown tool {params.name!r}. Available tools: {known}")

        logger.info("calling %s (%s %s)", binding.name, binding.method, binding.path)
        return _to_call_result(await client.call(binding, arguments))

    return Server(
        manifest.name,
        version=manifest.version,
        title=manifest.title,
        instructions=_instructions(manifest, settings),
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


async def serve_stdio(
    manifest_path: str | Path,
    *,
    extra_tools: Sequence[LocalTool] = (),
    customize: Customize | None = None,
    env: Mapping[str, str] | None = None,
) -> None:
    """Load a manifest and serve it on stdin/stdout until the client disconnects."""
    manifest = load_manifest(manifest_path)
    settings = settings_from_env(manifest, env)
    credentials = credentials_from_env(manifest.auth, env)
    _configure_logging(settings)

    async with ApiClient(settings, credentials) as client:
        server = build_server(manifest, settings, client, extra_tools=extra_tools, customize=customize)
        logger.info(
            "serving %s tools for %s at %s%s",
            len(manifest.tools),
            manifest.name,
            settings.base_url,
            " (read-only)" if settings.read_only else "",
        )
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())


def run_stdio(
    manifest_path: str | Path,
    *,
    extra_tools: Sequence[LocalTool] = (),
    customize: Customize | None = None,
) -> None:
    """Entry point for generated ``server.py`` scripts.

    Startup problems (missing manifest, missing credentials, bad base URL) exit
    with status 1 and a single line on stderr, which is what MCP clients surface.
    """
    try:
        anyio.run(lambda: serve_stdio(manifest_path, extra_tools=extra_tools, customize=customize))
    except (ManifestError, ConfigError, MissingCredentialError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        raise SystemExit(130) from None


def _descriptor(tool: ToolBinding) -> types.Tool:
    return types.Tool(
        name=tool.name,
        description=tool.description,
        input_schema=tool.input_schema,
        annotations=types.ToolAnnotations(
            read_only_hint=tool.read_only, destructive_hint=tool.method == "DELETE"
        ),
    )


def _local_descriptor(tool: LocalTool) -> types.Tool:
    return types.Tool(
        name=tool.name,
        description=tool.description,
        input_schema=tool.input_schema,
        annotations=types.ToolAnnotations(read_only_hint=tool.read_only),
    )


async def _run_local(tool: LocalTool, arguments: dict[str, Any]) -> ToolResult:
    try:
        result = await tool.handler(arguments)
    except Exception as exc:  # noqa: BLE001 - a custom tool must not kill the server
        logger.warning("local tool %s failed: %s", tool.name, exc)
        return ToolResult(text=f"{tool.name} failed: {exc}", is_error=True)
    return result if isinstance(result, ToolResult) else ToolResult(text=str(result))


def _to_call_result(result: ToolResult) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=result.text)],
        structured_content=result.structured,
        is_error=result.is_error,
    )


def _error(message: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=message)], is_error=True)


def _instructions(manifest: Manifest, settings: Settings) -> str:
    lines = [f"Tools for {manifest.title} ({manifest.version}) at {settings.base_url}."]
    if manifest.description:
        lines.append(manifest.description.strip()[:500])
    if settings.read_only:
        lines.append("This server is read-only: only safe, non-mutating operations are exposed.")
    lines.append("Prefer these tools over browser automation for anything this API covers.")
    return "\n\n".join(lines)


def _configure_logging(settings: Settings) -> None:
    """Log to stderr only; stdout belongs to the MCP protocol."""
    level = getattr(logging, settings.log_level, logging.WARNING)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger(_LOGGER_ROOT)
    root.handlers = [handler]
    root.setLevel(level if isinstance(level, int) else logging.WARNING)
    root.propagate = False
