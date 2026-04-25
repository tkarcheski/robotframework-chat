"""Tests for rfc.tool_call_schema_keywords.ToolCallSchemaKeywords."""

import json
from typing import Any, List, Tuple
from unittest.mock import MagicMock, patch

import pytest

from rfc.tool_call_schema_keywords import (
    ToolCallSchemaKeywords,
    extract_tool_call,
    validate_against_schema,
)


def _capture_rfc_data() -> Tuple[List[Tuple[str, str]], Any]:
    """Patch ``emit_rfc_data`` to record all emitted (key, value) pairs."""
    from unittest.mock import patch as _patch

    captured: List[Tuple[str, str]] = []

    def _fake(key: str, value: str) -> None:
        captured.append((key, value))

    return captured, _patch(
        "rfc.tool_call_schema_keywords.emit_rfc_data", side_effect=_fake
    )


def _score_for(captured: List[Tuple[str, str]]) -> str:
    return next(v for k, v in captured if k == "score")


# ---------------------------------------------------------------------------
# Fixture tool schemas
# ---------------------------------------------------------------------------

CREATE_USER_SCHEMA = {
    "name": "create_user",
    "description": "Create a new user account.",
    "parameters": {
        "type": "object",
        "properties": {
            "username": {"type": "string"},
            "email": {"type": "string"},
            "role": {"type": "string", "enum": ["admin", "editor", "viewer"]},
            "age": {"type": "integer"},
            "is_active": {"type": "boolean"},
        },
        "required": ["username", "email", "role"],
    },
}

GET_BY_ID_SCHEMA = {
    "name": "get_user_by_id",
    "description": "Look up a user by their numeric ID.",
    "parameters": {
        "type": "object",
        "properties": {"user_id": {"type": "integer"}},
        "required": ["user_id"],
    },
}

GET_BY_EMAIL_SCHEMA = {
    "name": "get_user_by_email",
    "description": "Look up a user by their email address.",
    "parameters": {
        "type": "object",
        "properties": {"email": {"type": "string"}},
        "required": ["email"],
    },
}


# ---------------------------------------------------------------------------
# extract_tool_call: parse a JSON tool call from messy LLM text
# ---------------------------------------------------------------------------


class TestExtractToolCall:
    def test_extracts_plain_json(self) -> None:
        text = '{"tool": "create_user", "arguments": {"username": "alice"}}'
        call = extract_tool_call(text)
        assert call == {
            "tool": "create_user",
            "arguments": {"username": "alice"},
        }

    def test_strips_markdown_fence(self) -> None:
        text = '```json\n{"tool": "create_user", "arguments": {"x": 1}}\n```'
        call = extract_tool_call(text)
        assert call["tool"] == "create_user"

    def test_extracts_from_surrounding_prose(self) -> None:
        text = (
            "Sure! Here is the call:\n"
            '{"tool": "create_user", "arguments": {"username": "bob"}}\n'
            "Let me know if you need anything else."
        )
        call = extract_tool_call(text)
        assert call["tool"] == "create_user"
        assert call["arguments"]["username"] == "bob"

    def test_accepts_openai_name_key(self) -> None:
        """OpenAI-style {"name": ..., "arguments": ...} is normalized."""
        text = '{"name": "create_user", "arguments": {"username": "x"}}'
        call = extract_tool_call(text)
        assert call["tool"] == "create_user"

    def test_accepts_function_wrapper(self) -> None:
        """Anthropic/OpenAI wrapper {"function": {...}} is normalized."""
        text = '{"function": {"name": "create_user", "arguments": {"username": "x"}}}'
        call = extract_tool_call(text)
        assert call["tool"] == "create_user"
        assert call["arguments"] == {"username": "x"}

    def test_arguments_as_json_string_is_parsed(self) -> None:
        """OpenAI emits arguments as a stringified JSON; we parse it."""
        text = '{"name": "create_user", "arguments": "{\\"username\\": \\"x\\"}"}'
        call = extract_tool_call(text)
        assert call["arguments"] == {"username": "x"}

    def test_returns_none_when_no_json(self) -> None:
        assert extract_tool_call("I cannot help with that.") is None

    def test_returns_none_when_json_lacks_tool_name(self) -> None:
        assert extract_tool_call('{"foo": "bar"}') is None

    def test_skips_first_json_block_without_tool_name(self) -> None:
        """A leading metadata JSON should not block extraction of the real call."""
        text = (
            '{"thinking": "I should look this up."}\n'
            "Here is the call:\n"
            '{"tool": "get_user_by_id", "arguments": {"user_id": 7}}'
        )
        call = extract_tool_call(text)
        assert call is not None
        assert call["tool"] == "get_user_by_id"
        assert call["arguments"] == {"user_id": 7}

    def test_skips_unparseable_first_block(self) -> None:
        """A malformed first ``{...}`` should not stop later valid extraction."""
        text = (
            '{not json at all}\n{"tool": "get_user_by_id", "arguments": {"user_id": 7}}'
        )
        call = extract_tool_call(text)
        assert call is not None
        assert call["tool"] == "get_user_by_id"


