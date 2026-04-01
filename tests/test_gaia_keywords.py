"""Tests for rfc.gaia_keywords.GaiaKeywords — GAIA-style tool-use testing."""

import json
from unittest.mock import MagicMock, patch

import pytest

from rfc.gaia_keywords import GaiaKeywords, ToolCall, ToolDefinition


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_TOOLS: list[dict] = [
    {
        "name": "Ask LLM",
        "library": "LLMKeywords",
        "description": "Send a prompt to the LLM and get a text response",
        "arguments": [
            {
                "name": "prompt",
                "type": "str",
                "required": True,
                "description": "The text prompt to send",
            }
        ],
        "returns": "str",
    },
    {
        "name": "Grade Answer",
        "library": "LLMKeywords",
        "description": "Grade an actual answer against an expected answer",
        "arguments": [
            {"name": "question", "type": "str", "required": True},
            {"name": "expected", "type": "str", "required": True},
            {"name": "actual", "type": "str", "required": True},
        ],
        "returns": "tuple(score, reason)",
    },
    {
        "name": "Execute Python In Container",
        "library": "DockerKeywords",
        "description": "Run Python code inside a Docker container",
        "arguments": [
            {
                "name": "code",
                "type": "str",
                "required": True,
                "description": "Python source code to execute",
            }
        ],
        "returns": "ExecutionResult",
    },
    {
        "name": "Brainstorm Ideas",
        "library": "CEOKeywords",
        "description": "Generate product ideas for a given domain",
        "arguments": [
            {"name": "domain", "type": "str", "required": True},
            {"name": "count", "type": "int", "required": True},
            {"name": "constraints", "type": "str", "required": False},
        ],
        "returns": "BrainstormOutput",
    },
]


@pytest.fixture()
def gaia() -> GaiaKeywords:
    with (
        patch("rfc.gaia_keywords.create_provider") as mock_create,
        patch("rfc.gaia_keywords.Grader"),
    ):
        mock_create.return_value = MagicMock()
        kw = GaiaKeywords()
    return kw


# ---------------------------------------------------------------------------
# ToolDefinition dataclass
# ---------------------------------------------------------------------------


class TestToolDefinition:
    def test_from_dict(self) -> None:
        td = ToolDefinition.from_dict(SAMPLE_TOOLS[0])
        assert td.name == "Ask LLM"
        assert td.library == "LLMKeywords"
        assert len(td.arguments) == 1
        assert td.arguments[0]["name"] == "prompt"

    def test_from_dict_minimal(self) -> None:
        td = ToolDefinition.from_dict({"name": "Foo", "description": "bar"})
        assert td.name == "Foo"
        assert td.library == ""
        assert td.arguments == []
        assert td.returns == ""


# ---------------------------------------------------------------------------
# build_tool_prompt
# ---------------------------------------------------------------------------


class TestBuildToolPrompt:
    def test_includes_all_tools(self, gaia: GaiaKeywords) -> None:
        prompt = gaia.build_tool_prompt(SAMPLE_TOOLS, "Do something")
        assert "Ask LLM" in prompt
        assert "Grade Answer" in prompt
        assert "Execute Python In Container" in prompt
        assert "Brainstorm Ideas" in prompt

    def test_includes_question(self, gaia: GaiaKeywords) -> None:
        prompt = gaia.build_tool_prompt(SAMPLE_TOOLS, "What tool should I use?")
        assert "What tool should I use?" in prompt

    def test_includes_argument_info(self, gaia: GaiaKeywords) -> None:
        prompt = gaia.build_tool_prompt(SAMPLE_TOOLS, "question")
        assert "prompt" in prompt
        assert "str" in prompt

    def test_includes_json_format_instructions(self, gaia: GaiaKeywords) -> None:
        prompt = gaia.build_tool_prompt(SAMPLE_TOOLS, "question")
        assert "tool_calls" in prompt
        assert "JSON" in prompt

    def test_empty_tools_raises(self, gaia: GaiaKeywords) -> None:
        with pytest.raises(ValueError, match="at least one tool"):
            gaia.build_tool_prompt([], "question")

    def test_empty_question_raises(self, gaia: GaiaKeywords) -> None:
        with pytest.raises(ValueError, match="question"):
            gaia.build_tool_prompt(SAMPLE_TOOLS, "")

    def test_includes_no_tool_refusal_instruction(
        self, gaia: GaiaKeywords
    ) -> None:
        prompt = gaia.build_tool_prompt(SAMPLE_TOOLS, "question")
        assert "none" in prompt.lower() or "no suitable tool" in prompt.lower()


# ---------------------------------------------------------------------------
# parse_tool_calls
# ---------------------------------------------------------------------------


