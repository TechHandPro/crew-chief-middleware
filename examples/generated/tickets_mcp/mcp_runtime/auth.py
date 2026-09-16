"""Credentials, resolved from the environment only.

Secrets are never written to the manifest, never logged, and are redacted from
any text the runtime hands back to the model.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from .manifest import AuthConfig

_REDACTED = "***"
#: Values shorter than this are not worth redacting and would mangle unrelated text.
_MIN_REDACTABLE_LENGTH = 6


class MissingCredentialError(RuntimeError):
    """A required credential environment variable is unset or empty."""


@dataclass(frozen=True)
class Credentials:
    """Ready-to-send authentication material."""

    headers: dict[str, str] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)
    secrets: tuple[str, ...] = ()

    def redact(self, text: str) -> str:
        return redact(text, self.secrets)


def credentials_from_env(auth: AuthConfig, env: Mapping[str, str] | None = None) -> Credentials:
    """Resolve ``auth`` against ``env`` (defaults to ``os.environ``)."""
    environment = os.environ if env is None else env

    if auth.kind == "none":
        return Credentials()

    if auth.kind == "bearer":
        token = _require(environment, auth.env.get("token", ""), "bearer token")
        return Credentials(headers={"Authorization": f"Bearer {token}"}, secrets=(token,))

    if auth.kind == "basic":
        username = _require(environment, auth.env.get("username", ""), "basic auth username")
        password = _require(environment, auth.env.get("password", ""), "basic auth password")
        encoded = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        return Credentials(headers={"Authorization": f"Basic {encoded}"}, secrets=(password, encoded))

    if auth.kind == "api_key":
        api_key = _require(environment, auth.env.get("api_key", ""), "API key")
        field_name = auth.name or "X-API-Key"
        if auth.location == "query":
            return Credentials(query={field_name: api_key}, secrets=(api_key,))
        return Credentials(headers={field_name: api_key}, secrets=(api_key,))

    raise MissingCredentialError(f"unsupported auth kind {auth.kind!r}")


def redact(text: str, secrets: tuple[str, ...]) -> str:
    """Replace any occurrence of a known secret with ``***``."""
    redacted = text
    for secret in secrets:
        if secret and len(secret) >= _MIN_REDACTABLE_LENGTH:
            redacted = redacted.replace(secret, _REDACTED)
    return redacted


def _require(env: Mapping[str, str], variable: str, label: str) -> str:
    if not variable:
        raise MissingCredentialError(
            f"the manifest does not say which environment variable holds the {label}"
        )
    value = (env.get(variable) or "").strip()
    if not value:
        raise MissingCredentialError(f"missing {label}: set the {variable} environment variable")
    return value
