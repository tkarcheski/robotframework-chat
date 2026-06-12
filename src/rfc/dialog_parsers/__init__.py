"""Pluggable per-tool transcript parsers for ``rfc dialog import`` (#355).

Each parser maps one external agent-tool export file to a
:class:`rfc.dialog_parsers.base.ParsedTranscript`. ``claude-code`` is
fully implemented; ``codex`` and ``opencode`` are registered stubs that
raise ``NotImplementedError`` so unsupported tools fail loudly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .base import DialogParseError, ParsedTranscript
from .claude_code import parse_claude_code
from .codex import parse_codex
from .opencode import parse_opencode

DialogParser = Callable[[Path], ParsedTranscript]

PARSERS: dict[str, DialogParser] = {
    "claude-code": parse_claude_code,
    "codex": parse_codex,
    "opencode": parse_opencode,
}

SUPPORTED_TOOLS: tuple[str, ...] = tuple(PARSERS)


class UnknownDialogToolError(ValueError):
    """Requested tool has no registered transcript parser."""


def get_parser(tool: str) -> DialogParser:
    """Return the parser registered for ``tool`` or raise a clear error."""
    try:
        return PARSERS[tool]
    except KeyError:
        raise UnknownDialogToolError(
            f"no transcript parser for tool {tool!r}; "
            f"supported tools: {', '.join(SUPPORTED_TOOLS)}"
        ) from None


__all__ = [
    "PARSERS",
    "SUPPORTED_TOOLS",
    "DialogParseError",
    "DialogParser",
    "ParsedTranscript",
    "UnknownDialogToolError",
    "get_parser",
]
