"""Load and validate a generated ``tools.json`` manifest."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Bumped when the manifest layout changes in a way older runtimes cannot read.
MANIFEST_VERSION = 1

READ_ONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_SUPPORTED_METHODS = frozenset({"GET", "PUT", "POST", "DELETE", "PATCH", "HEAD", "OPTIONS"})
_SUPPORTED_LOCATIONS = frozenset({"path", "query", "header"})
_SUPPORTED_AUTH_KINDS = frozenset({"none", "bearer", "api_key", "basic"})


class ManifestError(RuntimeError):
    """The manifest is missing, malformed, or written by a newer generator."""


@dataclass(frozen=True)
class ParameterBinding:
    """Maps one tool argument onto one HTTP request parameter."""

    arg: str
    name: str
    location: str
    required: bool = False


@dataclass(frozen=True)
class BodyBinding:
    """Maps one tool argument onto the HTTP request body."""

    arg: str
    content_type: str
    required: bool = False


@dataclass(frozen=True)
class AuthConfig:
    """Which credential the server sends, and which env vars hold it."""

    kind: str = "none"
    env: dict[str, str] = field(default_factory=dict)
    location: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class ToolBinding:
    """One MCP tool and the request it performs."""

    name: str
    description: str
    input_schema: dict[str, Any]
    method: str
    path: str
    parameters: tuple[ParameterBinding, ...] = ()
    body: BodyBinding | None = None

    @property
    def read_only(self) -> bool:
        return self.method in READ_ONLY_METHODS


@dataclass(frozen=True)
class Manifest:
    """A generated service description."""

    name: str
    title: str
    version: str
    env_prefix: str
    auth: AuthConfig
    tools: tuple[ToolBinding, ...]
    description: str = ""
    base_url: str | None = None
    generator: dict[str, Any] = field(default_factory=dict)

    def tool(self, name: str) -> ToolBinding | None:
        for tool in self.tools:
            if tool.name == name:
                return tool
        return None


def load_manifest(path: str | Path) -> Manifest:
    manifest_path = Path(path).expanduser()
    if not manifest_path.is_file():
        raise ManifestError(f"manifest not found: {manifest_path}")
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{manifest_path} is not valid JSON: {exc}") from exc
    return manifest_from_dict(document)


def manifest_from_dict(document: Any) -> Manifest:
    if not isinstance(document, dict):
        raise ManifestError("manifest must be a JSON object")

    version = document.get("manifest_version")
    if version != MANIFEST_VERSION:
        raise ManifestError(
            f"manifest_version {version!r} is not supported by this runtime "
            f"(expected {MANIFEST_VERSION}); regenerate the server"
        )

    service = document.get("service")
    if not isinstance(service, dict) or not service.get("name"):
        raise ManifestError("manifest is missing a `service` object with a name")

    tools = tuple(_tool_from_dict(entry, index) for index, entry in enumerate(document.get("tools") or []))
    if not tools:
        raise ManifestError("manifest declares no tools")
    duplicates = sorted({tool.name for tool in tools if [t.name for t in tools].count(tool.name) > 1})
    if duplicates:
        raise ManifestError(f"manifest has duplicate tool names: {', '.join(duplicates)}")

    return Manifest(
        name=str(service["name"]),
        title=str(service.get("title") or service["name"]),
        version=str(service.get("version") or "0.0.0"),
        description=str(service.get("description") or ""),
        env_prefix=str(service.get("env_prefix") or "API"),
        base_url=str(service["base_url"]) if service.get("base_url") else None,
        auth=_auth_from_dict(service.get("auth")),
        tools=tools,
        generator=document.get("generator") if isinstance(document.get("generator"), dict) else {},
    )


def _auth_from_dict(raw: Any) -> AuthConfig:
    if raw is None:
        return AuthConfig()
    if not isinstance(raw, dict):
        raise ManifestError("service.auth must be an object")

    kind = str(raw.get("kind") or "none")
    if kind not in _SUPPORTED_AUTH_KINDS:
        raise ManifestError(f"unsupported auth kind {kind!r}")
    env = raw.get("env") or {}
    if not isinstance(env, dict) or not all(isinstance(value, str) for value in env.values()):
        raise ManifestError("service.auth.env must map credential names to environment variable names")
    location = raw.get("location")
    if kind == "api_key" and location not in {"header", "query"}:
        raise ManifestError("api_key auth requires location 'header' or 'query'")
    return AuthConfig(
        kind=kind,
        env={str(key): str(value) for key, value in env.items()},
        location=str(location) if location else None,
        name=str(raw["name"]) if raw.get("name") else None,
    )


def _tool_from_dict(raw: Any, index: int) -> ToolBinding:
    label = f"tools[{index}]"
    if not isinstance(raw, dict):
        raise ManifestError(f"{label} must be an object")
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise ManifestError(f"{label} is missing a name")

    request = raw.get("request")
    if not isinstance(request, dict):
        raise ManifestError(f"{label} ({name}) is missing a `request` object")
    method = str(request.get("method") or "").upper()
    if method not in _SUPPORTED_METHODS:
        raise ManifestError(f"{label} ({name}) has unsupported method {method!r}")
    path = request.get("path")
    if not isinstance(path, str) or not path.startswith("/"):
        raise ManifestError(f"{label} ({name}) has an invalid path {path!r}")

    input_schema = raw.get("input_schema")
    if not isinstance(input_schema, dict):
        raise ManifestError(f"{label} ({name}) is missing an input_schema object")

    parameters: list[ParameterBinding] = []
    for entry in request.get("parameters") or []:
        if not isinstance(entry, dict) or not entry.get("arg") or not entry.get("name"):
            raise ManifestError(f"{label} ({name}) has a malformed parameter entry")
        location = str(entry.get("location") or "query")
        if location not in _SUPPORTED_LOCATIONS:
            raise ManifestError(
                f"{label} ({name}) parameter {entry['arg']} has unsupported location {location!r}"
            )
        parameters.append(
            ParameterBinding(
                arg=str(entry["arg"]),
                name=str(entry["name"]),
                location=location,
                required=bool(entry.get("required")),
            )
        )

    body_raw = request.get("body")
    body: BodyBinding | None = None
    if body_raw is not None:
        if not isinstance(body_raw, dict) or not body_raw.get("arg"):
            raise ManifestError(f"{label} ({name}) has a malformed body binding")
        body = BodyBinding(
            arg=str(body_raw["arg"]),
            content_type=str(body_raw.get("content_type") or "application/json"),
            required=bool(body_raw.get("required")),
        )

    return ToolBinding(
        name=name,
        description=str(raw.get("description") or ""),
        input_schema=input_schema,
        method=method,
        path=path,
        parameters=tuple(parameters),
        body=body,
    )
