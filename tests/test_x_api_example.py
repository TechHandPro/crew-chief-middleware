"""The curated X API Posts spec stays write-sized and generator-friendly."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from tests.conftest import REPO_ROOT, X_API_OVERRIDES, X_API_SPEC
from tests.test_runtime_http import Recorder

from openapi_to_mcp import __version__
from openapi_to_mcp.cli import main
from openapi_to_mcp.discovery import discover
from openapi_to_mcp.generator import generate
from openapi_to_mcp.model import Service
from openapi_to_mcp.overrides import apply_overrides, load_overrides
from openapi_to_mcp.runtime.auth import Credentials
from openapi_to_mcp.runtime.config import Settings
from openapi_to_mcp.runtime.http import ApiClient
from openapi_to_mcp.runtime.manifest import load_manifest

EXPECTED_X_API_TOOLS = (
    "get_me",
    "get_post",
    "create_post",
    "upload_media",
)
WRITE_TOOLS = frozenset({"create_post", "upload_media"})
_OUT_OF_SCOPE_PATHS = (
    "/1.1/",
    "upload.twitter.com",
    "/initialize",
    "/append",
    "/finalize",
    "/2/dm",
    "/2/tweets/search",
)
_SECRET_MARKERS = ("sk_live", "BEGIN PRIVATE", "oauth_token_secret")
_MAX_OPERATIONS = 10
_CLEAN_BODY_TYPES = frozenset({"application/json", "application/x-www-form-urlencoded"})
_X_BASE = "https://api.x.com"


def _resolve_schema(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return schema
    node: Any = spec
    for part in ref[2:].split("/"):
        node = node[part]
    if not isinstance(node, dict):
        raise AssertionError(f"{ref} did not resolve to an object schema")
    return node


def _operations(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    found: list[tuple[str, str, dict[str, Any]]] = []
    for path, item in spec.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method.lower() in {"get", "put", "post", "delete", "patch", "head", "options"} and isinstance(
                operation, dict
            ):
                found.append((method.upper(), path, operation))
    return found


def _x_client(recorder: Recorder, **settings_kwargs: Any) -> ApiClient:
    settings = Settings(base_url=_X_BASE, max_retries=0, **settings_kwargs)
    credentials = Credentials(
        headers={"Authorization": "Bearer token-value-1234"}, secrets=("token-value-1234",)
    )
    return ApiClient(settings, credentials, transport=recorder.transport())


class TestSpecStaysPostScoped:
    def test_is_a_small_openapi_3_document(self, x_api_spec: dict[str, Any]) -> None:
        assert str(x_api_spec["openapi"]).startswith("3.")
        operations = _operations(x_api_spec)
        assert operations, "the X Posts spec must declare operations"
        assert len(operations) <= _MAX_OPERATIONS

    def test_targets_api_x_com_with_a_user_bearer_scheme(self, x_api_spec: dict[str, Any]) -> None:
        servers = x_api_spec["servers"]
        assert servers[0]["url"] == _X_BASE
        schemes = x_api_spec["components"]["securitySchemes"]
        assert "bearerAuth" in schemes
        assert schemes["bearerAuth"]["type"] == "http"
        assert schemes["bearerAuth"]["scheme"] == "bearer"

    def test_omits_v1_chunked_upload_and_other_x_surfaces(self, x_api_spec: dict[str, Any]) -> None:
        paths = " ".join(x_api_spec["paths"])
        for fragment in _OUT_OF_SCOPE_PATHS:
            assert fragment not in paths

    def test_create_post_maps_quote_and_media_ids(self, x_api_spec: dict[str, Any]) -> None:
        content = x_api_spec["paths"]["/2/tweets"]["post"]["requestBody"]["content"]
        assert set(content) <= _CLEAN_BODY_TYPES
        assert "application/json" in content
        schema = _resolve_schema(x_api_spec, content["application/json"]["schema"])
        assert "text" in schema["properties"]
        assert "quote_tweet_id" in schema["properties"]
        media = _resolve_schema(x_api_spec, schema["properties"]["media"])
        assert "media_ids" in media["properties"]
        reply = _resolve_schema(x_api_spec, schema["properties"]["reply"])
        assert "in_reply_to_tweet_id" in reply["properties"]

    def test_image_upload_uses_json_base64_not_multipart(self, x_api_spec: dict[str, Any]) -> None:
        content = x_api_spec["paths"]["/2/media/upload"]["post"]["requestBody"]["content"]
        assert set(content) <= _CLEAN_BODY_TYPES
        assert "multipart/form-data" not in content
        schema = _resolve_schema(x_api_spec, content[next(iter(content))]["schema"])
        assert schema["required"] == ["media", "media_category"]
        assert schema["properties"]["media"]["format"] == "byte"
        assert "tweet_image" in schema["properties"]["media_category"]["enum"]

    def test_checked_in_sources_contain_no_credential_material(self) -> None:
        for path in (X_API_SPEC, X_API_OVERRIDES, REPO_ROOT / "examples" / "x-api.md"):
            text = path.read_text(encoding="utf-8")
            for marker in _SECRET_MARKERS:
                assert marker not in text, f"{path} looks like it contains a secret marker {marker!r}"


class TestDiscoveryAndOverrides:
    def test_name_prefix_is_x_api_token(self, x_api_service: Service) -> None:
        assert x_api_service.name == "x"
        assert x_api_service.env_prefix == "X"
        assert x_api_service.auth.kind == "bearer"
        assert x_api_service.auth.required_env == ("X_API_TOKEN",)
        assert x_api_service.base_url == _X_BASE

    def test_curated_tool_list_is_exactly_the_write_surface(self, x_api_service: Service) -> None:
        assert x_api_service.tool_names == EXPECTED_X_API_TOOLS

    def test_write_tools_exist_and_are_gated_by_read_only_classification(
        self, x_api_service: Service
    ) -> None:
        for name in EXPECTED_X_API_TOOLS:
            tool = x_api_service.tool(name)
            if name in WRITE_TOOLS:
                assert tool.read_only is False
            else:
                assert tool.read_only is True

    def test_discovery_without_overrides_still_maps_every_operation(self, x_api_spec: dict[str, Any]) -> None:
        raw = discover(x_api_spec, name="x").service
        curated, warnings = apply_overrides(raw, load_overrides(X_API_OVERRIDES))
        assert warnings == ()
        assert len(raw.tools) == len(curated.tools) == len(EXPECTED_X_API_TOOLS)

    def test_create_post_and_upload_media_bind_json_bodies(self, x_api_service: Service) -> None:
        create = x_api_service.tool("create_post")
        upload = x_api_service.tool("upload_media")
        assert create.method == "POST" and create.path == "/2/tweets"
        assert create.body is not None and create.body.content_type == "application/json"
        assert upload.method == "POST" and upload.path == "/2/media/upload"
        assert upload.body is not None and upload.body.content_type == "application/json"


class TestListToolsSmoke:
    def test_list_tools_table_includes_create_post_and_upload_media(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(
            [
                "list-tools",
                "--spec",
                str(X_API_SPEC),
                "--name",
                "x",
                "--overrides",
                str(X_API_OVERRIDES),
            ]
        )
        output = capsys.readouterr().out
        assert exit_code == 0
        assert "auth: bearer" in output
        assert "get_me" in output and "GET    /2/users/me" in output
        assert "create_post" in output and "POST   /2/tweets" in output
        assert "upload_media" in output and "POST   /2/media/upload" in output
        assert str(len(EXPECTED_X_API_TOOLS)) in output

    def test_list_tools_json_reports_the_user_token_env_var(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(
            [
                "list-tools",
                "--spec",
                str(X_API_SPEC),
                "--name",
                "x",
                "--overrides",
                str(X_API_OVERRIDES),
                "--json",
            ]
        )
        payload = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        assert payload["service"]["required_env"] == ["X_API_TOKEN"]
        assert payload["service"]["base_url"] == _X_BASE
        names = [tool["name"] for tool in payload["tools"]]
        assert names == list(EXPECTED_X_API_TOOLS)
        create = next(tool for tool in payload["tools"] if tool["name"] == "create_post")
        assert create["read_only"] is False
        get_me = next(tool for tool in payload["tools"] if tool["name"] == "get_me")
        assert get_me["read_only"] is True
        assert get_me["path"] == "/2/users/me"


@pytest.mark.anyio
class TestAdapterRequestMapping:
    """Generated tools.json plus runtime HTTP mapping (registration, not a live X call)."""

    async def test_create_post_sends_json_quote_without_media(
        self, x_api_service: Service, tmp_path: Path
    ) -> None:
        project = generate(x_api_service, tmp_path / "x_mcp", generator_version=__version__)
        manifest = load_manifest(project.directory / "tools.json")
        tool = manifest.tool("create_post")
        assert tool is not None
        recorder = Recorder(httpx.Response(201, json={"data": {"id": "123", "text": "quoted"}}))
        async with _x_client(recorder) as client:
            result = await client.call(
                tool,
                {"body": {"text": "commentary", "quote_tweet_id": "9876543210"}},
            )
        assert result.is_error is False
        assert str(recorder.last.url) == f"{_X_BASE}/2/tweets"
        assert recorder.last.method == "POST"
        assert recorder.last.headers["authorization"] == "Bearer token-value-1234"
        assert recorder.last.headers["content-type"] == "application/json"
        assert json.loads(recorder.last.content) == {"text": "commentary", "quote_tweet_id": "9876543210"}

    async def test_create_post_sends_json_media_ids(self, x_api_service: Service, tmp_path: Path) -> None:
        project = generate(x_api_service, tmp_path / "x_mcp", generator_version=__version__)
        manifest = load_manifest(project.directory / "tools.json")
        tool = manifest.tool("create_post")
        assert tool is not None
        recorder = Recorder(httpx.Response(201, json={"data": {"id": "1", "text": "photo"}}))
        async with _x_client(recorder) as client:
            await client.call(
                tool,
                {"body": {"text": "photo of the day", "media": {"media_ids": ["1880028106020515840"]}}},
            )
        assert json.loads(recorder.last.content) == {
            "text": "photo of the day",
            "media": {"media_ids": ["1880028106020515840"]},
        }

    async def test_upload_media_sends_json_base64_not_multipart(
        self, x_api_service: Service, tmp_path: Path
    ) -> None:
        project = generate(x_api_service, tmp_path / "x_mcp", generator_version=__version__)
        manifest = load_manifest(project.directory / "tools.json")
        tool = manifest.tool("upload_media")
        assert tool is not None
        recorder = Recorder(httpx.Response(200, json={"data": {"id": "1880", "media_key": "3_1880"}}))
        payload = {"media": "aGVsbG8=", "media_category": "tweet_image", "media_type": "image/png"}
        async with _x_client(recorder) as client:
            result = await client.call(tool, {"body": payload})
        assert result.is_error is False
        assert str(recorder.last.url) == f"{_X_BASE}/2/media/upload"
        assert recorder.last.headers["content-type"] == "application/json"
        assert "multipart" not in recorder.last.headers.get("content-type", "")
        assert json.loads(recorder.last.content) == payload

    async def test_read_only_mode_hides_writes_before_they_leave_the_process(
        self, x_api_service: Service, tmp_path: Path
    ) -> None:
        project = generate(x_api_service, tmp_path / "x_mcp", generator_version=__version__)
        manifest = load_manifest(project.directory / "tools.json")
        tool = manifest.tool("create_post")
        assert tool is not None
        recorder = Recorder()
        async with _x_client(recorder, read_only=True) as client:
            result = await client.call(tool, {"body": {"text": "nope"}})
        assert result.is_error and "read-only mode" in result.text
        assert recorder.requests == []

    async def test_get_me_sends_user_fields_query_wire_name(
        self, x_api_service: Service, tmp_path: Path
    ) -> None:
        project = generate(x_api_service, tmp_path / "x_mcp", generator_version=__version__)
        manifest = load_manifest(project.directory / "tools.json")
        tool = manifest.tool("get_me")
        assert tool is not None
        recorder = Recorder(httpx.Response(200, json={"data": {"id": "1", "username": "demo"}}))
        async with _x_client(recorder) as client:
            await client.call(tool, {"user_fields": "id,username"})
        assert recorder.last.url.path == "/2/users/me"
        assert recorder.last.url.params.multi_items() == [("user.fields", "id,username")]
