"""The intermediate representation between an OpenAPI document and a generated server."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ParameterLocation = Literal["path", "query", "header"]
AuthKind = Literal["none", "bearer", "api_key", "basic"]

#: Methods that only read state. Generated servers can be pinned to these.
READ_ONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class Parameter:
    """One request parameter, exposed as a single tool argument."""

    arg: str
    """Tool argument name (snake_case)."""

    name: str
    """Wire name, as the API expects it."""

    location: ParameterLocation
    required: bool
    schema: dict[str, Any] = field(default_factory=dict)
    description: str | None = None


@dataclass(frozen=True)
class RequestBody:
    """A JSON (or other single-content-type) request body, exposed as one tool argument."""

    arg: str
    content_type: str
    required: bool
    schema: dict[str, Any] = field(default_factory=dict)
    description: str | None = None


@dataclass(frozen=True)
class Tool:
    """One MCP tool bound to one OpenAPI operation."""

    name: str
    description: str
    method: str
    path: str
    input_schema: dict[str, Any]
    parameters: tuple[Parameter, ...] = ()
    body: RequestBody | None = None
    tags: tuple[str, ...] = ()
    operation_id: str | None = None

    @property
    def read_only(self) -> bool:
        return self.method.upper() in READ_ONLY_METHODS


@dataclass(frozen=True)
class Auth:
    """How the generated server authenticates, and which env vars carry the secrets."""

    kind: AuthKind = "none"
    env: dict[str, str] = field(default_factory=dict)
    location: Literal["header", "query"] | None = None
    name: str | None = None
    scheme_name: str | None = None

    @property
    def required_env(self) -> tuple[str, ...]:
        return tuple(sorted(self.env.values()))


@dataclass(frozen=True)
class Service:
    """Everything needed to emit a runnable MCP server."""

    name: str
    title: str
    version: str
    description: str
    env_prefix: str
    auth: Auth
    tools: tuple[Tool, ...]
    base_url: str | None = None

    def tool(self, name: str) -> Tool:
        for candidate in self.tools:
            if candidate.name == name:
                return candidate
        raise KeyError(name)

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(tool.name for tool in self.tools)


@dataclass(frozen=True)
class Discovery:
    """A discovered service plus anything skipped along the way."""

    service: Service
    warnings: tuple[str, ...] = ()
