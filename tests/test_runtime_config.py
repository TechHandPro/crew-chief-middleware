"""Runtime configuration and credential resolution, both env-driven."""

from __future__ import annotations

import pytest

from openapi_to_mcp.runtime.auth import MissingCredentialError, credentials_from_env, redact
from openapi_to_mcp.runtime.config import ConfigError, settings_from_env
from openapi_to_mcp.runtime.manifest import AuthConfig, Manifest, ToolBinding

TOOL = ToolBinding(
    name="list_items",
    description="",
    input_schema={"type": "object", "properties": {}},
    method="GET",
    path="/items",
)


def manifest(base_url: str | None = "https://api.example.com/v1", auth: AuthConfig | None = None) -> Manifest:
    return Manifest(
        name="demo",
        title="Demo",
        version="1.0.0",
        env_prefix="DEMO",
        auth=auth or AuthConfig(),
        tools=(TOOL,),
        base_url=base_url,
    )


class TestSettings:
    def test_defaults_come_from_the_manifest(self) -> None:
        settings = settings_from_env(manifest(), {})
        assert settings.base_url == "https://api.example.com/v1"
        assert (settings.timeout_seconds, settings.max_retries, settings.read_only) == (30.0, 2, False)

    def test_env_overrides_the_base_url_and_strips_a_trailing_slash(self) -> None:
        settings = settings_from_env(manifest(), {"DEMO_BASE_URL": "https://staging.example.com/api/"})
        assert settings.base_url == "https://staging.example.com/api"

    def test_missing_base_url_names_the_variable_to_set(self) -> None:
        with pytest.raises(ConfigError, match="DEMO_BASE_URL"):
            settings_from_env(manifest(base_url=None), {})

    def test_plaintext_http_to_a_remote_host_is_refused_by_default(self) -> None:
        with pytest.raises(ConfigError, match="ALLOW_INSECURE_HTTP"):
            settings_from_env(manifest(), {"DEMO_BASE_URL": "http://api.example.com"})

    def test_plaintext_http_can_be_allowed_explicitly(self) -> None:
        settings = settings_from_env(
            manifest(), {"DEMO_BASE_URL": "http://api.example.com", "DEMO_ALLOW_INSECURE_HTTP": "1"}
        )
        assert settings.base_url == "http://api.example.com"

    def test_loopback_http_needs_no_opt_in(self) -> None:
        assert settings_from_env(manifest(), {"DEMO_BASE_URL": "http://127.0.0.1:8080"}).base_url

    def test_credentials_embedded_in_the_url_are_refused(self) -> None:
        with pytest.raises(ConfigError, match="must not embed credentials"):
            settings_from_env(manifest(), {"DEMO_BASE_URL": "https://user:secret@api.example.com"})

    @pytest.mark.parametrize("value", ["ftp://api.example.com", "api.example.com", "https://"])
    def test_unusable_base_urls_are_rejected(self, value: str) -> None:
        with pytest.raises(ConfigError):
            settings_from_env(manifest(), {"DEMO_BASE_URL": value})

    def test_read_only_accepts_common_boolean_spellings(self) -> None:
        assert settings_from_env(manifest(), {"DEMO_READ_ONLY": "yes"}).read_only is True
        assert settings_from_env(manifest(), {"DEMO_READ_ONLY": "off"}).read_only is False

    def test_a_non_boolean_flag_is_a_configuration_error(self) -> None:
        with pytest.raises(ConfigError, match="is not a boolean"):
            settings_from_env(manifest(), {"DEMO_READ_ONLY": "maybe"})

    def test_numeric_limits_are_validated(self) -> None:
        assert settings_from_env(manifest(), {"DEMO_TIMEOUT_SECONDS": "5"}).timeout_seconds == 5.0
        with pytest.raises(ConfigError, match="is not a number"):
            settings_from_env(manifest(), {"DEMO_TIMEOUT_SECONDS": "soon"})
        with pytest.raises(ConfigError, match="below the minimum"):
            settings_from_env(manifest(), {"DEMO_MAX_RESPONSE_BYTES": "10"})


class TestCredentials:
    def test_bearer_token_becomes_an_authorization_header(self) -> None:
        auth = AuthConfig(kind="bearer", env={"token": "DEMO_API_TOKEN"})
        credentials = credentials_from_env(auth, {"DEMO_API_TOKEN": "s3cret-token"})
        assert credentials.headers == {"Authorization": "Bearer s3cret-token"}
        assert credentials.secrets == ("s3cret-token",)

    def test_api_key_can_go_in_a_header_or_the_query_string(self) -> None:
        header_auth = AuthConfig(
            kind="api_key", env={"api_key": "DEMO_API_KEY"}, location="header", name="X-Api-Key"
        )
        assert credentials_from_env(header_auth, {"DEMO_API_KEY": "abc123"}).headers == {
            "X-Api-Key": "abc123"
        }

        query_auth = AuthConfig(
            kind="api_key", env={"api_key": "DEMO_API_KEY"}, location="query", name="api_key"
        )
        assert credentials_from_env(query_auth, {"DEMO_API_KEY": "abc123"}).query == {"api_key": "abc123"}

    def test_basic_auth_is_base64_encoded(self) -> None:
        auth = AuthConfig(kind="basic", env={"username": "DEMO_USERNAME", "password": "DEMO_PASSWORD"})
        credentials = credentials_from_env(auth, {"DEMO_USERNAME": "alice", "DEMO_PASSWORD": "hunter2000"})
        assert credentials.headers["Authorization"] == "Basic YWxpY2U6aHVudGVyMjAwMA=="

    def test_no_auth_sends_nothing(self) -> None:
        credentials = credentials_from_env(AuthConfig(), {})
        assert credentials.headers == {} and credentials.query == {}

    def test_a_missing_credential_names_the_variable_to_set(self) -> None:
        auth = AuthConfig(kind="bearer", env={"token": "DEMO_API_TOKEN"})
        with pytest.raises(MissingCredentialError, match="DEMO_API_TOKEN"):
            credentials_from_env(auth, {})

    def test_a_blank_credential_counts_as_missing(self) -> None:
        auth = AuthConfig(kind="bearer", env={"token": "DEMO_API_TOKEN"})
        with pytest.raises(MissingCredentialError, match="DEMO_API_TOKEN"):
            credentials_from_env(auth, {"DEMO_API_TOKEN": "   "})

    def test_secrets_are_redacted_from_text(self) -> None:
        auth = AuthConfig(kind="bearer", env={"token": "DEMO_API_TOKEN"})
        credentials = credentials_from_env(auth, {"DEMO_API_TOKEN": "super-secret-value"})
        assert credentials.redact("sent Bearer super-secret-value") == "sent Bearer ***"

    def test_short_values_are_left_alone_to_avoid_mangling_unrelated_text(self) -> None:
        assert redact("the api returned 200 ok", ("ok",)) == "the api returned 200 ok"
