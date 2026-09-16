"""Runtime settings, read from the environment.

Everything an operator can change at run time lives here: base URL, timeouts,
response size caps, and the read-only switch. Nothing is read from disk except
the manifest, and no defaults reach out to the network.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from .manifest import Manifest

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RESPONSE_BYTES = 100_000
DEFAULT_MAX_RETRIES = 2
DEFAULT_LOG_LEVEL = "WARNING"

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off", ""})


class ConfigError(RuntimeError):
    """The environment is missing or contradicts something the server needs."""


@dataclass(frozen=True)
class Settings:
    """Effective runtime configuration."""

    base_url: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    max_retries: int = DEFAULT_MAX_RETRIES
    read_only: bool = False
    log_level: str = DEFAULT_LOG_LEVEL


def settings_from_env(manifest: Manifest, env: Mapping[str, str] | None = None) -> Settings:
    """Build :class:`Settings` for ``manifest`` from ``env`` (defaults to ``os.environ``)."""
    environment = os.environ if env is None else env
    prefix = manifest.env_prefix

    base_url = (environment.get(f"{prefix}_BASE_URL") or manifest.base_url or "").strip()
    if not base_url:
        raise ConfigError(
            f"no base URL configured: set {prefix}_BASE_URL, or regenerate the server with --base-url"
        )
    allow_insecure_http = _read_bool(environment, f"{prefix}_ALLOW_INSECURE_HTTP", default=False)
    base_url = _validate_base_url(base_url, prefix=prefix, allow_insecure_http=allow_insecure_http)

    return Settings(
        base_url=base_url,
        timeout_seconds=_read_float(
            environment, f"{prefix}_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS, minimum=0.1
        ),
        max_response_bytes=int(
            _read_float(environment, f"{prefix}_MAX_RESPONSE_BYTES", DEFAULT_MAX_RESPONSE_BYTES, minimum=1024)
        ),
        max_retries=int(_read_float(environment, f"{prefix}_MAX_RETRIES", DEFAULT_MAX_RETRIES, minimum=0)),
        read_only=_read_bool(environment, f"{prefix}_READ_ONLY", default=False),
        log_level=(environment.get(f"{prefix}_LOG_LEVEL") or DEFAULT_LOG_LEVEL).upper(),
    )


def _validate_base_url(base_url: str, *, prefix: str, allow_insecure_http: bool) -> str:
    parts = urlsplit(base_url)
    if parts.scheme not in {"http", "https"}:
        raise ConfigError(f"base URL {base_url!r} must use http or https")
    if not parts.netloc:
        raise ConfigError(f"base URL {base_url!r} has no host")
    if parts.username or parts.password:
        raise ConfigError(
            "base URL must not embed credentials; use the documented credential env vars instead"
        )
    if parts.query or parts.fragment:
        raise ConfigError(f"base URL {base_url!r} must not contain a query string or fragment")
    if parts.scheme == "http":
        host = (parts.hostname or "").lower()
        if host not in _LOOPBACK_HOSTS and not allow_insecure_http:
            raise ConfigError(
                f"refusing to send credentials over plaintext http to {host!r}; "
                f"use https, or set {prefix}_ALLOW_INSECURE_HTTP=1 for a trusted local endpoint"
            )
    return base_url.rstrip("/")


def _read_bool(env: Mapping[str, str], key: str, *, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise ConfigError(f"{key}={raw!r} is not a boolean (use 1/0, true/false, yes/no)")


def _read_float(env: Mapping[str, str], key: str, default: float, *, minimum: float) -> float:
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key}={raw!r} is not a number") from exc
    if value < minimum:
        raise ConfigError(f"{key}={raw!r} is below the minimum of {minimum}")
    return value
