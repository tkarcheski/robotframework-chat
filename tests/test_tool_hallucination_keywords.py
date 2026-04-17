"""Tests for rfc.tool_hallucination_keywords.ToolHallucinationKeywords."""

import json
from unittest.mock import MagicMock, patch

from rfc.tool_hallucination_keywords import (
    ToolHallucinationKeywords,
    parse_tool_mentions,
)


class TestParseToolMentions:
    def test_finds_mentioned_tools(self) -> None:
        response = "I would use calculator and search_web to solve this."
        all_tools = ["calculator", "search_web", "fake_db", "magic_parser"]
        mentioned = parse_tool_mentions(response, all_tools)
        assert mentioned == {"calculator", "search_web"}

    def test_case_insensitive_matching(self) -> None:
        response = "Use CALCULATOR for this."
        all_tools = ["calculator", "fake_tool"]
        mentioned = parse_tool_mentions(response, all_tools)
        assert mentioned == {"calculator"}

    def test_no_tools_mentioned(self) -> None:
        response = "I don't need any tools for this."
        all_tools = ["calculator", "search_web"]
        mentioned = parse_tool_mentions(response, all_tools)
        assert mentioned == set()

    def test_all_tools_mentioned(self) -> None:
        response = "I'll use calculator, search_web, and fake_db."
        all_tools = ["calculator", "search_web", "fake_db"]
        mentioned = parse_tool_mentions(response, all_tools)
        assert mentioned == {"calculator", "search_web", "fake_db"}

    def test_substring_overlap_does_not_false_match(self) -> None:
        """web_search_pro should NOT also match web_search."""
        response = "I would use web_search_pro for this task."
        all_tools = ["web_search", "web_search_pro"]
        mentioned = parse_tool_mentions(response, all_tools)
        assert mentioned == {"web_search_pro"}


class TestToolHallucinationKeywordsInit:
    @patch("rfc.tool_hallucination_keywords.create_provider")
    def test_default_init(self, mock_create: MagicMock) -> None:
        ToolHallucinationKeywords()
        mock_create.assert_called_once_with(timeout=5400, max_retries=2)


class TestTestToolSelection:
    @patch("rfc.tool_hallucination_keywords.create_provider")
    def test_only_real_tools_mentioned_scores_1(self, mock_create: MagicMock) -> None:
        """LLM mentions only real tools — precision = 1.0."""
        kw = ToolHallucinationKeywords()
        kw.client.generate.return_value = "I would use calculator for this task."

        result = kw.test_tool_selection(
            task="What is 2+2?",
            real_tools=json.dumps(["calculator", "search_web"]),
            fake_tools=json.dumps(
                [
                    "quantum_solver",
                    "mind_reader",
                    "time_machine",
                    "reality_bender",
                    "dream_parser",
                ]
            ),
        )
        assert result["precision"] == 1.0
        assert result["hallucinated_tools"] == []
        assert "calculator" in result["real_tools_mentioned"]

    @patch("rfc.tool_hallucination_keywords.create_provider")
    def test_fake_tool_mentioned_reduces_score(self, mock_create: MagicMock) -> None:
        """LLM mentions a fake tool — precision < 1.0."""
        kw = ToolHallucinationKeywords()
        kw.client.generate.return_value = (
            "I would use calculator and quantum_solver for this."
        )

        result = kw.test_tool_selection(
            task="What is 2+2?",
            real_tools=json.dumps(["calculator", "search_web"]),
            fake_tools=json.dumps(
                [
                    "quantum_solver",
                    "mind_reader",
                    "time_machine",
                    "reality_bender",
                    "dream_parser",
                ]
            ),
        )
        assert result["precision"] == 0.5  # 1 real / 2 total
        assert "quantum_solver" in result["hallucinated_tools"]

    @patch("rfc.tool_hallucination_keywords.create_provider")
    def test_no_tools_mentioned_scores_zero(self, mock_create: MagicMock) -> None:
        """LLM mentions no tools at all — score 0.0 (failed to select)."""
        kw = ToolHallucinationKeywords()
        kw.client.generate.return_value = "I don't need any tools."

        result = kw.test_tool_selection(
            task="What is 2+2?",
            real_tools=json.dumps(["calculator", "search_web"]),
            fake_tools=json.dumps(
                [
                    "quantum_solver",
                    "mind_reader",
                    "time_machine",
                    "reality_bender",
                    "dream_parser",
                ]
            ),
        )
        assert result["precision"] == 0.0
        assert result["tools_mentioned"] == []

    @patch("rfc.tool_hallucination_keywords.create_provider")
    def test_all_fake_tools_scores_zero(self, mock_create: MagicMock) -> None:
        """LLM only mentions fake tools — precision = 0.0."""
        kw = ToolHallucinationKeywords()
        kw.client.generate.return_value = "I would use quantum_solver and mind_reader."

        result = kw.test_tool_selection(
            task="What is 2+2?",
            real_tools=json.dumps(["calculator", "search_web"]),
            fake_tools=json.dumps(
                [
                    "quantum_solver",
                    "mind_reader",
                    "time_machine",
                    "reality_bender",
                    "dream_parser",
                ]
            ),
        )
        assert result["precision"] == 0.0
        assert len(result["hallucinated_tools"]) == 2

    @patch("rfc.tool_hallucination_keywords.create_provider")
    def test_string_json_parsing(self, mock_create: MagicMock) -> None:
        """Tool lists passed as JSON strings are correctly parsed."""
        kw = ToolHallucinationKeywords()
        kw.client.generate.return_value = "Use search_web."

        result = kw.test_tool_selection(
            task="Find info",
            real_tools='["search_web", "calculator"]',
            fake_tools='["fake1", "fake2", "fake3", "fake4", "fake5"]',
        )
        assert result["precision"] == 1.0
        assert "search_web" in result["real_tools_mentioned"]
