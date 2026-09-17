"""The curated Meta Graph Pages spec stays SOCIAL-sized and generator-friendly."""

from __future__ import annotations

import json
from typing import Any

import pytest
from tests.conftest import META_GRAPH_OVERRIDES, META_GRAPH_SPEC, REPO_ROOT

from openapi_to_mcp.cli import main
from openapi_to_mcp.discovery import discover
from openapi_to_mcp.model import Service
from openapi_to_mcp.overrides import apply_overrides, load_overrides

# SOCIAL needs Page metadata, feed/posts, comments, engagement, insights, and
# URL-based photo/video publish. Keep this list the source of truth for size.
EXPECTED_META_GRAPH_TOOLS = (
    "get_current_page",
    "list_managed_pages",
    "get_page",
    "list_page_feed",
    "create_page_post",
    "list_page_posts",
    "get_post",
    "list_post_comments",
    "create_post_comment",
    "list_post_likes",
    "get_comment",
    "list_comment_replies",
    "reply_to_comment",
    "list_page_insights",
    "list_post_insights",
    "list_page_photos",
    "publish_page_photo",
    "list_page_videos",
    "publish_page_video",
)
WRITE_TOOLS = frozenset(
    {
        "create_page_post",
        "create_post_comment",
        "reply_to_comment",
        "publish_page_photo",
        "publish_page_video",
    }
)
_OUT_OF_SCOPE_PATHS = ("video_reels", "private_replies", "rupload", "/stories")
_SECRET_MARKERS = ("EAA", "EAAB", "access_token=", "sk_live", "BEGIN PRIVATE")
_MAX_OPERATIONS = 25
_CLEAN_BODY_TYPES = frozenset({"application/json", "application/x-www-form-urlencoded"})


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


class TestSpecStaysPageScoped:
    def test_is_a_small_openapi_3_document(self, meta_graph_spec: dict[str, Any]) -> None:
        assert str(meta_graph_spec["openapi"]).startswith("3.")
        operations = _operations(meta_graph_spec)
        assert operations, "the Pages spec must declare operations"
        assert len(operations) <= _MAX_OPERATIONS

    def test_targets_graph_v24_with_a_page_token_scheme(self, meta_graph_spec: dict[str, Any]) -> None:
        servers = meta_graph_spec["servers"]
        assert servers[0]["url"] == "https://graph.facebook.com/v24.0"
        schemes = meta_graph_spec["components"]["securitySchemes"]
        assert "bearerAuth" in schemes
        assert schemes["bearerAuth"]["type"] == "http"
        assert schemes["bearerAuth"]["scheme"] == "bearer"

    def test_omits_messenger_reels_and_other_graph_surfaces(self, meta_graph_spec: dict[str, Any]) -> None:
        paths = " ".join(meta_graph_spec["paths"])
        for fragment in _OUT_OF_SCOPE_PATHS:
            assert fragment not in paths

    def test_page_schema_does_not_invite_token_exfiltration(self, meta_graph_spec: dict[str, Any]) -> None:
        page_props = meta_graph_spec["components"]["schemas"]["Page"]["properties"]
        assert "access_token" not in page_props
        field_defaults = [
            parameter["schema"].get("default", "")
            for parameter in meta_graph_spec["components"]["parameters"].values()
            if isinstance(parameter, dict) and parameter.get("name") == "fields"
        ]
        assert field_defaults
        assert all("access_token" not in str(default) for default in field_defaults)

    def test_photo_and_video_publish_use_url_bodies_the_runtime_can_send(
        self, meta_graph_spec: dict[str, Any]
    ) -> None:
        photo = meta_graph_spec["paths"]["/{page-id}/photos"]["post"]["requestBody"]["content"]
        video = meta_graph_spec["paths"]["/{page-id}/videos"]["post"]["requestBody"]["content"]
        assert set(photo) <= _CLEAN_BODY_TYPES
        assert set(video) <= _CLEAN_BODY_TYPES
        assert "multipart/form-data" not in photo
        assert "multipart/form-data" not in video
        photo_schema = _resolve_schema(meta_graph_spec, photo[next(iter(photo))]["schema"])
        video_schema = _resolve_schema(meta_graph_spec, video[next(iter(video))]["schema"])
        assert "url" in photo_schema["properties"]
        assert "file_url" in video_schema["properties"]

    def test_checked_in_sources_contain_no_credential_material(self) -> None:
        for path in (
            META_GRAPH_SPEC,
            META_GRAPH_OVERRIDES,
            REPO_ROOT / "examples" / "meta-graph-pages.md",
        ):
            text = path.read_text(encoding="utf-8")
            for marker in _SECRET_MARKERS:
                assert marker not in text, f"{path} looks like it contains a secret marker {marker!r}"


