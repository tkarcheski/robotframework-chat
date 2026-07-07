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
        assert result.score == 1.0
        assert isinstance(result.score, float)
        assert result.reason == "correct"

    def test_grade_incorrect_answer(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 0, "reason": "wrong"}'
        grader = Grader(client)
        result = grader.grade("What is 2+2?", "4", "5")
        assert result.score == 0.0

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

    def test_grade_partial_score(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 0.4, "reason": "partially correct"}'
        grader = Grader(client)
        result = grader.grade("What is 2+2?", "4", "It might be 3 or 4")
        assert result.score == 0.4

    def test_grade_prompt_requests_fractional_scores(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 0.5, "reason": "partial"}'
        grader = Grader(client)
        grader.grade("q", "e", "a")
        prompt = client.generate.call_args[0][0]
        assert "score must be a number between 0.0 and 1.0" in prompt
        assert "use partial credit" in prompt
        assert '"score": 0.0 to 1.0' in prompt


class _ThinkingGraderClient:
    """Fake grader LLM that returns thinking-only output until think=False.

    Mimics qwen3.6 on Ollama 0.30+ (issue #131): the OllamaClient surfaces a
    blank `response` + non-empty `thinking` as an inline <think> block, so the
    usable grader answer is empty until reasoning is turned off.
    """

    def __init__(self):
        self.think = None
        self.last_metrics = None
        self.calls = []
        self.think_seen = []

    def generate(self, prompt):
        self.calls.append(prompt)
        self.think_seen.append(self.think)
        if self.think is False:
            return '{"score": 0.5, "reason": "graded after think disabled"}'
        return "<think>reasoning but no verdict</think>"


class _NoThinkClient:
    def __init__(self, response):
        self._response = response
        self.last_metrics = None
        self.calls = 0

    def generate(self, prompt):
        self.calls += 1
        return self._response


class TestGraderThinkRetry:
    def test_empty_verdict_retries_with_think_false(self):
        client = _ThinkingGraderClient()
        result = Grader(client).grade("q", "e", "a")
        assert result.score == 0.5
        # Two calls: thinking-only, then the retry with think disabled.
        assert len(client.calls) == 2
        assert client.think_seen == [None, False]
        # Original think setting restored after the retry.
        assert client.think is None

    def test_retry_logs_warning(self):
        from unittest.mock import patch

        client = _ThinkingGraderClient()
        with patch("rfc.grader.logger") as mock_logger:
            Grader(client).grade("q", "e", "a")
        assert mock_logger.warn.called

    def test_no_retry_when_first_verdict_nonempty(self):
        client = _ThinkingGraderClient()
        # Pre-answer so the first generate already yields a usable verdict.
        client.generate = lambda prompt: '{"score": 1.0, "reason": "ok"}'  # type: ignore[method-assign]
        result = Grader(client).grade("q", "e", "a")
        assert result.score == 1.0
        # think must remain untouched (no retry path).
        assert client.think is None

    def test_no_retry_when_think_already_false(self):
        client = _ThinkingGraderClient()
        client.think = False  # already disabled; retrying can't help
        with pytest.raises(ValueError, match="invalid JSON"):
            # think=False path returns valid JSON in the fake, so force empty:
            client.generate = lambda prompt: "<think>still nothing</think>"  # type: ignore[method-assign]
            Grader(client).grade("q", "e", "a")

    def test_client_without_think_attr_does_not_retry(self):
        client = _NoThinkClient("<think>no verdict</think>")
        with pytest.raises(ValueError, match="invalid JSON"):
            Grader(client).grade("q", "e", "a")
        assert client.calls == 1  # no second attempt

    def test_think_restored_even_if_retry_raises(self):
        client = _ThinkingGraderClient()

        def boom(prompt):
            client.calls.append(prompt)
            if client.think is False:
                raise RuntimeError("provider down")
            return "<think>nothing</think>"

        client.generate = boom  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="provider down"):
            Grader(client).grade("q", "e", "a")
        assert client.think is None  # restored despite the exception
