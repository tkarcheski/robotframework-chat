"""Tests for eval_graders — llm_judge wrapper over Grader (#621)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from rfc.eval_graders import llm_judge
from rfc.models import GradeResult


class TestLLMJudge:
    def _make_grader(self, score: float = 0.9, reason: str = "correct") -> MagicMock:
        grader = MagicMock()
        grader.grade.return_value = GradeResult(score=score, reason=reason)
        return grader

    def test_delegates_to_grader_grade(self) -> None:
        grader = self._make_grader()
        llm_judge(grader, "q", "expected", "actual")
        grader.grade.assert_called_once_with("q", "expected", "actual")

    def test_returns_grade_result(self) -> None:
        grader = self._make_grader(score=1.0, reason="perfect")
        result = llm_judge(grader, "q", "expected", "actual")
        assert isinstance(result, GradeResult)
        assert result.score == 1.0
        assert result.reason == "perfect"

    def test_zero_score_passes_through(self) -> None:
        grader = self._make_grader(score=0.0, reason="wrong")
        result = llm_judge(grader, "q", "expected", "actual")
        assert result.score == 0.0

    def test_raises_on_none_grader(self) -> None:
        with pytest.raises((AttributeError, TypeError)):
            llm_judge(None, "q", "expected", "actual")  # type: ignore[arg-type]
