"""LLM-judge grader — a Protocol adapter over the existing Grader (#621).

This does NOT reimplement grading. It wraps :class:`rfc.grader.Grader`
(the LLM-as-judge already used by the math/swebench suites) to the
:class:`rfc.graders.base.Grader` Protocol: it pulls the question and expected
answer out of the dataset ``instance``, delegates to ``Grader.grade(...)``,
and adapts the returned :class:`rfc.models.GradeResult` to ``(score, reason)``.

The LLM client is injected (mockable exactly as ``rfc.grader.Grader`` is in
``tests/test_grader.py``), so unit tests never call a real model.
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
        # Reuse the existing judge wholesale (validation, prompt, empty-answer
        # handling all live there); never duplicate grading logic here.
        self._judge = _LLMGrader(llm_client)

    def grade(self, instance: Dict[str, Any], response: str) -> Tuple[float, str]:
        question = _first(instance, _QUESTION_FIELDS)
        expected = _first(instance, _EXPECTED_FIELDS)
        result = self._judge.grade(question, expected, response)
        return result.score, result.reason
