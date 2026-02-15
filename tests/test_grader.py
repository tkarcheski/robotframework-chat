"""Tests for rfc.grader.Grader."""

from unittest.mock import MagicMock

import pytest

from rfc.grader import Grader
from rfc.models import GradeResult


class TestGrader:
    def test_init_none_client_rejected(self):
        with pytest.raises(TypeError, match="must not be None"):
            Grader(None)

    def test_init_with_client(self):
        client = MagicMock()
        grader = Grader(client)
        assert grader.llm is client

    def test_grade_correct_answer(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 1, "reason": "correct"}'
        grader = Grader(client)
        result = grader.grade("What is 2+2?", "4", "4")
        assert isinstance(result, GradeResult)
        assert result.score == 1
        assert result.reason == "correct"

    def test_grade_incorrect_answer(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 0, "reason": "wrong"}'
        grader = Grader(client)
        result = grader.grade("What is 2+2?", "4", "5")
        assert result.score == 0

    def test_grade_invalid_json(self):
        client = MagicMock()
        client.generate.return_value = "not valid json"
        grader = Grader(client)
        with pytest.raises(ValueError, match="invalid JSON"):
            grader.grade("q", "e", "a")

    def test_grade_missing_score_field(self):
        client = MagicMock()
        client.generate.return_value = '{"reason": "x"}'
        grader = Grader(client)
        with pytest.raises(ValueError, match="missing required fields"):
            grader.grade("q", "e", "a")

    def test_grade_missing_reason_field(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 1}'
        grader = Grader(client)
        with pytest.raises(ValueError, match="missing required fields"):
            grader.grade("q", "e", "a")

    def test_grade_empty_question(self):
        client = MagicMock()
        grader = Grader(client)
        with pytest.raises(ValueError, match="non-empty string"):
            grader.grade("", "expected", "actual")

    def test_grade_non_string_input(self):
        client = MagicMock()
        grader = Grader(client)
        with pytest.raises(TypeError, match="question must be a str"):
            grader.grade(123, "expected", "actual")

    def test_grade_non_string_expected(self):
        client = MagicMock()
        grader = Grader(client)
        with pytest.raises(TypeError, match="expected must be a str"):
            grader.grade("q", 123, "actual")
