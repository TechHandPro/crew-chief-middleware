"""Specialize: filter, rename, and re-describe generated tools.

A raw spec often exposes more surface than an agent should see. Overrides keep
that curation in a small declarative file next to the spec instead of in patches
against generated code.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import yaml

from openapi_to_mcp.errors import GeneratorError
from openapi_to_mcp.model import Service, Tool

_VALID_TOOL_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")


@dataclass(frozen=True)
class ToolOverride:
    """Per-tool curation."""

    rename: str | None = None
    description: str | None = None
    hidden: bool = False


@dataclass(frozen=True)
class Overrides:
    """Curation applied after discovery and before generation."""

    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    tools: dict[str, ToolOverride] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.include and not self.exclude and not self.tools


def load_overrides(path: str | Path) -> Overrides:
    """Load an overrides file (YAML or JSON)."""
    overrides_path = Path(path).expanduser()
    if not overrides_path.is_file():
        raise GeneratorError(f"overrides file not found: {overrides_path}")

    text = overrides_path.read_text(encoding="utf-8")
    try:
        document = json.loads(text) if overrides_path.suffix.lower() == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise GeneratorError(f"{overrides_path} could not be parsed: {exc}") from exc
    if document is None:
        return Overrides()
    if not isinstance(document, dict):
        raise GeneratorError(f"{overrides_path} must contain a mapping")

    tools: dict[str, ToolOverride] = {}
    raw_tools = document.get("tools") or {}
    if not isinstance(raw_tools, dict):
        raise GeneratorError(f"{overrides_path}: `tools` must be a mapping of tool name to settings")
    for tool_name, raw in raw_tools.items():
        if not isinstance(raw, dict):
            raise GeneratorError(f"{overrides_path}: tools.{tool_name} must be a mapping")
        rename = raw.get("name") or raw.get("rename")
        if rename is not None and not _VALID_TOOL_NAME.match(str(rename)):
            raise GeneratorError(
                f"{overrides_path}: tools.{tool_name}.name {rename!r} is not a valid tool name"
            )
        tools[str(tool_name)] = ToolOverride(
            rename=str(rename) if rename else None,
            description=str(raw["description"]) if raw.get("description") else None,
            hidden=bool(raw.get("hidden", False)),
        )

    return Overrides(
        include=_string_tuple(document.get("include"), overrides_path, "include"),
        exclude=_string_tuple(document.get("exclude"), overrides_path, "exclude"),
        tools=tools,
    )


def merge_overrides(base: Overrides, *, include: tuple[str, ...], exclude: tuple[str, ...]) -> Overrides:
    """Layer command line ``--include`` / ``--exclude`` globs on top of a file."""
    return Overrides(
        include=base.include + include,
        exclude=base.exclude + exclude,
        tools=base.tools,
    )


def apply_overrides(service: Service, overrides: Overrides) -> tuple[Service, tuple[str, ...]]:
    """Return the curated service plus warnings about overrides that matched nothing."""
    if overrides.is_empty:
        return service, ()

    warnings: list[str] = []
    kept: list[Tool] = []
    for tool in service.tools:
        if overrides.include and not _matches_any(tool.name, overrides.include):
            continue
        if _matches_any(tool.name, overrides.exclude):
            continue
        settings = overrides.tools.get(tool.name)
        if settings is not None and settings.hidden:
            continue
        kept.append(_apply_tool_override(tool, settings))

    unmatched = sorted(set(overrides.tools) - set(service.tool_names))
    warnings.extend(f"overrides mention unknown tool {name!r}" for name in unmatched)

    names = [tool.name for tool in kept]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise GeneratorError(f"overrides produced duplicate tool names: {', '.join(duplicates)}")
    if not kept:
        raise GeneratorError("every tool was filtered out; loosen --include/--exclude or the overrides file")

    curated = Service(
        name=service.name,
        title=service.title,
        version=service.version,
        description=service.description,
        env_prefix=service.env_prefix,
        auth=service.auth,
        tools=tuple(kept),
        base_url=service.base_url,
    )
    return curated, tuple(warnings)


def _apply_tool_override(tool: Tool, settings: ToolOverride | None) -> Tool:
    if settings is None or (settings.rename is None and settings.description is None):
        return tool
    return Tool(
        name=settings.rename or tool.name,
        description=settings.description or tool.description,
        method=tool.method,
        path=tool.path,
        input_schema=tool.input_schema,
        parameters=tool.parameters,
        body=tool.body,
        tags=tool.tags,
        operation_id=tool.operation_id,
    )


def _matches_any(name: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatchcase(name, pattern) for pattern in patterns)


def _string_tuple(value: Any, path: Path, key: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise GeneratorError(f"{path}: `{key}` must be a string or a list of strings")
