"""Runtime for generated MCP servers.

This package is vendored into every generated project (as ``mcp_runtime``), so it
only imports from the standard library, ``httpx``, ``anyio``, and the official
``mcp`` SDK, and all internal imports are relative.

A generated server is a manifest (``tools.json``) plus this runtime:

    from mcp_runtime import run_stdio

    run_stdio(Path(__file__).parent / "tools.json")
"""

from .auth import Credentials, MissingCredentialError, credentials_from_env, redact
from .config import ConfigError, Settings, settings_from_env
from .http import ApiClient, ToolResult
from .manifest import Manifest, ManifestError, ToolBinding, load_manifest
from .server import LocalTool, build_server, run_stdio, serve_stdio

__all__ = [
    "ApiClient",
    "ConfigError",
    "Credentials",
    "LocalTool",
    "Manifest",
    "ManifestError",
    "MissingCredentialError",
    "Settings",
    "ToolBinding",
    "ToolResult",
    "build_server",
    "credentials_from_env",
    "load_manifest",
    "redact",
    "run_stdio",
    "serve_stdio",
    "settings_from_env",
]

RUNTIME_VERSION = "0.1.0"
