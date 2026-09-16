"""Discover: turn an OpenAPI document into MCP tool definitions.

One operation becomes one tool. Path, query, and header parameters plus the
request body become that tool's arguments, and the resulting JSON Schema is what
an agent sees when it lists tools.
"""

from __future__ import annotations

from typing import Any

from openapi_to_mcp.errors import SpecError
from openapi_to_mcp.model import (
    Auth,
    Discovery,
    Parameter,
    RequestBody,
    Service,
    Tool,
)
from openapi_to_mcp.naming import env_prefix as default_env_prefix
from openapi_to_mcp.naming import to_snake_case, tool_name, unique_name
from openapi_to_mcp.refs import Document, SchemaTranslator

HTTP_METHODS = ("get", "put", "post", "delete", "patch", "head", "options")

#: Header parameters the runtime owns; a tool argument must never fight with them.
_RESERVED_HEADERS = frozenset(
    {"authorization", "accept", "accept-encoding", "content-type", "user-agent", "host"}
)

_JSON_CONTENT = "application/json"
_FORM_CONTENT = "application/x-www-form-urlencoded"
_MAX_DESCRIPTION_CHARS = 1200


def discover(
    spec: dict[str, Any],
    *,
    name: str,
    base_url: str | None = None,
    env_prefix: str | None = None,
) -> Discovery:
    """Build a :class:`~openapi_to_mcp.model.Service` from an OpenAPI document."""
    document = Document(spec)
    warnings: list[str] = []
    info = spec.get("info") if isinstance(spec.get("info"), dict) else {}

    resolved_base_url = base_url or _server_url(spec, warnings)
    auth = _discover_auth(spec, document, env_prefix or default_env_prefix(name), warnings)
    tools = _discover_tools(spec, document, auth, warnings)
    if not tools:
        raise SpecError("no usable operations found in this spec")

    service = Service(
        name=name,
        title=str(info.get("title") or name),
        version=str(info.get("version") or "0.0.0"),
        description=str(info.get("description") or "").strip(),
        env_prefix=env_prefix or default_env_prefix(name),
        auth=auth,
        tools=tuple(tools),
        base_url=resolved_base_url,
    )
    return Discovery(service=service, warnings=tuple(warnings))


def _server_url(spec: dict[str, Any], warnings: list[str]) -> str | None:
    servers = spec.get("servers")
    if not isinstance(servers, list) or not servers:
        warnings.append(
            "spec declares no servers; set the base URL with --base-url or the *_BASE_URL env var"
        )
        return None
    first = servers[0]
    if not isinstance(first, dict) or not first.get("url"):
        warnings.append("first server entry has no url; set the base URL with --base-url")
        return None

    url = str(first["url"])
    variables = first.get("variables")
    if isinstance(variables, dict):
        for key, definition in variables.items():
            if isinstance(definition, dict) and definition.get("default") is not None:
                url = url.replace(f"{{{key}}}", str(definition["default"]))
    if "{" in url:
        warnings.append(f"server url {url!r} still has unresolved variables; override it with --base-url")
        return None
    if not url.startswith(("http://", "https://")):
        warnings.append(f"server url {url!r} is relative; set the absolute base URL with --base-url")
        return None
    return url.rstrip("/")


def _discover_auth(
    spec: dict[str, Any],
    document: Document,
    prefix: str,
    warnings: list[str],
) -> Auth:
    components = spec.get("components") if isinstance(spec.get("components"), dict) else {}
    schemes = components.get("securitySchemes") if isinstance(components.get("securitySchemes"), dict) else {}
    if not schemes:
        return Auth()

    for scheme_name in _security_scheme_order(spec, schemes):
        definition = document.resolve(schemes.get(scheme_name))
        if not isinstance(definition, dict):
            continue
        auth = _auth_from_scheme(scheme_name, definition, prefix, warnings)
        if auth is not None:
            return auth
    warnings.append("no supported security scheme found; the generated server will send no credentials")
    return Auth()


def _security_scheme_order(spec: dict[str, Any], schemes: dict[str, Any]) -> list[str]:
    """Scheme names to try, most authoritative first."""
    ordered: list[str] = []

    def add_requirements(requirements: Any) -> None:
        if not isinstance(requirements, list):
            return
        for requirement in requirements:
            if isinstance(requirement, dict):
                ordered.extend(key for key in requirement if key in schemes)

    add_requirements(spec.get("security"))
    paths = spec.get("paths") if isinstance(spec.get("paths"), dict) else {}
    for path_item in paths.values():
        if not isinstance(path_item, dict):
            continue
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if isinstance(operation, dict):
                add_requirements(operation.get("security"))
    ordered.extend(schemes.keys())

    seen: set[str] = set()
    return [name for name in ordered if not (name in seen or seen.add(name))]