class TestParseToolCalls:
    def test_parse_valid_single_call(self, gaia: GaiaKeywords) -> None:
        response = json.dumps(
            {
                "tool_calls": [
                    {"tool": "Ask LLM", "arguments": {"prompt": "hello"}}
                ],
                "reasoning": "need to ask",
            }
        )
        calls = gaia.parse_tool_calls(response)
        assert len(calls) == 1
        assert calls[0].tool == "Ask LLM"
        assert calls[0].arguments == {"prompt": "hello"}

    def test_parse_multiple_calls(self, gaia: GaiaKeywords) -> None:
        response = json.dumps(
            {
                "tool_calls": [
                    {"tool": "Set LLM Model", "arguments": {"model": "mistral"}},
                    {"tool": "Ask LLM", "arguments": {"prompt": "hello"}},
                ],
                "reasoning": "configure then ask",
            }
        )
        calls = gaia.parse_tool_calls(response)
        assert len(calls) == 2
        assert calls[0].tool == "Set LLM Model"
        assert calls[1].tool == "Ask LLM"

    def test_parse_from_markdown_block(self, gaia: GaiaKeywords) -> None:
        response = '```json\n{"tool_calls": [{"tool": "Ask LLM", "arguments": {"prompt": "hi"}}]}\n```'
        calls = gaia.parse_tool_calls(response)
        assert len(calls) == 1
        assert calls[0].tool == "Ask LLM"

    def test_parse_malformed_json_returns_empty(self, gaia: GaiaKeywords) -> None:
        calls = gaia.parse_tool_calls("this is not json at all")
        assert calls == []

    def test_parse_json_without_tool_calls_key(self, gaia: GaiaKeywords) -> None:
        response = json.dumps({"answer": "42"})
        calls = gaia.parse_tool_calls(response)
        assert calls == []

    def test_parse_refusal_response(self, gaia: GaiaKeywords) -> None:
        response = json.dumps(
            {"tool_calls": [], "reasoning": "No suitable tool available"}
        )
        calls = gaia.parse_tool_calls(response)
        assert calls == []

    def test_parse_with_thinking_tags(self, gaia: GaiaKeywords) -> None:
        response = (
            "<think>Let me think about this.</think>"
            '{"tool_calls": [{"tool": "Ask LLM", "arguments": {"prompt": "hi"}}]}'
        )
        calls = gaia.parse_tool_calls(response)
        assert len(calls) == 1
        assert calls[0].tool == "Ask LLM"


# ---------------------------------------------------------------------------
# grade_tool_selection
# ---------------------------------------------------------------------------


class TestGradeToolSelection:
    def test_correct_single_tool(self, gaia: GaiaKeywords) -> None:
        calls = [ToolCall(tool="Ask LLM", arguments={"prompt": "hi"})]
        result = gaia.grade_tool_selection(["Ask LLM"], calls)
        assert result["score"] == 1.0

    def test_wrong_tool(self, gaia: GaiaKeywords) -> None:
        calls = [ToolCall(tool="Grade Answer", arguments={})]
        result = gaia.grade_tool_selection(["Ask LLM"], calls)
        assert result["score"] == 0.0

    def test_correct_multiple_tools(self, gaia: GaiaKeywords) -> None:
        calls = [
            ToolCall(tool="Set LLM Model", arguments={"model": "m"}),
            ToolCall(tool="Ask LLM", arguments={"prompt": "hi"}),
        ]
        result = gaia.grade_tool_selection(["Set LLM Model", "Ask LLM"], calls)
        assert result["score"] == 1.0

    def test_partial_selection(self, gaia: GaiaKeywords) -> None:
        calls = [ToolCall(tool="Ask LLM", arguments={"prompt": "hi"})]
        result = gaia.grade_tool_selection(["Set LLM Model", "Ask LLM"], calls)
        assert 0.0 < result["score"] < 1.0

    def test_empty_calls_when_expected(self, gaia: GaiaKeywords) -> None:
        result = gaia.grade_tool_selection(["Ask LLM"], [])
        assert result["score"] == 0.0

    def test_correct_ordering_for_chain(self, gaia: GaiaKeywords) -> None:
        calls = [
            ToolCall(tool="Set LLM Model", arguments={}),
            ToolCall(tool="Ask LLM", arguments={}),
        ]
        result = gaia.grade_tool_selection(["Set LLM Model", "Ask LLM"], calls)
        assert result["score"] == 1.0
        assert result["order_correct"]

    def test_wrong_ordering(self, gaia: GaiaKeywords) -> None:
        calls = [
            ToolCall(tool="Ask LLM", arguments={}),
            ToolCall(tool="Set LLM Model", arguments={}),
        ]
        result = gaia.grade_tool_selection(["Set LLM Model", "Ask LLM"], calls)
        # Tools are correct but order is wrong — partial credit
        assert result["score"] < 1.0
        assert not result["order_correct"]

    def test_repeated_tool_calls_both_present(self, gaia: GaiaKeywords) -> None:
        """Repeated tool calls must be preserved — multiplicity matters."""
        calls = [
            ToolCall(tool="Ask LLM", arguments={"prompt": "step 1"}),
            ToolCall(tool="Ask LLM", arguments={"prompt": "step 2"}),
        ]
        result = gaia.grade_tool_selection(["Ask LLM", "Ask LLM"], calls)
        assert result["score"] == 1.0
        assert result["order_correct"]

    def test_repeated_tool_call_missing_second(self, gaia: GaiaKeywords) -> None:
        """Expecting two Ask LLM calls but only one provided — partial credit."""
        calls = [ToolCall(tool="Ask LLM", arguments={"prompt": "only one"})]
        result = gaia.grade_tool_selection(["Ask LLM", "Ask LLM"], calls)
        # Only 1 of 2 expected occurrences present
        assert result["score"] < 1.0
        assert result["score"] > 0.0

    def test_repeated_tool_call_extra_occurrence(self, gaia: GaiaKeywords) -> None:
        """Expected one Ask LLM but got two — extras should not inflate score above 1.0."""
        calls = [
            ToolCall(tool="Ask LLM", arguments={}),
            ToolCall(tool="Ask LLM", arguments={}),
        ]
        result = gaia.grade_tool_selection(["Ask LLM"], calls)
        assert result["score"] <= 1.0


