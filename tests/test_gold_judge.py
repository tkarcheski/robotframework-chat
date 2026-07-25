"""Tests for the pinned gold-suite judge (``GOLD_JUDGE_MODEL``).

The gold suites used to build their ``Grader`` from ``self.client`` — the arm's
own model — so a model under test graded its own answers. A paired A/B then
compared arms that were not only generating differently but *judging*
differently, and a judge that emitted unparseable JSON failed the test outright,
conflating "the judge broke" with "the answer was wrong".

These tests pin the two properties that fix it: one frozen judge for every arm,
and judge failure that skips rather than fails.
"""

import pytest

from unittest.mock import MagicMock, patch

from rfc.exceptions import (
    GraderUnavailableError,
    RFCSkipError,
    SelfGradingConfigError,
)
from rfc.grader import Grader
from rfc.llm_client import create_judge_provider


class TestJudgeExceptions:
    def test_grader_unavailable_skips_not_fails(self):
        assert issubclass(GraderUnavailableError, RFCSkipError)
        assert GraderUnavailableError.ROBOT_SKIP_EXECUTION is True

    def test_self_grading_config_skips_not_fails(self):
        assert issubclass(SelfGradingConfigError, RFCSkipError)
        assert SelfGradingConfigError.ROBOT_SKIP_EXECUTION is True

    def test_grader_unavailable_names_the_judge(self):
        err = GraderUnavailableError("phi4:14b", "not json at all")
        assert err.judge_model == "phi4:14b"
        assert "phi4:14b" in str(err)
        assert "not json at all" in str(err)

    def test_self_grading_error_names_both_sides(self):
        err = SelfGradingConfigError("qwen2.5:3b")
        assert err.model == "qwen2.5:3b"
        assert "qwen2.5:3b" in str(err)


class TestCreateJudgeProvider:
    def test_unset_env_returns_fallback_client(self, monkeypatch):
        """Legacy behavior is preserved for every non-gate consumer."""
        monkeypatch.delenv("GOLD_JUDGE_MODEL", raising=False)
        fallback = MagicMock()
        assert create_judge_provider(fallback) is fallback

    def test_blank_env_returns_fallback_client(self, monkeypatch):
        monkeypatch.setenv("GOLD_JUDGE_MODEL", "   ")
        fallback = MagicMock()
        assert create_judge_provider(fallback) is fallback

    def test_pinned_judge_is_built_with_deterministic_settings(self, monkeypatch):
        monkeypatch.setenv("GOLD_JUDGE_MODEL", "phi4:14b")
        monkeypatch.setenv("DEFAULT_MODEL", "qwen2.5:3b")
        monkeypatch.delenv("GOLD_JUDGE_PROVIDER", raising=False)
        fallback = MagicMock()

        with patch("rfc.llm_client.create_provider") as factory:
            judge = create_judge_provider(fallback)

        assert judge is factory.return_value
        kwargs = factory.call_args.kwargs
        assert kwargs["model"] == "phi4:14b"
        assert kwargs["temperature"] == 0.0
        assert kwargs["response_format"] == "json"
        assert factory.call_args.args[0] == "ollama"

    def test_judge_provider_is_overridable(self, monkeypatch):
        monkeypatch.setenv("GOLD_JUDGE_MODEL", "phi4:14b")
        monkeypatch.setenv("GOLD_JUDGE_PROVIDER", "vllm")
        monkeypatch.setenv("DEFAULT_MODEL", "qwen2.5:3b")

        with patch("rfc.llm_client.create_provider") as factory:
            create_judge_provider(MagicMock())

        assert factory.call_args.args[0] == "vllm"

    def test_judge_equal_to_arm_is_refused(self, monkeypatch):
        """Self-grading is the bug being fixed; it must never run silently."""
        monkeypatch.setenv("GOLD_JUDGE_MODEL", "qwen2.5:3b")
        monkeypatch.setenv("DEFAULT_MODEL", "qwen2.5:3b")

        with pytest.raises(SelfGradingConfigError, match="qwen2.5:3b"):
            create_judge_provider(MagicMock())

    def test_judge_equal_to_arm_ignores_case_and_space(self, monkeypatch):
        monkeypatch.setenv("GOLD_JUDGE_MODEL", " Qwen2.5:3B ")
        monkeypatch.setenv("DEFAULT_MODEL", "qwen2.5:3b")

        with pytest.raises(SelfGradingConfigError):
            create_judge_provider(MagicMock())

    def test_timeout_and_retries_are_forwarded(self, monkeypatch):
        monkeypatch.setenv("GOLD_JUDGE_MODEL", "phi4:14b")
        monkeypatch.setenv("DEFAULT_MODEL", "qwen2.5:3b")

        with patch("rfc.llm_client.create_provider") as factory:
            create_judge_provider(MagicMock(), timeout=99, max_retries=5)

        assert factory.call_args.kwargs["timeout"] == 99
        assert factory.call_args.kwargs["max_retries"] == 5


class TestJudgeFailureSkips:
    def test_unparseable_judge_output_retries_then_skips(self):
        client = MagicMock()
        client.generate.return_value = "I think the answer is fine, honestly"
        client.model = "phi4:14b"

        with pytest.raises(GraderUnavailableError):
            Grader(client).grade("q", "e", "a")

        # One retry: the judge is asked exactly twice before giving up.
        assert client.generate.call_count == 2

    def test_transient_bad_json_recovers_on_retry(self):
        client = MagicMock()
        client.generate.side_effect = [
            "sorry, here goes:",
            '{"score": 1.0, "reason": "correct"}',
        ]
        client.model = "phi4:14b"

        result = Grader(client).grade("q", "e", "a")

        assert result.score == 1.0
        assert client.generate.call_count == 2

    def test_missing_fields_also_skips(self):
        client = MagicMock()
        client.generate.return_value = '{"reason": "no score here"}'
        client.model = "phi4:14b"

        with pytest.raises(GraderUnavailableError):
            Grader(client).grade("q", "e", "a")

    def test_empty_answer_still_scores_zero(self):
        """An empty *answer* is a model failure, not a judge failure."""
        client = MagicMock()
        result = Grader(client).grade("q", "e", "   ")

        assert result.score == 0.0
        client.generate.assert_not_called()
