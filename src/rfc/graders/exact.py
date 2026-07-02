"""Exact-match grader — deterministic string equality (#621).

No LLM, no network: scores 1.0 when the response equals the instance's
expected answer (whitespace-trimmed, case-insensitive by default), else 0.0.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple


class ExactGrader:
    """Score by exact string match against ``expected_answer`` / ``expected``."""

    def __init__(self, case_sensitive: bool = False) -> None:
        self.case_sensitive = case_sensitive

    def grade(self, instance: Dict[str, Any], response: str) -> Tuple[float, str]:
        expected = instance.get("expected_answer")
        if expected is None:
            expected = instance.get("expected", "")
        exp = str(expected).strip()
        act = str(response).strip()
        if not self.case_sensitive:
            exp = exp.lower()
            act = act.lower()
        if act == exp:
            return 1.0, "Exact match"
        return 0.0, f"No exact match (expected {expected!r})"
