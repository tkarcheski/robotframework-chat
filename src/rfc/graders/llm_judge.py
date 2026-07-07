"""LLM-judge grader — a Protocol adapter over :class:`rfc.grader.Grader` (#621).

Does NOT reimplement grading: it pulls the question and expected answer from the
dataset ``instance``, delegates to the existing LLM-as-judge ``Grader.grade``,
and adapts the returned ``GradeResult`` to ``(score, reason)``. The LLM client
is injected, so unit tests never call a real model.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from ..grader import Grader as _LLMGrader

# Instance fields consulted for the judge question / expected answer, in
# priority order. Different benchmarks name these differently.
_QUESTION_FIELDS = ("question", "problem_statement", "prompt", "input")
_EXPECTED_FIELDS = ("expected_answer", "expected", "answer", "reference")


def _first(instance: Dict[str, Any], fields: tuple[str, ...]) -> str:
    for f in fields:
        val = instance.get(f)
        if val:
            return str(val)
    return ""


class LLMJudgeGrader:
    """Adapt :class:`rfc.grader.Grader` to the eval Grader Protocol."""

    def __init__(self, llm_client: Any) -> None:
        # Reuse the existing judge wholesale; never duplicate grading logic here.
        self._judge = _LLMGrader(llm_client)

    def grade(self, instance: Dict[str, Any], response: str) -> Tuple[float, str]:
        question = _first(instance, _QUESTION_FIELDS)
        expected = _first(instance, _EXPECTED_FIELDS)
        result = self._judge.grade(question, expected, response)
        return result.score, result.reason