def _auth_from_scheme(
    scheme_name: str,
    definition: dict[str, Any],
    prefix: str,
    warnings: list[str],
) -> Auth | None:
    scheme_type = str(definition.get("type") or "").lower()

    if scheme_type == "http":
        http_scheme = str(definition.get("scheme") or "").lower()
        if http_scheme == "bearer":
            return Auth(kind="bearer", env={"token": f"{prefix}_API_TOKEN"}, scheme_name=scheme_name)
        if http_scheme == "basic":
            return Auth(
                kind="basic",
                env={"username": f"{prefix}_USERNAME", "password": f"{prefix}_PASSWORD"},
                scheme_name=scheme_name,
            )
        warnings.append(f"security scheme {scheme_name!r} uses unsupported http scheme {http_scheme!r}")
        return None

    if scheme_type == "apikey":
        location = str(definition.get("in") or "header").lower()
        if location not in {"header", "query"}:
            warnings.append(
                f"security scheme {scheme_name!r} sends the API key in {location!r}, which is unsupported"
            )
            return None
        return Auth(
            kind="api_key",
            env={"api_key": f"{prefix}_API_KEY"},
            location="header" if location == "header" else "query",
            name=str(definition.get("name") or "X-API-Key"),
            scheme_name=scheme_name,
        )

    if scheme_type in {"oauth2", "openidconnect"}:
        warnings.append(
            f"security scheme {scheme_name!r} is {scheme_type}; the runtime sends a pre-obtained "
            f"access token from {prefix}_API_TOKEN and does not run the token flow itself"
        )
        return Auth(kind="bearer", env={"token": f"{prefix}_API_TOKEN"}, scheme_name=scheme_name)

    warnings.append(f"security scheme {scheme_name!r} has unsupported type {scheme_type!r}")
    return None


def _discover_tools(
    spec: dict[str, Any],
    document: Document,
    auth: Auth,
    warnings: list[str],
) -> list[Tool]:
    tools: list[Tool] = []
    taken: set[str] = set()
    paths = spec.get("paths") if isinstance(spec.get("paths"), dict) else {}

    for path, raw_item in paths.items():
        path_item = document.resolve(raw_item)
        if not isinstance(path_item, dict):
            warnings.append(f"skipped path {path!r}: not an object")
            continue
        shared_parameters = (
            path_item.get("parameters") if isinstance(path_item.get("parameters"), list) else []
        )

        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            tool = _build_tool(
                document=document,
                auth=auth,
                path=str(path),
                method=method.upper(),
                operation=operation,
                shared_parameters=shared_parameters,
                taken=taken,
                warnings=warnings,
            )
            taken.add(tool.name)
            tools.append(tool)
    return tools


def _build_tool(
    *,
    document: Document,
    auth: Auth,
    path: str,
    method: str,
    operation: dict[str, Any],
    shared_parameters: list[Any],
    taken: set[str],
    warnings: list[str],
) -> Tool:
    operation_id = operation.get("operationId")
    name = unique_name(tool_name(operation_id, method, path), taken)
    translator = SchemaTranslator(document)

    parameters = _build_parameters(
        document=document,
        translator=translator,
        auth=auth,
        merged=_merge_parameters(document, shared_parameters, operation.get("parameters")),
        location_label=f"{method} {path}",
        warnings=warnings,
    )
    body = _build_body(
        document=document,
        translator=translator,
        operation=operation,
        taken_args={parameter.arg for parameter in parameters},
        location_label=f"{method} {path}",
        warnings=warnings,
    )

    return Tool(
        name=name,
        description=_build_description(operation, method, path),
        method=method,
        path=path,
        input_schema=_build_input_schema(parameters, body, translator),
        parameters=tuple(parameters),
        body=body,
        tags=tuple(str(tag) for tag in operation.get("tags", []) if isinstance(tag, str)),
        operation_id=str(operation_id) if operation_id else None,
    )