class TestDiscoveryAndOverrides:
    def test_name_prefix_is_meta_graph_api_token(self, meta_graph_service: Service) -> None:
        assert meta_graph_service.name == "meta_graph"
        assert meta_graph_service.env_prefix == "META_GRAPH"
        assert meta_graph_service.auth.kind == "bearer"
        assert meta_graph_service.auth.required_env == ("META_GRAPH_API_TOKEN",)
        assert meta_graph_service.base_url == "https://graph.facebook.com/v24.0"

    def test_curated_tool_list_is_exactly_the_social_page_surface(self, meta_graph_service: Service) -> None:
        assert meta_graph_service.tool_names == EXPECTED_META_GRAPH_TOOLS

    def test_write_tools_exist_and_are_gated_by_read_only_classification(
        self, meta_graph_service: Service
    ) -> None:
        for name in EXPECTED_META_GRAPH_TOOLS:
            tool = meta_graph_service.tool(name)
            if name in WRITE_TOOLS:
                assert tool.read_only is False
            else:
                assert tool.read_only is True

    def test_discovery_without_overrides_still_maps_every_operation(
        self, meta_graph_spec: dict[str, Any]
    ) -> None:
        raw = discover(meta_graph_spec, name="meta_graph").service
        curated, warnings = apply_overrides(raw, load_overrides(META_GRAPH_OVERRIDES))
        assert warnings == ()
        assert len(raw.tools) == len(curated.tools) == len(EXPECTED_META_GRAPH_TOOLS)


class TestListToolsSmoke:
    def test_list_tools_table_includes_page_feed_and_read_only_writes(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(
            [
                "list-tools",
                "--spec",
                str(META_GRAPH_SPEC),
                "--name",
                "meta_graph",
                "--overrides",
                str(META_GRAPH_OVERRIDES),
            ]
        )
        output = capsys.readouterr().out
        assert exit_code == 0
        assert "auth: bearer" in output
        assert "list_page_feed" in output and "GET    /{page-id}/feed" in output
        assert "create_page_post" in output and "POST   /{page-id}/feed" in output
        assert str(len(EXPECTED_META_GRAPH_TOOLS)) in output

    def test_list_tools_json_reports_the_page_token_env_var(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(
            [
                "list-tools",
                "--spec",
                str(META_GRAPH_SPEC),
                "--name",
                "meta_graph",
                "--overrides",
                str(META_GRAPH_OVERRIDES),
                "--json",
            ]
        )
        payload = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        assert payload["service"]["required_env"] == ["META_GRAPH_API_TOKEN"]
        assert payload["service"]["base_url"] == "https://graph.facebook.com/v24.0"
        names = [tool["name"] for tool in payload["tools"]]
        assert names == list(EXPECTED_META_GRAPH_TOOLS)
        create = next(tool for tool in payload["tools"] if tool["name"] == "create_page_post")
        assert create["read_only"] is False
        get_page = next(tool for tool in payload["tools"] if tool["name"] == "get_page")
        assert get_page["read_only"] is True
        assert get_page["path"] == "/{page-id}"
