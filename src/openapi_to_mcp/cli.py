"""Command line interface.

openapi_to_mcp generate --spec PATH --out DIR --name NAME
openapi_to_mcp list-tools --spec PATH [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from openapi_to_mcp import __version__
from openapi_to_mcp.discovery import discover
from openapi_to_mcp.errors import GeneratorError
from openapi_to_mcp.generator import generate
from openapi_to_mcp.model import Discovery
from openapi_to_mcp.overrides import Overrides, apply_overrides, load_overrides, merge_overrides
from openapi_to_mcp.spec_loader import load_spec

_EXIT_USAGE = 2
_EXIT_FAILURE = 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            return _run_generate(args)
        if args.command == "list-tools":
            return _run_list_tools(args)
    except GeneratorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return _EXIT_FAILURE
    parser.print_help()
    return _EXIT_USAGE


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openapi_to_mcp",
        description="Turn an OpenAPI document into a runnable MCP server.",
    )
    parser.add_argument("--version", action="version", version=f"openapi_to_mcp {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    generate_parser = subparsers.add_parser(
        "generate",
        help="write an MCP server project for a spec",
        description="Generate a standalone MCP server (stdio) from an OpenAPI 3.x document.",
    )
    generate_parser.add_argument(
        "--spec", required=True, type=Path, help="path to an OpenAPI 3.x JSON or YAML file"
    )
    generate_parser.add_argument("--out", required=True, type=Path, help="directory to write the server into")
    generate_parser.add_argument(
        "--name", required=True, help="service name, used for tool naming and env vars"
    )
    generate_parser.add_argument("--base-url", help="override the base URL from the spec's servers list")
    generate_parser.add_argument(
        "--env-prefix", help="environment variable prefix (default: derived from --name)"
    )
    generate_parser.add_argument(
        "--force", action="store_true", help="overwrite an existing non-empty output directory"
    )
    generate_parser.add_argument("--quiet", action="store_true", help="only print errors")
    _add_curation_arguments(generate_parser)

    list_parser = subparsers.add_parser(
        "list-tools",
        help="preview the tools a spec would produce",
        description="Discover tools without writing anything.",
    )
    list_parser.add_argument(
        "--spec", required=True, type=Path, help="path to an OpenAPI 3.x JSON or YAML file"
    )
    list_parser.add_argument("--name", default="api", help="service name used for tool naming (default: api)")
    list_parser.add_argument(
        "--json", action="store_true", dest="as_json", help="emit JSON instead of a table"
    )
    _add_curation_arguments(list_parser)

    return parser


def _add_curation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="GLOB",
        help="keep only tools matching this glob (repeatable)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="drop tools matching this glob (repeatable)",
    )
    parser.add_argument(
        "--overrides", type=Path, help="YAML or JSON file that renames, re-describes, or hides tools"
    )


def _run_generate(args: argparse.Namespace) -> int:
    discovery, warnings = _discover(args)
    project = generate(
        discovery.service,
        args.out,
        generator_version=__version__,
        force=args.force,
    )

    if not args.quiet:
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
        service = discovery.service
        print(f"Generated {len(project.tool_names)} tools for {service.name} in {project.directory}")
        print(f"  tools: {', '.join(project.tool_names)}")
        required_env = service.auth.required_env
        if required_env:
            print(f"  set before running: {', '.join(required_env)}")
        requirements = project.directory / "requirements.txt"
        print(f"  next: pip install -r {requirements} && python {project.server_script}")
    return 0


def _run_list_tools(args: argparse.Namespace) -> int:
    discovery, warnings = _discover(args)
    service = discovery.service

    if args.as_json:
        print(
            json.dumps(
                {
                    "service": {
                        "name": service.name,
                        "title": service.title,
                        "version": service.version,
                        "base_url": service.base_url,
                        "auth": service.auth.kind,
                        "required_env": list(service.auth.required_env),
                    },
                    "tools": [
                        {
                            "name": tool.name,
                            "method": tool.method,
                            "path": tool.path,
                            "read_only": tool.read_only,
                            "arguments": sorted(tool.input_schema.get("properties", {})),
                        }
                        for tool in service.tools
                    ],
                    "warnings": list(warnings),
                },
                indent=2,
            )
        )
        return 0

    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"{service.title} ({service.version}) -> {len(service.tools)} tools, auth: {service.auth.kind}")
    width = max((len(tool.name) for tool in service.tools), default=4)
    for tool in service.tools:
        print(f"  {tool.name.ljust(width)}  {tool.method:<6} {tool.path}")
    return 0


def _discover(args: argparse.Namespace) -> tuple[Discovery, tuple[str, ...]]:
    spec = load_spec(args.spec)
    discovery = discover(
        spec,
        name=args.name,
        base_url=getattr(args, "base_url", None),
        env_prefix=getattr(args, "env_prefix", None),
    )
    overrides = load_overrides(args.overrides) if args.overrides else Overrides()
    overrides = merge_overrides(overrides, include=tuple(args.include), exclude=tuple(args.exclude))
    service, override_warnings = apply_overrides(discovery.service, overrides)
    return (
        Discovery(service=service, warnings=discovery.warnings),
        discovery.warnings + override_warnings,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