# ---------------------------------------------------------------------------
# validate_against_schema: deterministic schema validation
# ---------------------------------------------------------------------------


class TestValidateAgainstSchema:
    def test_correct_call_validates(self) -> None:
        call = {
            "tool": "create_user",
            "arguments": {
                "username": "alice",
                "email": "a@example.com",
                "role": "admin",
            },
        }
        result = validate_against_schema(call, [CREATE_USER_SCHEMA])
        assert result["schema_valid"] is True
        assert result["selected_tool"] == "create_user"
        assert result["missing_required"] == []
        assert result["extra_fields"] == []
        assert result["type_errors"] == []
        assert result["enum_violations"] == []

    def test_unknown_tool_name_flagged(self) -> None:
        call = {"tool": "bogus_tool", "arguments": {}}
        result = validate_against_schema(call, [CREATE_USER_SCHEMA])
        assert result["schema_valid"] is False
        assert result["unknown_tool"] is True

    def test_missing_required_field(self) -> None:
        call = {
            "tool": "create_user",
            "arguments": {"username": "alice", "email": "a@example.com"},
        }
        result = validate_against_schema(call, [CREATE_USER_SCHEMA])
        assert result["schema_valid"] is False
        assert "role" in result["missing_required"]

    def test_extra_field_flagged(self) -> None:
        call = {
            "tool": "create_user",
            "arguments": {
                "username": "alice",
                "email": "a@example.com",
                "role": "admin",
                "favourite_color": "blue",
            },
        }
        result = validate_against_schema(call, [CREATE_USER_SCHEMA])
        assert result["schema_valid"] is False
        assert "favourite_color" in result["extra_fields"]

    def test_invalid_enum_value(self) -> None:
        call = {
            "tool": "create_user",
            "arguments": {
                "username": "alice",
                "email": "a@example.com",
                "role": "superuser",
            },
        }
        result = validate_against_schema(call, [CREATE_USER_SCHEMA])
        assert result["schema_valid"] is False
        assert any(v["field"] == "role" for v in result["enum_violations"])

    def test_type_mismatch_string_for_integer(self) -> None:
        call = {
            "tool": "create_user",
            "arguments": {
                "username": "alice",
                "email": "a@example.com",
                "role": "admin",
                "age": "thirty",
            },
        }
        result = validate_against_schema(call, [CREATE_USER_SCHEMA])
        assert result["schema_valid"] is False
        assert any(e["field"] == "age" for e in result["type_errors"])

    def test_boolean_is_not_integer(self) -> None:
        """A bool must not pass integer type validation (Python quirk)."""
        call = {
            "tool": "create_user",
            "arguments": {
                "username": "alice",
                "email": "a@example.com",
                "role": "admin",
                "age": True,
            },
        }
        result = validate_against_schema(call, [CREATE_USER_SCHEMA])
        assert any(e["field"] == "age" for e in result["type_errors"])

    def test_picks_correct_tool_from_multiple(self) -> None:
        call = {
            "tool": "get_user_by_email",
            "arguments": {"email": "a@example.com"},
        }
        result = validate_against_schema(call, [GET_BY_ID_SCHEMA, GET_BY_EMAIL_SCHEMA])
        assert result["schema_valid"] is True
        assert result["selected_tool"] == "get_user_by_email"

    def test_no_tool_call_in_response(self) -> None:
        result = validate_against_schema(None, [CREATE_USER_SCHEMA])
        assert result["schema_valid"] is False
        assert result["no_call_detected"] is True


# ---------------------------------------------------------------------------
# ToolCallSchemaKeywords: integration with the LLM client
# ---------------------------------------------------------------------------


class TestToolCallSchemaKeywordsInit:
    @patch("rfc.tool_call_schema_keywords.create_provider")
    def test_default_init(self, mock_create: MagicMock) -> None:
        ToolCallSchemaKeywords()
        mock_create.assert_called_once_with(timeout=5400, max_retries=2)


