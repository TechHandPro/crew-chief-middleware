"""Load an OpenAPI 3.x document from a JSON or YAML file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from openapi_to_mcp.errors import SpecError

_MAX_SPEC_BYTES = 32 * 1024 * 1024


def load_spec(path: str | Path) -> dict[str, Any]:
    """Read and minimally validate an OpenAPI document."""
    spec_path = Path(path).expanduser()
    if not spec_path.is_file():
        raise SpecError(f"spec file not found: {spec_path}")
    size = spec_path.stat().st_size
    if size > _MAX_SPEC_BYTES:
        raise SpecError(f"spec file is too large ({size} bytes, limit {_MAX_SPEC_BYTES})")

    text = spec_path.read_text(encoding="utf-8")
    document = _parse(text, spec_path)
    if not isinstance(document, dict):
        raise SpecError(f"{spec_path} does not contain an OpenAPI object")

    version = str(document.get("openapi", ""))
    if not version:
        hint = (
            " This looks like a Swagger 2.0 file; convert it to OpenAPI 3 first."
            if "swagger" in document
            else ""
        )
        raise SpecError(f"{spec_path} has no `openapi` version field.{hint}")
    if not version.startswith("3."):
        raise SpecError(f"unsupported OpenAPI version {version!r}: only 3.x documents are supported")
    if not isinstance(document.get("paths"), dict) or not document["paths"]:
        raise SpecError(f"{spec_path} declares no paths, so there is nothing to expose as tools")
    return document


def _parse(text: str, spec_path: Path) -> Any:
    if spec_path.suffix.lower() == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise SpecError(f"{spec_path} is not valid JSON: {exc}") from exc
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SpecError(f"{spec_path} is not valid YAML: {exc}") from exc
