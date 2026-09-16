"""Serialize a discovered service into the ``tools.json`` manifest a runtime reads."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from openapi_to_mcp.model import Service, Tool
from openapi_to_mcp.runtime.manifest import MANIFEST_VERSION


def build_manifest(
    service: Service, *, generator_version: str, generated_at: datetime | None = None
) -> dict[str, Any]:
    """Build the manifest document. Deterministic apart from ``generated_at``."""
    timestamp = (generated_at or datetime.now(UTC)).replace(microsecond=0)
    return {
        "manifest_version": MANIFEST_VERSION,
        "generator": {
            "name": "openapi-to-mcp",
            "version": generator_version,
            "generated_at": timestamp.isoformat(),
        },
        "service": {
            "name": service.name,
            "title": service.title,
            "version": service.version,
            "description": service.description,
            "env_prefix": service.env_prefix,
            "base_url": service.base_url,
            "auth": _auth(service),
        },
        "tools": [_tool(tool) for tool in service.tools],
    }


def _auth(service: Service) -> dict[str, Any]:
    auth = service.auth
    payload: dict[str, Any] = {"kind": auth.kind, "env": dict(auth.env)}
    if auth.location:
        payload["location"] = auth.location
    if auth.name:
        payload["name"] = auth.name
    if auth.scheme_name:
        payload["scheme_name"] = auth.scheme_name
    return payload


def _tool(tool: Tool) -> dict[str, Any]:
    request: dict[str, Any] = {
        "method": tool.method,
        "path": tool.path,
        "parameters": [
            {
                "arg": parameter.arg,
                "name": parameter.name,
                "location": parameter.location,
                "required": parameter.required,
            }
            for parameter in tool.parameters
        ],
    }
    if tool.body is not None:
        request["body"] = {
            "arg": tool.body.arg,
            "content_type": tool.body.content_type,
            "required": tool.body.required,
        }

    payload: dict[str, Any] = {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
        "request": request,
        "read_only": tool.read_only,
    }
    if tool.operation_id:
        payload["operation_id"] = tool.operation_id
    if tool.tags:
        payload["tags"] = list(tool.tags)
    return payload
