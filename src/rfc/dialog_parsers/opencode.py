"""OpenCode transcript parser — stub (#355).

Only the ``claude-code`` parser is implemented today; this module
reserves the registry slot so ``rfc dialog import --tool opencode``
fails with an honest message instead of a silent mis-parse.
"""

from __future__ import annotations

from pathlib import Path

from .base import ParsedTranscript


def parse_opencode(path: Path) -> ParsedTranscript:
    """Not implemented yet — PRs welcome."""
    raise NotImplementedError(
        "The 'opencode' transcript parser is not implemented yet — PRs welcome! "
        "See src/rfc/dialog_parsers/claude_code.py for the reference implementation."
    )
