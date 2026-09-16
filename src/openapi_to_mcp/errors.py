"""Exceptions raised by the generator.

Every failure an operator can cause (bad spec, unsupported feature, existing
output directory) raises :class:`GeneratorError` so the CLI can print a single
actionable line instead of a traceback.
"""

from __future__ import annotations


class GeneratorError(Exception):
    """A problem the operator can fix, reported without a traceback."""


class SpecError(GeneratorError):
    """The OpenAPI document is missing, malformed, or uses an unsupported feature."""


class OutputError(GeneratorError):
    """The output directory cannot be written to."""
