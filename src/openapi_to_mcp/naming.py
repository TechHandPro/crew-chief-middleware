"""Deterministic names for tools, arguments, and environment variables.

Tool names are the API surface an agent sees, so they must be stable across
regenerations: the same document always produces the same names in the same
order.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_NON_ALNUM = re.compile(r"[^0-9a-zA-Z]+")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_PYTHON_KEYWORDS = frozenset(
    {
        "and",
        "as",
        "assert",
        "async",
        "await",
        "break",
        "class",
        "continue",
        "def",
        "del",
        "elif",
        "else",
        "except",
        "false",
        "finally",
        "for",
        "from",
        "global",
        "if",
        "import",
        "in",
        "is",
        "lambda",
        "none",
        "nonlocal",
        "not",
        "or",
        "pass",
        "raise",
        "return",
        "true",
        "try",
        "while",
        "with",
        "yield",
    }
)


def to_snake_case(value: str) -> str:
    """Convert ``listTicketComments`` / ``list-ticket-comments`` to ``list_ticket_comments``."""
    spaced = _CAMEL_BOUNDARY.sub(" ", value)
    cleaned = _NON_ALNUM.sub(" ", spaced).strip()
    snake = "_".join(part.lower() for part in cleaned.split() if part)
    if not snake:
        return "unnamed"
    if snake[0].isdigit():
        snake = f"n_{snake}"
    if snake in _PYTHON_KEYWORDS:
        snake = f"{snake}_"
    return snake


def tool_name(operation_id: str | None, method: str, path: str) -> str:
    """Derive a tool name, preferring ``operationId`` and falling back to method plus path."""
    if operation_id and operation_id.strip():
        return to_snake_case(operation_id)
    path_words = [segment for segment in path.split("/") if segment]
    readable = [
        f"by_{segment[1:-1]}" if segment.startswith("{") and segment.endswith("}") else segment
        for segment in path_words
    ]
    return to_snake_case("_".join([method.lower(), *readable]))


def unique_name(candidate: str, taken: Iterable[str]) -> str:
    """Return ``candidate``, suffixed with ``_2``, ``_3``, ... when it is already taken."""
    used = set(taken)
    if candidate not in used:
        return candidate
    for suffix in range(2, 1000):
        alternative = f"{candidate}_{suffix}"
        if alternative not in used:
            return alternative
    raise ValueError(f"could not find a unique name for {candidate!r}")


def env_prefix(name: str) -> str:
    """Environment variable prefix for a service name (``help-desk`` -> ``HELP_DESK``)."""
    if not name.strip():
        return "API"
    return to_snake_case(name).upper().strip("_") or "API"


def module_name(name: str) -> str:
    """Importable module/package name for a service name."""
    return to_snake_case(name)
