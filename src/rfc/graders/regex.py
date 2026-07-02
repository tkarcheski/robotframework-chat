"""Regex grader — deterministic pattern search over the response (#621).

No LLM, no network: scores 1.0 when the instance's ``pattern`` (or
``expected_answer`` used as a pattern) is found anywhere in the response,
else 0.0. An invalid pattern raises ``re.error`` (a ``ValueError`` subclass)
so a malformed dataset fails loudly rather than silently scoring 0.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Tuple


class RegexGrader:
    """Score by regex search against ``pattern`` / ``expected_answer``."""

    def __init__(self, flags: int = 0) -> None:
        self.flags = flags

    def grade(self, instance: Dict[str, Any], response: str) -> Tuple[float, str]:
        pattern = instance.get("pattern")
        if pattern is None:
            pattern = instance.get("expected_answer", "")
        # re.compile raises re.error (a ValueError) on a malformed pattern.
        compiled = re.compile(str(pattern), self.flags)
        if compiled.search(str(response)):
            return 1.0, f"Pattern {pattern!r} matched"
        return 0.0, f"Pattern {pattern!r} did not match"
