"""DialogGrader — the ``Grade Answer`` machinery for non-Robot callers (#356).

The Robot keyword ``Grade Answer`` (:mod:`rfc.keywords`) wraps
:class:`rfc.grader.Grader` and emits Robot log artifacts. The replay
engine grades outside any Robot run, so this module re-exposes the same
grading core without the Robot listener/log side effects.
"""

from __future__ import annotations

from .grader import Grader
from .llm_client import LLMProvider
from .models import GradeResult


class DialogGrader:
    """Grade a replayed answer against the originally recorded answer."""

    def __init__(self, llm_client: LLMProvider) -> None:
        self._grader = Grader(llm_client)

    def grade(self, question: str, expected: str, actual: str) -> GradeResult:
        """Score ``actual`` against ``expected`` for ``question`` (0.0–1.0).

        Same contract as the ``Grade Answer`` keyword: empty ``actual``
        scores 0.0 without consulting the judge model.
        """
        return self._grader.grade(question, expected, actual)
