"""Reference resolution and OpenAPI-to-JSON-Schema translation.

Tool input schemas are plain JSON Schema, so ``$ref`` pointers into
``#/components/schemas`` are rewritten to ``#/$defs`` entries collected per tool.
Recursive schemas therefore survive translation instead of being inlined forever.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote

from openapi_to_mcp.errors import SpecError
from openapi_to_mcp.naming import to_snake_case

#: OpenAPI-only annotations that mean nothing to a JSON Schema validator.
_DROPPED_KEYWORDS = frozenset({"xml", "externalDocs", "discriminator", "nullable"})

_SCHEMA_VALUE_KEYWORDS = frozenset(
    {
        "not",
        "if",
        "then",
        "else",
        "additionalProperties",
        "unevaluatedProperties",
        "propertyNames",
        "contains",
        "unevaluatedItems",
        "additionalItems",
    }
)
_SCHEMA_LIST_KEYWORDS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
_SCHEMA_MAP_KEYWORDS = frozenset(
    {"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"}
)

_MAX_REF_HOPS = 32


class Document:
    """An OpenAPI document with local ``$ref`` resolution."""

    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = spec

    def resolve(self, node: Any) -> Any:
        """Follow ``$ref`` chains on non-schema objects (parameters, request bodies)."""
        hops = 0
        while isinstance(node, dict) and "$ref" in node:
            hops += 1
            if hops > _MAX_REF_HOPS:
                raise SpecError("$ref chain is too deep or circular outside of a schema")
            node = self.resolve_pointer(str(node["$ref"]))
        return node

    def resolve_pointer(self, ref: str) -> Any:
        if not ref.startswith("#/"):
            raise SpecError(
                f"unsupported $ref {ref!r}: only local references into this document are supported. "
                "Bundle the spec first (for example with `redocly bundle`)."
            )
        node: Any = self.spec
        for raw_token in ref[2:].split("/"):
            token = unquote(raw_token.replace("~1", "/").replace("~0", "~"))
            if isinstance(node, list):
                try:
                    node = node[int(token)]
                except (ValueError, IndexError) as exc:
                    raise SpecError(f"$ref {ref!r} does not resolve in this document") from exc
                continue
            if not isinstance(node, dict) or token not in node:
                raise SpecError(f"$ref {ref!r} does not resolve in this document")
            node = node[token]
        return node


class SchemaTranslator:
    """Translate OpenAPI schemas to JSON Schema, collecting shared ``$defs``.

    One translator is used per tool so each generated input schema carries exactly
    the definitions it needs.
    """

    def __init__(self, document: Document) -> None:
        self._document = document
        self._defs: dict[str, dict[str, Any]] = {}
        self._names_by_ref: dict[str, str] = {}

    @property
    def defs(self) -> dict[str, dict[str, Any]]:
        return self._defs

    def translate(self, schema: Any) -> Any:
        if isinstance(schema, bool):
            return schema
        if not isinstance(schema, dict):
            return {}

        if "$ref" in schema:
            name = self._register(str(schema["$ref"]))
            siblings = {
                key: self.translate(value) if key in _SCHEMA_VALUE_KEYWORDS else value
                for key, value in schema.items()
                if key != "$ref" and key not in _DROPPED_KEYWORDS
            }
            return {"$ref": f"#/$defs/{name}", **siblings}

        translated: dict[str, Any] = {}
        for key, value in schema.items():
            if key in _DROPPED_KEYWORDS:
                continue
            if key == "items":
                translated[key] = (
                    [self.translate(item) for item in value]
                    if isinstance(value, list)
                    else self.translate(value)
                )
            elif key in _SCHEMA_VALUE_KEYWORDS:
                translated[key] = self.translate(value)
            elif key in _SCHEMA_LIST_KEYWORDS and isinstance(value, list):
                translated[key] = [self.translate(item) for item in value]
            elif key in _SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
                translated[key] = {sub_key: self.translate(sub) for sub_key, sub in value.items()}
            else:
                translated[key] = value

        if schema.get("nullable") is True:
            translated = _allow_null(translated)
        return translated

    def _register(self, ref: str) -> str:
        """Add the referenced schema to ``$defs`` (once) and return its definition name."""
        known = self._names_by_ref.get(ref)
        if known is not None:
            return known

        name = _definition_name(ref)
        while name in self._defs:
            name = f"{name}_ref"
        # Reserve the name before translating so recursive schemas terminate.
        self._names_by_ref[ref] = name
        self._defs[name] = {}
        resolved = self._document.resolve_pointer(ref)
        translated = self.translate(resolved)
        self._defs[name] = translated if isinstance(translated, dict) else {}
        return name


def _definition_name(ref: str) -> str:
    """Keep the spec's own schema name (``TicketStatus``) when it is safe to reuse."""
    tail = unquote(ref.rstrip("/").rsplit("/", 1)[-1])
    cleaned = re.sub(r"[^0-9A-Za-z_.-]+", "_", tail).strip("_")
    return cleaned or to_snake_case(tail) or "schema"


def _allow_null(schema: dict[str, Any]) -> dict[str, Any]:
    declared = schema.get("type")
    if isinstance(declared, str):
        return {**schema, "type": [declared, "null"]}
    if isinstance(declared, list) and "null" not in declared:
        return {**schema, "type": [*declared, "null"]}
    return schema