class TestEvaluateToolCall:
    @patch("rfc.tool_call_schema_keywords.create_provider")
    def test_correct_call_passes(self, mock_create: MagicMock) -> None:
        kw = ToolCallSchemaKeywords()
        kw.client.generate.return_value = json.dumps(
            {
                "tool": "create_user",
                "arguments": {
                    "username": "alice",
                    "email": "alice@example.com",
                    "role": "admin",
                },
            }
        )
        result = kw.evaluate_tool_call(
            prompt="Create an admin user named alice with email alice@example.com.",
            tools=json.dumps([CREATE_USER_SCHEMA]),
        )
        assert result["schema_valid"] is True
        assert result["selected_tool"] == "create_user"

    @patch("rfc.tool_call_schema_keywords.create_provider")
    def test_expected_tool_mismatch_flagged(self, mock_create: MagicMock) -> None:
        kw = ToolCallSchemaKeywords()
        kw.client.generate.return_value = json.dumps(
            {"tool": "get_user_by_email", "arguments": {"email": "a@b.com"}}
        )
        result = kw.evaluate_tool_call(
            prompt="Look up user 42.",
            tools=json.dumps([GET_BY_ID_SCHEMA, GET_BY_EMAIL_SCHEMA]),
            expected_tool="get_user_by_id",
        )
        assert result["tool_correct"] is False
        assert result["selected_tool"] == "get_user_by_email"

    @patch("rfc.tool_call_schema_keywords.create_provider")
    def test_expected_args_mismatch_flagged(self, mock_create: MagicMock) -> None:
        kw = ToolCallSchemaKeywords()
        kw.client.generate.return_value = json.dumps(
            {"tool": "get_user_by_id", "arguments": {"user_id": 99}}
        )
        result = kw.evaluate_tool_call(
            prompt="Look up user 42.",
            tools=json.dumps([GET_BY_ID_SCHEMA]),
            expected_tool="get_user_by_id",
            expected_args=json.dumps({"user_id": 42}),
        )
        assert result["arg_value_errors"]
        assert result["arg_value_errors"][0]["field"] == "user_id"

    @patch("rfc.tool_call_schema_keywords.create_provider")
    def test_garbled_response_recorded(self, mock_create: MagicMock) -> None:
        kw = ToolCallSchemaKeywords()
        kw.client.generate.return_value = "Sorry, I cannot help."
        result = kw.evaluate_tool_call(
            prompt="Create a user.",
            tools=json.dumps([CREATE_USER_SCHEMA]),
        )
        assert result["schema_valid"] is False
        assert result["no_call_detected"] is True

    @patch("rfc.tool_call_schema_keywords.create_provider")
    def test_tools_arg_must_be_json(self, mock_create: MagicMock) -> None:
        kw = ToolCallSchemaKeywords()
        with pytest.raises(json.JSONDecodeError):
            kw.evaluate_tool_call(prompt="x", tools="not json")


class TestEvaluateToolCallScoring:
    """The emitted RFC score must reflect *all* failure modes, not just schema validity."""

    @patch("rfc.tool_call_schema_keywords.create_provider")
    def test_wrong_tool_selection_scores_zero(self, mock_create: MagicMock) -> None:
        """Wrong tool but valid schema → schema_valid=True yet score=0.0."""
        captured, ctx = _capture_rfc_data()
        kw = ToolCallSchemaKeywords()
        kw.client.generate.return_value = json.dumps(
            {"tool": "get_user_by_email", "arguments": {"email": "a@b.com"}}
        )
        with ctx:
            result = kw.evaluate_tool_call(
                prompt="Look up user 42.",
                tools=json.dumps([GET_BY_ID_SCHEMA, GET_BY_EMAIL_SCHEMA]),
                expected_tool="get_user_by_id",
            )
        assert result["schema_valid"] is True
        assert result["tool_correct"] is False
        assert result["overall_pass"] is False
        assert _score_for(captured) == "0.0"

    @patch("rfc.tool_call_schema_keywords.create_provider")
    def test_wrong_arg_values_score_zero(self, mock_create: MagicMock) -> None:
        """Right tool + valid schema but wrong extracted value → score=0.0."""
        captured, ctx = _capture_rfc_data()
        kw = ToolCallSchemaKeywords()
        kw.client.generate.return_value = json.dumps(
            {"tool": "get_user_by_id", "arguments": {"user_id": 99}}
        )
        with ctx:
            result = kw.evaluate_tool_call(
                prompt="Look up user 42.",
                tools=json.dumps([GET_BY_ID_SCHEMA]),
                expected_tool="get_user_by_id",
                expected_args=json.dumps({"user_id": 42}),
            )
        assert result["schema_valid"] is True
        assert result["arg_value_errors"]
        assert result["overall_pass"] is False
        assert _score_for(captured) == "0.0"

    @patch("rfc.tool_call_schema_keywords.create_provider")
    def test_fully_correct_call_scores_one(self, mock_create: MagicMock) -> None:
        captured, ctx = _capture_rfc_data()
        kw = ToolCallSchemaKeywords()
        kw.client.generate.return_value = json.dumps(
            {"tool": "get_user_by_id", "arguments": {"user_id": 42}}
        )
        with ctx:
            result = kw.evaluate_tool_call(
                prompt="Look up user 42.",
                tools=json.dumps([GET_BY_ID_SCHEMA]),
                expected_tool="get_user_by_id",
                expected_args=json.dumps({"user_id": 42}),
            )
        assert result["overall_pass"] is True
        assert _score_for(captured) == "1.0"
