"""Tests for rfc.react_keywords.ReActKeywords."""

import json
from unittest.mock import MagicMock, patch

import pytest

from rfc.react_keywords import ReActKeywords, parse_react_response


class TestParseReactResponse:
    def test_parses_final_answer(self) -> None:
        text = "I now know the answer.\nFINAL_ANSWER: 42"
        action, arg = parse_react_response(text)
        assert action == "FINAL_ANSWER"
        assert arg == "42"

    def test_parses_action(self) -> None:
        text = "I need to look this up.\nACTION: calculator(2+2)"
        action, arg = parse_react_response(text)
        assert action == "ACTION"
        assert arg == "calculator(2+2)"

    def test_parses_final_answer_case_insensitive(self) -> None:
        text = "final_answer: Paris"
        action, arg = parse_react_response(text)
        assert action == "FINAL_ANSWER"
        assert arg == "Paris"

    def test_returns_none_for_unparseable(self) -> None:
        text = "I'm thinking about this problem..."
        action, arg = parse_react_response(text)
        assert action is None
        assert arg is None

    def test_multiline_final_answer(self) -> None:
        text = "Thought: done.\nFINAL_ANSWER: The capital of France is Paris"
        action, arg = parse_react_response(text)
        assert action == "FINAL_ANSWER"
        assert arg == "The capital of France is Paris"


class TestReActKeywordsInit:
    @patch("rfc.react_keywords.create_provider")
    @patch("rfc.react_keywords.Grader")
    def test_default_init(self, MockGrader: MagicMock, mock_create: MagicMock) -> None:
        kw = ReActKeywords()
        mock_create.assert_called_once_with(timeout=5400, max_retries=2)
        MockGrader.assert_called_once_with(mock_create.return_value)


class TestRunReActLoop:
    @patch("rfc.react_keywords.create_provider")
    @patch("rfc.react_keywords.Grader")
    def test_reaches_answer_in_one_step(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        """LLM returns FINAL_ANSWER immediately — 1 step used."""
        kw = ReActKeywords()
        kw.client.generate.return_value = "FINAL_ANSWER: 4"
        kw.client.last_metrics = None
        kw.client.num_ctx = None
        kw.client.max_tokens = 256
        mock_result = MagicMock()
        mock_result.score = 1.0
        mock_result.reason = "correct"
        kw.grader.grade.return_value = mock_result

        tool_results = json.dumps({})
        result = kw.run_react_loop(
            question="What is 2+2?",
            tool_descriptions="calculator: does math",
            tool_results=tool_results,
            expected_answer="4",
            max_steps=5,
        )
        assert result["score"] == 1.0
        assert result["steps_used"] == 1
        assert result["final_answer"] == "4"
        assert result["budget_exceeded"] is False

    @patch("rfc.react_keywords.create_provider")
    @patch("rfc.react_keywords.Grader")
    def test_reaches_answer_after_tool_call(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        """LLM calls a tool, gets observation, then gives final answer."""
        kw = ReActKeywords()
        kw.client.generate.side_effect = [
            "I need to calculate.\nACTION: calculator(2+2)",
            "FINAL_ANSWER: 4",
        ]
        kw.client.last_metrics = None
        kw.client.num_ctx = None
        kw.client.max_tokens = 256
        mock_result = MagicMock()
        mock_result.score = 1.0
        mock_result.reason = "correct"
        kw.grader.grade.return_value = mock_result

        tool_results = json.dumps({"calculator(2+2)": "4"})
        result = kw.run_react_loop(
            question="What is 2+2?",
            tool_descriptions="calculator: does math",
            tool_results=tool_results,
            expected_answer="4",
            max_steps=5,
        )
        assert result["score"] == 1.0
        assert result["steps_used"] == 2
        assert result["final_answer"] == "4"
        assert kw.client.generate.call_count == 2

    @patch("rfc.react_keywords.create_provider")
    @patch("rfc.react_keywords.Grader")
    def test_exceeds_budget_returns_failure(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        """LLM keeps calling tools past max_steps — budget exceeded."""
        kw = ReActKeywords()
        kw.client.generate.return_value = "ACTION: search(query)"
        kw.client.last_metrics = None
        kw.client.num_ctx = None
        kw.client.max_tokens = 256

        tool_results = json.dumps({"search(query)": "some result"})
        result = kw.run_react_loop(
            question="Find X",
            tool_descriptions="search: searches things",
            tool_results=tool_results,
            expected_answer="X",
            max_steps=3,
        )
        assert result["score"] == 0.0
        assert result["steps_used"] == 3
        assert result["budget_exceeded"] is True
        assert result["final_answer"] is None

    @patch("rfc.react_keywords.create_provider")
    @patch("rfc.react_keywords.Grader")
    def test_unknown_tool_returns_error_observation(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        """ACTION references a tool not in tool_results — gets error observation."""
        kw = ReActKeywords()
        kw.client.generate.side_effect = [
            "ACTION: unknown_tool(arg)",
            "FINAL_ANSWER: fallback",
        ]
        kw.client.last_metrics = None
        kw.client.num_ctx = None
        kw.client.max_tokens = 256
        mock_result = MagicMock()
        mock_result.score = 0.5
        mock_result.reason = "partial"
        kw.grader.grade.return_value = mock_result

        tool_results = json.dumps({"calculator(2+2)": "4"})
        result = kw.run_react_loop(
            question="What is 2+2?",
            tool_descriptions="calculator: does math",
            tool_results=tool_results,
            expected_answer="4",
            max_steps=5,
        )
        assert result["steps_used"] == 2
        assert result["final_answer"] == "fallback"

    @patch("rfc.react_keywords.create_provider")
    @patch("rfc.react_keywords.Grader")
    def test_string_max_steps_coercion(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        """Robot Framework passes args as strings — max_steps must be coerced."""
        kw = ReActKeywords()
        kw.client.generate.return_value = "FINAL_ANSWER: done"
        kw.client.last_metrics = None
        kw.client.num_ctx = None
        kw.client.max_tokens = 4096
        mock_result = MagicMock()
        mock_result.score = 1.0
        mock_result.reason = "ok"
        kw.grader.grade.return_value = mock_result

        result = kw.run_react_loop(
            question="Q",
            tool_descriptions="t: d",
            tool_results="{}",
            expected_answer="done",
            max_steps="3",  # type: ignore[arg-type]
        )
        assert result["score"] == 1.0
