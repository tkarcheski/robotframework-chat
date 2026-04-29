"""Tests for rfc.creativity_grader.CreativityGrader."""

from unittest.mock import MagicMock

import pytest

from rfc.creativity_grader import CreativityGrader
from rfc.models import GradeResult
from rfc.multi_grader import MultiGradeResult, MultiGrader


class TestCreativityGrader:
    def test_init_none_client_rejected(self) -> None:
        with pytest.raises(TypeError, match="must not be None"):
            CreativityGrader(None)

    def test_init_with_client(self) -> None:
        client = MagicMock()
        grader = CreativityGrader(client)
        assert grader.llm is client

    def test_grade_joke_returns_grade_result(self) -> None:
        client = MagicMock()
        client.generate.return_value = '{"score": 0.8, "reason": "funny and creative"}'
        grader = CreativityGrader(client)
        result = grader.grade_joke(
            "Tell me a fart joke",
            "Why did the bean go to the doctor? Because it had gas!",
            "contains humor about flatulence",
        )
        assert isinstance(result, GradeResult)
        assert result.score == 0.8
        assert result.reason == "funny and creative"

    def test_grade_joke_prompt_includes_creativity_criteria(self) -> None:
        client = MagicMock()
        client.generate.return_value = '{"score": 0.5, "reason": "ok"}'
        grader = CreativityGrader(client)
        grader.grade_joke("prompt", "joke text", "expected traits")
        prompt = client.generate.call_args[0][0]
        assert "humor" in prompt.lower()
        assert "creativ" in prompt.lower()
        assert "original" in prompt.lower()

    def test_grade_joke_prompt_includes_inputs(self) -> None:
        client = MagicMock()
        client.generate.return_value = '{"score": 0.5, "reason": "ok"}'
        grader = CreativityGrader(client)
        grader.grade_joke("Tell me a dad joke", "Why did the...", "dad joke format")
        prompt = client.generate.call_args[0][0]
        assert "Tell me a dad joke" in prompt
        assert "Why did the..." in prompt
        assert "dad joke format" in prompt

    def test_grade_joke_invalid_json(self) -> None:
        client = MagicMock()
        client.generate.return_value = "not json"
        grader = CreativityGrader(client)
        with pytest.raises(ValueError, match="invalid JSON"):
            grader.grade_joke("prompt", "joke", "traits")

    def test_grade_joke_missing_fields(self) -> None:
        client = MagicMock()
        client.generate.return_value = '{"reason": "no score"}'
        grader = CreativityGrader(client)
        with pytest.raises(ValueError, match="missing required fields"):
            grader.grade_joke("prompt", "joke", "traits")

    def test_grade_joke_empty_prompt_rejected(self) -> None:
        client = MagicMock()
        grader = CreativityGrader(client)
        with pytest.raises(ValueError, match="non-empty"):
            grader.grade_joke("", "joke", "traits")

    def test_grade_joke_non_string_rejected(self) -> None:
        client = MagicMock()
        grader = CreativityGrader(client)
        with pytest.raises(TypeError, match="prompt must be a str"):
            grader.grade_joke(123, "joke", "traits")  # type: ignore[arg-type]

    def test_grade_context_returns_grade_result(self) -> None:
        client = MagicMock()
        client.generate.return_value = (
            '{"score": 0.9, "reason": "maintained context perfectly"}'
        )
        grader = CreativityGrader(client)
        result = grader.grade_context(
            "Name recall test",
            "User said their name is Alice",
            "Hello Alice!",
            "Response should use the name Alice",
        )
        assert isinstance(result, GradeResult)
        assert result.score == 0.9

    def test_grade_context_prompt_includes_context_criteria(self) -> None:
        client = MagicMock()
        client.generate.return_value = '{"score": 0.5, "reason": "ok"}'
        grader = CreativityGrader(client)
        grader.grade_context("desc", "conversation", "response", "expected")
        prompt = client.generate.call_args[0][0]
        assert "context" in prompt.lower()

    def test_grade_context_prompt_includes_inputs(self) -> None:
        client = MagicMock()
        client.generate.return_value = '{"score": 0.5, "reason": "ok"}'
        grader = CreativityGrader(client)
        grader.grade_context(
            "Name recall", "User: My name is Bob", "Hi Bob!", "uses name Bob"
        )
        prompt = client.generate.call_args[0][0]
        assert "Name recall" in prompt
        assert "My name is Bob" in prompt
        assert "Hi Bob!" in prompt
        assert "uses name Bob" in prompt

    def test_grade_joke_handles_thinking_tags(self) -> None:
        client = MagicMock()
        client.generate.return_value = (
            '<think>let me think</think>{"score": 0.7, "reason": "good"}'
        )
        grader = CreativityGrader(client)
        result = grader.grade_joke("prompt", "joke", "traits")
        assert result.score == 0.7

    def test_grade_joke_handles_markdown_json(self) -> None:
        client = MagicMock()
        client.generate.return_value = (
            '```json\n{"score": 0.6, "reason": "decent"}\n```'
        )
        grader = CreativityGrader(client)
        result = grader.grade_joke("prompt", "joke", "traits")
        assert result.score == 0.6

    def test_grade_joke_routes_through_multi_grader(self) -> None:
        """When given a MultiGrader, grade_joke uses panel consensus (#260)."""
        panel = MagicMock(spec=MultiGrader)
        panel.grade.return_value = MultiGradeResult(
            scores=[0.6, 0.8, 0.7],
            majority_score=0.7,
            agreement_ratio=0.9,
            reasons=["funny", "creative", "good wordplay"],
        )
        grader = CreativityGrader(panel)
        result = grader.grade_joke("Tell me a joke", "knock knock", "humor")

        assert isinstance(result, GradeResult)
        assert result.score == 0.7
        assert "agreement 90%" in result.reason
        assert "funny" in result.reason
        # Single-client path must not be invoked.
        panel.grade.assert_called_once()
        kwargs = panel.grade.call_args.kwargs
        assert "Tell me a joke" in kwargs["question"]
        assert kwargs["actual"] == "knock knock"
        assert kwargs["expected"] == "humor"
        assert "Humor" in kwargs["rubric"]

    def test_grade_joke_panel_validates_inputs(self) -> None:
        """Validation runs before dispatching to the panel."""
        panel = MagicMock(spec=MultiGrader)
        grader = CreativityGrader(panel)
        with pytest.raises(ValueError, match="non-empty"):
            grader.grade_joke("", "joke", "traits")
        panel.grade.assert_not_called()

    def test_grade_context_unaffected_by_multi_grader(self) -> None:
        """Context grading still uses single-client path (#260 scoped to jokes)."""
        client = MagicMock()
        client.generate.return_value = '{"score": 0.5, "reason": "ok"}'
        grader = CreativityGrader(client)
        # Sanity check: this is the single-client constructor, not a MultiGrader.
        result = grader.grade_context("desc", "conv", "resp", "expected")
        assert result.score == 0.5
        client.generate.assert_called_once()
