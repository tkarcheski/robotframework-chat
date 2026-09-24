"""Guards the ai/writing.md docs standard on the docs it governs.

Rule 6 is the only mechanically checkable one: no em dashes, no en dashes.
They read as machine-generated and usually paper over a sentence that wanted
to be two. Ranges use a plain hyphen.

Scope is deliberately narrow: the core agent-facing docs plus the graded-pool
files, not the whole repo. Most of the repo predates the standard and converts
when someone touches it (writing.md's own closing rule), so a repo-wide check
would fail on day one and get disabled.

Add a file here when you convert it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Files held to the standard. Grow this list as docs are converted.
GOVERNED_FILES: tuple[str, ...] = (
    "CLAUDE.md",
    "ai/CLAUDE.md",
    "ai/agents.md",
    "ai/testing.md",
    "ai/writing.md",
    "config/gold_harness.yaml",
    "scripts/check_gold_suites.py",
    "tests/test_check_gold_suites.py",
    "tests/test_docs_style.py",
)

# Referenced by codepoint so this file does not trip its own check.
FORBIDDEN = {"\u2014": "em dash", "\u2013": "en dash"}


@pytest.mark.parametrize("relpath", GOVERNED_FILES)
def test_no_dashes(relpath: str) -> None:
    path = ROOT / relpath
    assert path.exists(), f"{relpath} is listed as governed but does not exist"

    offenders = [
        f"{relpath}:{num}: {line.strip()}"
        for num, line in enumerate(path.read_text().splitlines(), 1)
        if any(ch in line for ch in FORBIDDEN)
    ]
    assert not offenders, (
        "ai/writing.md rule 6: no em/en dashes. Use a period, colon, comma, or "
        "brackets; ranges use a plain hyphen.\n" + "\n".join(offenders)
    )


def test_governed_files_are_unique_and_sorted() -> None:
    """Keeps the list reviewable as it grows."""
    assert len(set(GOVERNED_FILES)) == len(GOVERNED_FILES)
    assert list(GOVERNED_FILES) == sorted(GOVERNED_FILES)