# ---------------------------------------------------------------------------
# grade_tool_arguments
# ---------------------------------------------------------------------------


class TestGradeToolArguments:
    def test_exact_match(self, gaia: GaiaKeywords) -> None:
        call = ToolCall(
            tool="Ask LLM", arguments={"prompt": "What is 2+2?"}
        )
        expected = {"prompt": "What is 2+2?"}
        result = gaia.grade_tool_arguments(expected, call)
        assert result["score"] == 1.0

    def test_wrong_value(self, gaia: GaiaKeywords) -> None:
        call = ToolCall(tool="Ask LLM", arguments={"prompt": "wrong"})
        expected = {"prompt": "What is 2+2?"}
        result = gaia.grade_tool_arguments(expected, call)
        assert result["score"] < 1.0

    def test_missing_key(self, gaia: GaiaKeywords) -> None:
        call = ToolCall(tool="Ask LLM", arguments={})
        expected = {"prompt": "hello"}
        result = gaia.grade_tool_arguments(expected, call)
        assert result["score"] == 0.0

    def test_extra_keys_not_penalized(self, gaia: GaiaKeywords) -> None:
        call = ToolCall(
            tool="Ask LLM",
            arguments={"prompt": "hello", "extra": "ignored"},
        )
        expected = {"prompt": "hello"}
        result = gaia.grade_tool_arguments(expected, call)
        assert result["score"] == 1.0

    def test_numeric_type_coercion(self, gaia: GaiaKeywords) -> None:
        call = ToolCall(
            tool="Set LLM Parameters",
            arguments={"temperature": "0.7", "max_tokens": "1024"},
        )
        expected = {"temperature": 0.7, "max_tokens": 1024}
        result = gaia.grade_tool_arguments(expected, call)
        assert result["score"] == 1.0

    def test_partial_key_match(self, gaia: GaiaKeywords) -> None:
        call = ToolCall(
            tool="Grade Answer",
            arguments={"question": "Q", "expected": "E"},
        )
        expected = {"question": "Q", "expected": "E", "actual": "A"}
        result = gaia.grade_tool_arguments(expected, call)
        assert 0.0 < result["score"] < 1.0


# ---------------------------------------------------------------------------
# grade_tool_refusal
# ---------------------------------------------------------------------------


class TestGradeToolRefusal:
    def test_correct_refusal_empty_calls(self, gaia: GaiaKeywords) -> None:
        response = json.dumps(
            {
                "tool_calls": [],
                "reasoning": "No tool available for sending emails",
            }
        )
        result = gaia.grade_tool_refusal(response)
        assert result["score"] == 1.0

    def test_correct_refusal_with_explanation(self, gaia: GaiaKeywords) -> None:
        response = json.dumps(
            {
                "tool_calls": [],
                "reasoning": "None of the available tools can query a database",
            }
        )
        result = gaia.grade_tool_refusal(response)
        assert result["score"] == 1.0

    def test_incorrect_refusal_tool_called(self, gaia: GaiaKeywords) -> None:
        response = json.dumps(
            {
                "tool_calls": [
                    {"tool": "Ask LLM", "arguments": {"prompt": "weather?"}}
                ],
                "reasoning": "Trying Ask LLM",
            }
        )
        result = gaia.grade_tool_refusal(response)
        assert result["score"] == 0.0

    def test_refusal_in_plain_text(self, gaia: GaiaKeywords) -> None:
        response = "I cannot complete this task because none of the available tools support sending emails."
        result = gaia.grade_tool_refusal(response)
        assert result["score"] == 1.0


