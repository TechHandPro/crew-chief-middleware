"""The HTTP half of a generated server: arguments in, API response out.

Design constraints that show up as code here:

* the host is fixed by configuration, never by tool arguments, so a model cannot
  redirect a credentialed request somewhere else;
* redirects are not followed, so credentials cannot leak to another origin;
* responses are capped, so one huge payload cannot flood an agent's context;
* only idempotent methods are retried.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import anyio
import httpx

from .auth import Credentials
from .config import Settings
from .manifest import ToolBinding

USER_AGENT = "openapi-to-mcp/0.1 (+https://github.com/crew-chief-middleware)"

_RETRY_STATUS_CODES = frozenset({429, 502, 503, 504})
_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
_MAX_RETRY_SLEEP_SECONDS = 5.0
_JSON_INDENT = 2


class ToolInputError(RuntimeError):
    """The arguments the model supplied cannot be turned into a request."""


class ReadOnlyError(RuntimeError):
    """A write tool was called while the server is pinned to read-only mode."""


@dataclass(frozen=True)
class ToolResult:
    """What the MCP layer turns into a ``CallToolResult``."""

    text: str
    structured: dict[str, Any] | None = None
    is_error: bool = False


class ApiClient:
    """Executes manifest-described requests against one API."""

    def __init__(
        self,
        settings: Settings,
        credentials: Credentials,
        *,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._credentials = credentials
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.timeout_seconds),
            follow_redirects=False,
            transport=transport,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> ApiClient:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()

    async def call(self, tool: ToolBinding, arguments: dict[str, Any] | None) -> ToolResult:
        """Run ``tool`` and return a model-facing result. Never raises for API errors."""
        try:
            request = self._build_request(tool, arguments or {})
        except (ToolInputError, ReadOnlyError) as exc:
            return ToolResult(text=str(exc), is_error=True)

        try:
            response = await self._send(tool, request)
        except httpx.HTTPError as exc:
            detail = self._credentials.redact(str(exc)) or exc.__class__.__name__
            return ToolResult(text=f"{tool.method} {tool.path} failed: {detail}", is_error=True)

        return self._build_result(tool, response)

    def _build_request(self, tool: ToolBinding, arguments: dict[str, Any]) -> httpx.Request:
        if self._settings.read_only and not tool.read_only:
            raise ReadOnlyError(
                f"{tool.name} performs {tool.method} and this server runs in read-only mode; "
                "unset the *_READ_ONLY environment variable to allow writes"
            )

        known_args = {parameter.arg for parameter in tool.parameters}
        if tool.body is not None:
            known_args.add(tool.body.arg)
        unknown = sorted(set(arguments) - known_args)
        if unknown:
            raise ToolInputError(
                f"unknown argument(s) for {tool.name}: {', '.join(unknown)}. "
                f"Accepted arguments: {', '.join(sorted(known_args)) or 'none'}"
            )

        path_values: dict[str, str] = {}
        query: dict[str, Any] = dict(self._credentials.query)
        headers: dict[str, str] = dict(self._credentials.headers)

        for parameter in tool.parameters:
            if parameter.arg not in arguments or arguments[parameter.arg] is None:
                if parameter.required:
                    raise ToolInputError(f"{tool.name} requires the {parameter.arg!r} argument")
                continue
            value = arguments[parameter.arg]
            if parameter.location == "path":
                path_values[parameter.name] = _path_segment(tool.name, parameter.arg, value)
            elif parameter.location == "query":
                query[parameter.name] = _query_value(value)
            else:
                headers[parameter.name] = _scalar(value)

        url = self._settings.base_url + _render_path(tool, path_values)
        body_kwargs = self._body_kwargs(tool, arguments, headers)
        return self._client.build_request(
            tool.method,
            url,
            params={key: value for key, value in query.items() if value is not None} or None,
            headers=headers,
            **body_kwargs,
        )

    def _body_kwargs(
        self,
        tool: ToolBinding,
        arguments: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        """Return httpx body keywords, adding a Content-Type header when needed."""
        if tool.body is None:
            return {}
        value = arguments.get(tool.body.arg)
        if value is None:
            if tool.body.required:
                raise ToolInputError(f"{tool.name} requires the {tool.body.arg!r} argument")
            return {}

        content_type = tool.body.content_type
        if content_type == "application/x-www-form-urlencoded":
            if not isinstance(value, dict):
                raise ToolInputError(f"{tool.name} expects {tool.body.arg!r} to be an object")
            return {"data": {key: _scalar(item) for key, item in value.items()}}
        if content_type == "application/json" or content_type.endswith("+json"):
            if content_type != "application/json":
                headers["Content-Type"] = content_type
            return {"json": value}
        if not isinstance(value, str):
            raise ToolInputError(f"{tool.name} expects {tool.body.arg!r} to be a raw {content_type} string")
        headers["Content-Type"] = content_type
        return {"content": value.encode("utf-8")}

    async def _send(self, tool: ToolBinding, request: httpx.Request) -> httpx.Response:
        attempts = self._settings.max_retries + 1 if tool.method in _IDEMPOTENT_METHODS else 1
        response = await self._client.send(request)
        for attempt in range(1, attempts):
            if response.status_code not in _RETRY_STATUS_CODES:
                return response
            await anyio.sleep(_retry_delay(response, attempt - 1))
            response = await self._client.send(request)
        return response

    def _build_result(self, tool: ToolBinding, response: httpx.Response) -> ToolResult:
        payload, truncated = self._decode(response)
        if isinstance(payload, str):
            text = payload
            structured: dict[str, Any] | None = None
        else:
            text = json.dumps(payload, indent=_JSON_INDENT, ensure_ascii=False)[
                : self._settings.max_response_bytes
            ]
            structured = payload if isinstance(payload, dict) else {"items": payload, "count": len(payload)}

        if truncated:
            text += f"\n\n[truncated to {self._settings.max_response_bytes} bytes]"
            structured = None

        if response.is_error:
            summary = f"HTTP {response.status_code} from {tool.method} {tool.path}"
            return ToolResult(text=self._credentials.redact(f"{summary}\n\n{text}".strip()), is_error=True)
        if not text:
            return ToolResult(text=f"HTTP {response.status_code} (empty response body)")
        return ToolResult(text=self._credentials.redact(text), structured=structured)

    def _decode(self, response: httpx.Response) -> tuple[Any, bool]:
        raw = response.content
        truncated = len(raw) > self._settings.max_response_bytes
        limited = raw[: self._settings.max_response_bytes]
        content_type = response.headers.get("content-type", "")
        if not truncated and ("json" in content_type or not content_type):
            try:
                return json.loads(limited.decode("utf-8")), False
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
        return limited.decode("utf-8", errors="replace"), truncated


def _render_path(tool: ToolBinding, path_values: dict[str, str]) -> str:
    path = tool.path
    for name, value in path_values.items():
        path = path.replace(f"{{{name}}}", value)
    if "{" in path or "}" in path:
        missing = path[path.index("{") : path.index("}") + 1] if "}" in path else path
        raise ToolInputError(f"{tool.name} is missing a path parameter for {missing}")
    return path if path.startswith("/") else f"/{path}"


def _path_segment(tool_name: str, arg: str, value: Any) -> str:
    text = _scalar(value)
    if not text:
        raise ToolInputError(f"{tool_name} requires a non-empty {arg!r}")
    return quote(text, safe="")


def _query_value(value: Any) -> Any:
    if isinstance(value, list | tuple):
        return [_scalar(item) for item in value]
    if isinstance(value, dict):
        return json.dumps(value, separators=(",", ":"))
    return _scalar(value)


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, int | float):
        return repr(value) if isinstance(value, float) else str(value)
    return json.dumps(value, separators=(",", ":"))


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("retry-after")
    if retry_after:
        try:
            return min(float(retry_after), _MAX_RETRY_SLEEP_SECONDS)
        except ValueError:
            pass
    return min(0.5 * (2**attempt), _MAX_RETRY_SLEEP_SECONDS)
