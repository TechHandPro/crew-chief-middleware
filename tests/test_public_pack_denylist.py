"""Public-pack deny-list: README prose must not require a TNT/SOCIAL process.

Canonical written list: docs/public-pack.md

This file is the automated check. It is not itself a public-pack surface,
so deny-list literals may appear here.
"""

from __future__ import annotations

import re

from tests.conftest import REPO_ROOT

README = REPO_ROOT / "README.md"
ARCHITECTURE = REPO_ROOT / "ARCHITECTURE.md"
MAKEFILE = REPO_ROOT / "Makefile"
PUBLIC_PACK_DOC = REPO_ROOT / "docs" / "public-pack.md"
META_NOTES = REPO_ROOT / "examples" / "meta-graph-pages.md"
X_NOTES = REPO_ROOT / "examples" / "x-api.md"

# Operator DNS assembled so this test is the only scanner that names it.
_PRIVATE_OPERATOR_DNS = ".".join(("techhand", "pro"))
_PRIVATE_HOSTNAME_RE = re.compile(
    rf"(^|[^a-z0-9-])([a-z0-9-]+\.)?{re.escape(_PRIVATE_OPERATOR_DNS)}([^a-z0-9-]|$)",
    re.IGNORECASE,
)
_OPERATOR_LEGAL_NAME = " ".join(("TechHand", "Pro", "Solutions"))
_SECRET_MATERIAL_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]+-----|"
    r"\b(sk_live_|sk_test_|xox[baprs]-|EAAC[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,})"
)
_README_PROCESS_RES = (
    re.compile(r"(?i)\btnt\s*#\s*\d+"),
    re.compile(r"(?i)\borange-prompt\b"),
    re.compile(r"(?i)\btnt vault\b"),
    re.compile(r"\bSOCIAL\b"),
    re.compile(r"(?i)\btnt\b"),
)

_PUBLIC_EXAMPLE_GLOBS = (
    "examples/tickets-openapi.yaml",
    "examples/tickets-overrides.yaml",
    "examples/meta-graph-pages-openapi.yaml",
    "examples/meta-graph-pages-overrides.yaml",
    "examples/generated/tickets_mcp/README.md",
    "examples/generated/tickets_mcp/.env.example",
    "examples/generated/meta_graph_mcp/README.md",
    "examples/generated/meta_graph_mcp/.env.example",
    "examples/x-api-openapi.yaml",
    "examples/x-api-overrides.yaml",
    "examples/generated/x_mcp/README.md",
    "examples/generated/x_mcp/.env.example",
)


def _hits(text: str, patterns: tuple[re.Pattern[str], ...]) -> list[str]:
    found: list[str] = []
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            found.append(match.group(0))
    return found


class TestPublicPackContractExists:
    def test_written_deny_list_explains_the_split(self) -> None:
        text = PUBLIC_PACK_DOC.read_text(encoding="utf-8")
        lowered = text.lower()
        for needle in (
            "public pack",
            "operator notes",
            "deny-list",
            "readme",
            "orange-prompt",
            "meta graph",
            "not the default path",
        ):
            assert needle in lowered, f"docs/public-pack.md must explain {needle!r}"


class TestReadmeProseIsVendorNeutral:
    def test_readme_does_not_require_tnt_or_social_process(self) -> None:
        text = README.read_text(encoding="utf-8")
        assert _hits(text, _README_PROCESS_RES) == []

    def test_architecture_and_makefile_help_omit_process_ids(self) -> None:
        makefile_help = "\n".join(
            line for line in MAKEFILE.read_text(encoding="utf-8").splitlines() if "##" in line
        )
        architecture = ARCHITECTURE.read_text(encoding="utf-8")
        process_ids = (re.compile(r"(?i)\btnt\s*#\s*\d+"), re.compile(r"\bSOCIAL\b"))
        assert _hits(makefile_help, process_ids) == []
        assert _hits(architecture, process_ids) == []

    def test_readme_still_documents_both_committed_examples(self) -> None:
        text = README.read_text(encoding="utf-8")
        lowered = text.lower()
        for needle in (
            "tickets-openapi.yaml",
            "meta graph",
            "meta_graph",
            "x-api-openapi.yaml",
            "x_mcp",
            "make factory",
            "read_only",
            "secret manager",
        ):
            assert needle in lowered, f"README must keep working example content {needle!r}"

    def test_meta_graph_example_notes_are_optional_not_required(self) -> None:
        text = META_NOTES.read_text(encoding="utf-8")
        assert re.search(r"(?i)^## optional operator notes", text, re.MULTILINE)
        default_path, optional = re.split(r"(?im)^## optional operator notes\s*$", text, maxsplit=1)
        assert default_path.strip()
        assert optional.strip()
        assert _hits(default_path, _README_PROCESS_RES) == []
        assert re.search(r"(?i)\borange-prompt\b", optional)
        assert re.search(r"(?i)\bvault\b", optional)

    def test_x_api_example_notes_are_optional_not_required(self) -> None:
        text = X_NOTES.read_text(encoding="utf-8")
        assert re.search(r"(?i)^## optional operator notes", text, re.MULTILINE)
        default_path, optional = re.split(r"(?im)^## optional operator notes\s*$", text, maxsplit=1)
        assert default_path.strip()
        assert optional.strip()
        assert _hits(default_path, _README_PROCESS_RES) == []
        assert re.search(r"(?i)\borange-prompt\b", optional)
        assert re.search(r"(?i)\bvault\b", optional)
        assert re.search(r"(?i)\bx_api_token\b", optional)


class TestPublicExamplesStayScrubbed:
    def test_public_pack_surfaces_omit_private_hosts_and_secrets(self) -> None:
        paths = [
            README,
            ARCHITECTURE,
            MAKEFILE,
            META_NOTES,
            X_NOTES,
            *[REPO_ROOT / rel for rel in _PUBLIC_EXAMPLE_GLOBS],
        ]
        host_hits: list[str] = []
        secret_hits: list[str] = []
        legal_hits: list[str] = []
        for path in paths:
            assert path.is_file(), path
            text = path.read_text(encoding="utf-8")
            rel = path.relative_to(REPO_ROOT).as_posix()
            if _PRIVATE_HOSTNAME_RE.search(text):
                host_hits.append(rel)
            if _SECRET_MATERIAL_RE.search(text):
                secret_hits.append(rel)
            if _OPERATOR_LEGAL_NAME in text:
                legal_hits.append(rel)
        assert host_hits == []
        assert secret_hits == []
        assert legal_hits == []

    def test_generated_env_examples_do_not_default_a_private_token_host(self) -> None:
        for rel in (
            "examples/generated/tickets_mcp/.env.example",
            "examples/generated/meta_graph_mcp/.env.example",
            "examples/generated/x_mcp/.env.example",
        ):
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            assert "API_TOKEN=" in text
            assert _PRIVATE_HOSTNAME_RE.search(text) is None
