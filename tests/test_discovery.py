"""OpenAPI document in, MCP tool list out."""

from __future__ import annotations

from typing import Any

import pytest

from openapi_to_mcp.discovery import discover
from openapi_to_mcp.errors import SpecError
from openapi_to_mcp.model import Service


def build_spec(**overrides: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {"title": "Widgets", "version": "2.0.0"},
        "servers": [{"url": "https://api.example.com/v2"}],
        "paths": {
            "/widgets": {
                "get": {"operationId": "listWidgets", "responses": {"200": {"description": "ok"}}},
            }
        },
    }
    spec.update(overrides)
    return spec


class TestSampleSpec:
    def test_every_operation_becomes_one_tool_in_document_order(self, tickets_service: Service) -> None:
        assert tickets_service.tool_names == (
            "list_tickets",
            "create_ticket",
            "get_ticket",
            "delete_ticket",
            "update_ticket",
            "list_ticket_comments",
            "add_ticket_comment",
        )

    def test_service_metadata_comes_from_info_and_servers(self, tickets_service: Service) -> None:
        assert tickets_service.title == "Example Tickets API"
        assert tickets_service.version == "1.4.0"
        assert tickets_service.base_url == "https://tickets.example.com/api/v1"
        assert tickets_service.env_prefix == "TICKETS"

    def test_bearer_security_scheme_maps_to_one_token_env_var(self, tickets_service: Service) -> None:
        assert tickets_service.auth.kind == "bearer"
        assert tickets_service.auth.required_env == ("TICKETS_API_TOKEN",)

    def test_query_parameters_become_optional_arguments(self, tickets_service: Service) -> None:
        schema = tickets_service.tool("list_tickets").input_schema
        assert sorted(schema["properties"]) == ["assignee", "cursor", "limit", "status", "tag"]
        assert "required" not in schema
        assert schema["additionalProperties"] is False
        assert schema["properties"]["limit"]["maximum"] == 100

    def test_path_parameters_are_required_and_snake_cased(self, tickets_service: Service) -> None:
        tool = tickets_service.tool("get_ticket")
        assert tool.input_schema["required"] == ["ticket_id"]
        assert [(parameter.arg, parameter.name, parameter.location) for parameter in tool.parameters] == [
            ("ticket_id", "ticketId", "path")
        ]

    def test_path_level_parameters_are_merged_into_each_operation(self, tickets_service: Service) -> None:
        for name in ("get_ticket", "update_ticket", "delete_ticket", "list_ticket_comments"):
            assert "ticket_id" in tickets_service.tool(name).input_schema["properties"]

    def test_referenced_schemas_are_collected_as_defs(self, tickets_service: Service) -> None:
        schema = tickets_service.tool("list_tickets").input_schema
        assert schema["properties"]["status"]["$ref"] == "#/$defs/TicketStatus"
        assert schema["$defs"]["TicketStatus"]["enum"] == ["open", "pending", "solved", "closed"]

    def test_request_body_becomes_a_single_body_argument(self, tickets_service: Service) -> None:
        tool = tickets_service.tool("create_ticket")
        assert tool.body is not None
        assert (tool.body.arg, tool.body.content_type, tool.body.required) == (
            "body",
            "application/json",
            True,
        )
        assert tool.input_schema["required"] == ["body"]
        assert tool.input_schema["properties"]["body"]["$ref"] == "#/$defs/TicketCreate"

    def test_nullable_fields_translate_to_a_json_schema_type_union(self, tickets_service: Service) -> None:
        defs = tickets_service.tool("update_ticket").input_schema["$defs"]
        assert defs["TicketUpdate"]["properties"]["assignee"]["type"] == ["string", "null"]

    def test_read_only_reflects_the_http_method(self, tickets_service: Service) -> None:
        assert tickets_service.tool("get_ticket").read_only is True
        assert tickets_service.tool("delete_ticket").read_only is False

    def test_descriptions_carry_summary_and_the_underlying_call(self, tickets_service: Service) -> None:
        description = tickets_service.tool("get_ticket").description
        assert description.startswith("Get one ticket")
        assert "Calls GET /tickets/{ticketId}" in description


class TestNamingAndFallbacks:
    def test_operations_without_an_operation_id_are_named_from_method_and_path(self) -> None:
        spec = build_spec(
            paths={"/widgets/{widgetId}/parts": {"get": {"responses": {"200": {"description": "ok"}}}}}
        )
        assert discover(spec, name="widgets").service.tool_names == ("get_widgets_by_widget_id_parts",)

    def test_duplicate_operation_ids_are_disambiguated(self) -> None:
        spec = build_spec(
            paths={
                "/a": {"get": {"operationId": "fetch", "responses": {"200": {"description": "ok"}}}},
                "/b": {"get": {"operationId": "fetch", "responses": {"200": {"description": "ok"}}}},
            }
        )
        assert discover(spec, name="dup").service.tool_names == ("fetch", "fetch_2")

    def test_env_prefix_is_derived_from_the_service_name(self) -> None:
        assert discover(build_spec(), name="help-desk").service.env_prefix == "HELP_DESK"

    def test_explicit_base_url_overrides_the_spec(self) -> None:
        service = discover(build_spec(), name="widgets", base_url="https://staging.example.com").service
        assert service.base_url == "https://staging.example.com"

    def test_server_variables_use_their_defaults(self) -> None:
        spec = build_spec(
            servers=[{"url": "https://{tenant}.example.com/v1", "variables": {"tenant": {"default": "acme"}}}]
        )
        assert discover(spec, name="widgets").service.base_url == "https://acme.example.com/v1"


