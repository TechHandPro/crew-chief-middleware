#!/usr/bin/env python3
"""Fail-closed factory smoke for one generated MCP server (TNT #330).

Dogfood default is the committed Meta Graph Pages example. The script prints a
single PASS/FAIL line, never echoes credential values, and keeps READ_ONLY=1
unless an operator explicitly sets SMOKE_WRITES=1 after a recorded write smoke.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import anyio

from openapi_to_mcp.naming import env_prefix
from openapi_to_mcp.runtime.auth import redact
from openapi_to_mcp.runtime.manifest import ToolBinding

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NAME = "meta_graph"
DEFAULT_OUT = REPO_ROOT / "examples" / "generated" / "meta_graph_mcp"
_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off", ""})


class SmokeFail(RuntimeError):
    """Operator-facing failure; ``main`` prints ``FAIL:`` and exits 1."""


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    environment = dict(os.environ if env is None else env)
    args = _parse_args(argv, environment)
    secrets: tuple[str, ...] = ()
    try:
        prefix = env_prefix(args.name)
        token_var = f"{prefix}_API_TOKEN"
        token = (environment.get(token_var) or "").strip()
        if not token:
            raise SmokeFail(f"missing {token_var} (vault / orange-prompt only; never commit tokens)")
        secrets = (token,)

        read_only = _read_only(prefix, environment)
        if not read_only and not _flag(environment.get("SMOKE_WRITES")):
            raise SmokeFail(
                "kill-switch: factory smoke defaults to READ_ONLY=1 and will not "
                "continue with writes enabled. Keep READ_ONLY=1, or set "
                "SMOKE_WRITES=1 only after a recorded write smoke on a non-prod agent"
            )

        out = args.out.expanduser()
        if not out.is_absolute():
            out = (Path.cwd() / out).resolve()
        manifest_path = out / "tools.json"
        if not manifest_path.is_file() or not (out / "server.py").is_file():
            raise SmokeFail(f"generated server not found under {out} (run make factory-generate)")

        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_text = json.dumps(document, ensure_ascii=False)
        if token in manifest_text:
            raise SmokeFail(f"{token_var} appears in tools.json; rotate the token and never commit secrets")

        tools = document.get("tools")
        if not isinstance(tools, list) or not tools:
            raise SmokeFail(f"{manifest_path} has no tools")

        live_env = dict(environment)
        live_env[f"{prefix}_READ_ONLY"] = "1" if read_only else "0"
        live = args.live if args.live is not None else _flag(environment.get("FACTORY_LIVE"), default=True)

        if not live:
            _pass(
                f"offline gate (FACTORY_LIVE=0) NAME={args.name} READ_ONLY={'1' if read_only else '0'}",
                secrets,
            )
            return 0

        tool_name = anyio.run(_live_get, out, live_env, args.tool)
        _pass(f"live {tool_name} READ_ONLY={'1' if read_only else '0'}", secrets)
        return 0
    except SmokeFail as exc:
        _fail(str(exc), secrets)
        return 1
    except Exception as exc:  # noqa: BLE001 - operator script; never dump a traceback with secrets
        _fail(f"{type(exc).__name__}: {exc}", secrets)
        return 1


def _parse_args(argv: Sequence[str] | None, environment: Mapping[str, str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail-closed READ_ONLY smoke for one generated MCP server (TNT #330)."
    )
    parser.add_argument(
        "--name",
        default=environment.get("NAME") or DEFAULT_NAME,
        help="service name / env prefix source (default: meta_graph)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(environment["OUT"]) if environment.get("OUT") else DEFAULT_OUT,
        help="generated server directory (default: examples/generated/meta_graph_mcp)",
    )
    parser.add_argument("--tool", help="read-only tool to call when FACTORY_LIVE=1 (default: first GET)")
    live = parser.add_mutually_exclusive_group()
    live.add_argument("--live", dest="live", action="store_true", help="call one GET tool (default)")
    live.add_argument("--offline", dest="live", action="store_false", help="credential + manifest gate only")
    parser.set_defaults(live=None)
    return parser.parse_args(list(argv) if argv is not None else None)


def _read_only(prefix: str, environment: Mapping[str, str]) -> bool:
    specific = environment.get(f"{prefix}_READ_ONLY")
    if specific is not None:
        return _flag(specific, default=True)
    return _flag(environment.get("READ_ONLY"), default=True)


def _flag(raw: str | None, *, default: bool = False) -> bool:
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise SmokeFail(f"{raw!r} is not a boolean (use 1/0, true/false, yes/no)")


async def _live_get(out: Path, environment: Mapping[str, str], tool_name: str | None) -> str:
    """Call one GET tool through the generated server's vendored runtime.

    ``mcp_runtime`` is imported inline on purpose: the package name is always
    the same and the directory is the operator-chosen ``--out``. A top-level
    import would pin whichever generated server was first on ``sys.path``.
    """
    runtime = _generated_runtime(out)
    manifest = runtime.manifest.load_manifest(out / "tools.json")
    settings = runtime.config.settings_from_env(manifest, environment)
    credentials = runtime.auth.credentials_from_env(manifest.auth, environment)
    tool = _select_read_only_tool(manifest.tools, tool_name)
    async with runtime.http.ApiClient(settings, credentials) as client:
        result = await client.call(tool, {})
    if result.is_error:
        detail = credentials.redact(result.text)
        raise SmokeFail(f"live {tool.name} {detail}")
    return tool.name


def _select_read_only_tool(tools: Sequence[ToolBinding], requested: str | None) -> ToolBinding:
    by_name = {tool.name: tool for tool in tools}
    if requested:
        tool = by_name.get(requested)
        if tool is None:
            known = ", ".join(sorted(by_name)) or "none"
            raise SmokeFail(f"unknown tool {requested!r}. Available tools: {known}")
        if not tool.read_only:
            raise SmokeFail(f"refusing to smoke write tool {tool.name}; factory smoke is GET-only")
        return tool
    for tool in tools:
        if tool.read_only:
            return tool
    raise SmokeFail("manifest has no GET/HEAD/OPTIONS tool to smoke")


def _generated_runtime(out: Path) -> object:
    out_str = str(out.resolve())
    if sys.path[:1] != [out_str]:
        sys.path.insert(0, out_str)
    for key in list(sys.modules):
        if key == "mcp_runtime" or key.startswith("mcp_runtime."):
            del sys.modules[key]

    from mcp_runtime import auth, config, http, manifest  # noqa: PLC0415

    return argparse.Namespace(auth=auth, config=config, http=http, manifest=manifest)


def _pass(message: str, secrets: tuple[str, ...]) -> None:
    print(redact(f"PASS: {message}", secrets))


def _fail(message: str, secrets: tuple[str, ...]) -> None:
    print(redact(f"FAIL: {message}", secrets))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