def _merge_parameters(document: Document, shared: list[Any], own: Any) -> list[dict[str, Any]]:
    """Operation parameters win over path-level ones with the same name and location."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for group in (shared, own if isinstance(own, list) else []):
        for entry in group:
            resolved = document.resolve(entry)
            if not isinstance(resolved, dict) or not resolved.get("name"):
                continue
            key = (str(resolved["name"]), str(resolved.get("in") or "query"))
            merged[key] = resolved
    return list(merged.values())


def _build_parameters(
    *,
    document: Document,
    translator: SchemaTranslator,
    auth: Auth,
    merged: list[dict[str, Any]],
    location_label: str,
    warnings: list[str],
) -> list[Parameter]:
    parameters: list[Parameter] = []
    taken_args: set[str] = set()
    auth_header = (auth.name or "").lower() if auth.location == "header" else ""
    auth_query = (auth.name or "") if auth.location == "query" else ""

    for entry in merged:
        wire_name = str(entry["name"])
        location = str(entry.get("in") or "query").lower()
        if location not in {"path", "query", "header"}:
            warnings.append(
                f"{location_label}: skipped {location} parameter {wire_name!r} (unsupported location)"
            )
            continue
        if location == "header" and (
            wire_name.lower() in _RESERVED_HEADERS or wire_name.lower() == auth_header
        ):
            warnings.append(f"{location_label}: skipped header {wire_name!r} (managed by the runtime)")
            continue
        if location == "query" and auth_query and wire_name == auth_query:
            warnings.append(f"{location_label}: skipped query parameter {wire_name!r} (carries the API key)")
            continue

        arg = unique_name(to_snake_case(wire_name), taken_args)
        taken_args.add(arg)
        schema = entry.get("schema")
        translated = translator.translate(schema) if schema is not None else {"type": "string"}
        parameters.append(
            Parameter(
                arg=arg,
                name=wire_name,
                location=location,  # type: ignore[arg-type]
                required=bool(entry.get("required")) or location == "path",
                schema=translated if isinstance(translated, dict) else {},
                description=_clean_text(entry.get("description")),
            )
        )
    return parameters


def _build_body(
    *,
    document: Document,
    translator: SchemaTranslator,
    operation: dict[str, Any],
    taken_args: set[str],
    location_label: str,
    warnings: list[str],
) -> RequestBody | None:
    request_body = document.resolve(operation.get("requestBody"))
    if not isinstance(request_body, dict):
        return None
    content = request_body.get("content")
    if not isinstance(content, dict) or not content:
        return None

    content_type = _pick_content_type(content)
    media = document.resolve(content.get(content_type))
    schema = media.get("schema") if isinstance(media, dict) else None
    translated = translator.translate(schema) if schema is not None else {"type": "object"}

    if content_type not in {_JSON_CONTENT, _FORM_CONTENT} and not content_type.endswith("+json"):
        warnings.append(
            f"{location_label}: request body content type {content_type!r} is passed through as a raw string"
        )
        translated = {"type": "string", "description": f"Raw {content_type} request body."}

    arg = unique_name("body", taken_args)
    return RequestBody(
        arg=arg,
        content_type=content_type,
        required=bool(request_body.get("required")),
        schema=translated if isinstance(translated, dict) else {},
        description=_clean_text(request_body.get("description")),
    )


def _pick_content_type(content: dict[str, Any]) -> str:
    if _JSON_CONTENT in content:
        return _JSON_CONTENT
    for candidate in content:
        if str(candidate).endswith("+json"):
            return str(candidate)
    if _FORM_CONTENT in content:
        return _FORM_CONTENT
    return str(next(iter(content)))


def _build_input_schema(
    parameters: list[Parameter],
    body: RequestBody | None,
    translator: SchemaTranslator,
) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []

    for parameter in parameters:
        schema = dict(parameter.schema)
        if parameter.description and "description" not in schema:
            schema["description"] = parameter.description
        properties[parameter.arg] = schema
        if parameter.required:
            required.append(parameter.arg)

    if body is not None:
        schema = dict(body.schema)
        if body.description and "description" not in schema:
            schema["description"] = body.description
        properties[body.arg] = schema
        if body.required:
            required.append(body.arg)

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        input_schema["required"] = required
    if translator.defs:
        input_schema["$defs"] = translator.defs
    return input_schema


def _build_description(operation: dict[str, Any], method: str, path: str) -> str:
    parts: list[str] = []
    summary = _clean_text(operation.get("summary"))
    description = _clean_text(operation.get("description"))
    if summary:
        parts.append(summary)
    if description and description != summary:
        parts.append(description)
    if operation.get("deprecated"):
        parts.append("Deprecated by the API provider.")
    parts.append(f"Calls {method} {path}.")

    text = "\n\n".join(parts)
    if len(text) > _MAX_DESCRIPTION_CHARS:
        text = text[: _MAX_DESCRIPTION_CHARS - 3].rstrip() + "..."
    return text


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