class TestAuthDiscovery:
    def test_api_key_in_header(self) -> None:
        spec = build_spec(
            components={"securitySchemes": {"key": {"type": "apiKey", "in": "header", "name": "X-Api-Key"}}},
            security=[{"key": []}],
        )
        auth = discover(spec, name="widgets").service.auth
        assert (auth.kind, auth.location, auth.name) == ("api_key", "header", "X-Api-Key")
        assert auth.required_env == ("WIDGETS_API_KEY",)

    def test_api_key_in_query(self) -> None:
        spec = build_spec(
            components={"securitySchemes": {"key": {"type": "apiKey", "in": "query", "name": "api_key"}}},
            security=[{"key": []}],
        )
        auth = discover(spec, name="widgets").service.auth
        assert (auth.kind, auth.location, auth.name) == ("api_key", "query", "api_key")

    def test_basic_auth_uses_two_env_vars(self) -> None:
        spec = build_spec(
            components={"securitySchemes": {"legacy": {"type": "http", "scheme": "basic"}}},
            security=[{"legacy": []}],
        )
        auth = discover(spec, name="widgets").service.auth
        assert auth.kind == "basic"
        assert auth.required_env == ("WIDGETS_PASSWORD", "WIDGETS_USERNAME")

    def test_oauth2_falls_back_to_a_pre_obtained_bearer_token_with_a_warning(self) -> None:
        spec = build_spec(
            components={
                "securitySchemes": {
                    "oauth": {
                        "type": "oauth2",
                        "flows": {"clientCredentials": {"tokenUrl": "https://x/token"}},
                    }
                }
            },
            security=[{"oauth": []}],
        )
        discovery = discover(spec, name="widgets")
        assert discovery.service.auth.kind == "bearer"
        assert any("does not run the token flow" in warning for warning in discovery.warnings)

    def test_global_security_wins_over_an_unused_scheme(self) -> None:
        spec = build_spec(
            components={
                "securitySchemes": {
                    "unused": {"type": "apiKey", "in": "header", "name": "X-Unused"},
                    "chosen": {"type": "http", "scheme": "bearer"},
                }
            },
            security=[{"chosen": []}],
        )
        assert discover(spec, name="widgets").service.auth.scheme_name == "chosen"

    def test_no_security_schemes_means_no_credentials(self) -> None:
        auth = discover(build_spec(), name="widgets").service.auth
        assert auth.kind == "none"
        assert auth.required_env == ()

    def test_parameters_that_would_collide_with_credentials_are_skipped(self) -> None:
        spec = build_spec(
            components={"securitySchemes": {"key": {"type": "apiKey", "in": "header", "name": "X-Api-Key"}}},
            security=[{"key": []}],
            paths={
                "/widgets": {
                    "get": {
                        "operationId": "listWidgets",
                        "parameters": [
                            {"name": "X-Api-Key", "in": "header", "schema": {"type": "string"}},
                            {"name": "Authorization", "in": "header", "schema": {"type": "string"}},
                        ],
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        )
        discovery = discover(spec, name="widgets")
        assert discovery.service.tool("list_widgets").input_schema["properties"] == {}
        assert sum("managed by the runtime" in warning for warning in discovery.warnings) == 2


class TestWarningsAndErrors:
    def test_cookie_parameters_are_skipped_with_a_warning(self) -> None:
        spec = build_spec(
            paths={
                "/widgets": {
                    "get": {
                        "operationId": "listWidgets",
                        "parameters": [{"name": "session", "in": "cookie", "schema": {"type": "string"}}],
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            }
        )
        discovery = discover(spec, name="widgets")
        assert discovery.service.tool("list_widgets").input_schema["properties"] == {}
        assert any("unsupported location" in warning for warning in discovery.warnings)

    def test_missing_servers_warns_so_the_operator_sets_a_base_url(self) -> None:
        spec = build_spec()
        del spec["servers"]
        discovery = discover(spec, name="widgets")
        assert discovery.service.base_url is None
        assert any("BASE_URL" in warning for warning in discovery.warnings)

    def test_non_json_request_bodies_are_passed_through_as_strings(self) -> None:
        spec = build_spec(
            paths={
                "/reports": {
                    "post": {
                        "operationId": "uploadReport",
                        "requestBody": {"content": {"text/csv": {"schema": {"type": "string"}}}},
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            }
        )
        discovery = discover(spec, name="reports")
        body = discovery.service.tool("upload_report").body
        assert body is not None and body.content_type == "text/csv"
        assert any("raw string" in warning for warning in discovery.warnings)

    def test_external_refs_are_rejected_with_a_bundling_hint(self) -> None:
        spec = build_spec(
            paths={
                "/widgets": {
                    "get": {
                        "operationId": "listWidgets",
                        "parameters": [
                            {"name": "q", "in": "query", "schema": {"$ref": "common.yaml#/Query"}}
                        ],
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            }
        )
        with pytest.raises(SpecError, match="Bundle the spec"):
            discover(spec, name="widgets")

    def test_a_spec_with_no_operations_is_an_error(self) -> None:
        with pytest.raises(SpecError, match="no usable operations"):
            discover(build_spec(paths={"/widgets": {"description": "nothing callable"}}), name="widgets")

    def test_recursive_schemas_terminate(self) -> None:
        spec = build_spec(
            components={
                "schemas": {
                    "Node": {
                        "type": "object",
                        "properties": {
                            "children": {"type": "array", "items": {"$ref": "#/components/schemas/Node"}}
                        },
                    }
                }
            },
            paths={
                "/trees": {
                    "post": {
                        "operationId": "createTree",
                        "requestBody": {
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Node"}}}
                        },
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        )
        schema = discover(spec, name="trees").service.tool("create_tree").input_schema
        assert schema["properties"]["body"]["$ref"] == "#/$defs/Node"
        assert schema["$defs"]["Node"]["properties"]["children"]["items"]["$ref"] == "#/$defs/Node"