# ---------------------------------------------------------------------------
# run_gaia_tool_use_test (end-to-end with mocked LLM)
# ---------------------------------------------------------------------------


class TestRunGaiaToolUseTest:
    def test_single_tool_correct(self, gaia: GaiaKeywords) -> None:
        llm_response = json.dumps(
            {
                "tool_calls": [
                    {"tool": "Ask LLM", "arguments": {"prompt": "capital of France"}}
                ],
                "reasoning": "Need to query the LLM",
            }
        )
        gaia.client = MagicMock()
        gaia.client.generate.return_value = llm_response
        gaia.client.last_metrics = None
        gaia.client.num_ctx = None
        gaia.client.max_tokens = 256

        expected_calls = [{"tool": "Ask LLM", "arguments": {"prompt": "capital of France"}}]
        score, reason, response = gaia.run_gaia_tool_use_test(
            SAMPLE_TOOLS, "Ask the model about the capital of France", expected_calls
        )
        assert score == 1.0
        assert response == llm_response

    def test_refusal_scenario(self, gaia: GaiaKeywords) -> None:
        llm_response = json.dumps(
            {
                "tool_calls": [],
                "reasoning": "No tool can send emails",
            }
        )
        gaia.client = MagicMock()
        gaia.client.generate.return_value = llm_response
        gaia.client.last_metrics = None
        gaia.client.num_ctx = None
        gaia.client.max_tokens = 256

        score, reason, response = gaia.run_gaia_tool_use_test(
            SAMPLE_TOOLS,
            "Send an email to bob@example.com",
            [],  # empty expected = refusal expected
        )
        assert score == 1.0

    def test_wrong_tool_selected(self, gaia: GaiaKeywords) -> None:
        llm_response = json.dumps(
            {
                "tool_calls": [
                    {"tool": "Brainstorm Ideas", "arguments": {"domain": "math"}}
                ],
                "reasoning": "wrong choice",
            }
        )
        gaia.client = MagicMock()
        gaia.client.generate.return_value = llm_response
        gaia.client.last_metrics = None
        gaia.client.num_ctx = None
        gaia.client.max_tokens = 256

        expected_calls = [{"tool": "Ask LLM", "arguments": {"prompt": "hello"}}]
        score, reason, response = gaia.run_gaia_tool_use_test(
            SAMPLE_TOOLS, "Ask the model hello", expected_calls
        )
        assert score < 1.0

    def test_multi_step_chain_correct(self, gaia: GaiaKeywords) -> None:
        llm_response = json.dumps(
            {
                "tool_calls": [
                    {"tool": "Set LLM Model", "arguments": {"model": "mistral"}},
                    {"tool": "Ask LLM", "arguments": {"prompt": "explain recursion"}},
                ],
                "reasoning": "configure then ask",
            }
        )
        gaia.client = MagicMock()
        gaia.client.generate.return_value = llm_response
        gaia.client.last_metrics = None
        gaia.client.num_ctx = None
        gaia.client.max_tokens = 256

        expected_calls = [
            {"tool": "Set LLM Model", "arguments": {"model": "mistral"}},
            {"tool": "Ask LLM", "arguments": {"prompt": "explain recursion"}},
        ]
        score, reason, response = gaia.run_gaia_tool_use_test(
            SAMPLE_TOOLS, "Switch to mistral and ask about recursion", expected_calls
        )
        assert score == 1.0


# ---------------------------------------------------------------------------
# GaiaKeywords init
# ---------------------------------------------------------------------------


class TestGaiaKeywordsInit:
    @patch("rfc.gaia_keywords.create_provider")
    @patch("rfc.gaia_keywords.Grader")
    def test_default_init(self, MockGrader: MagicMock, mock_create: MagicMock) -> None:
        GaiaKeywords()
        mock_create.assert_called_once_with(timeout=5400, max_retries=2)
        MockGrader.assert_called_once_with(mock_create.return_value)

    @patch("rfc.gaia_keywords.create_provider")
    @patch("rfc.gaia_keywords.Grader")
    def test_custom_timeout(self, MockGrader: MagicMock, mock_create: MagicMock) -> None:
        GaiaKeywords(timeout=60, max_retries=5)
        mock_create.assert_called_once_with(timeout=60, max_retries=5)
