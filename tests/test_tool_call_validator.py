"""Tests for tool-call validation."""

import json

from rfc.agent_tool import ToolCall, ToolSchema
from rfc.tool_call_validator import ToolCallValidator, ToolResultValidator


class TestToolCallValidator:
    """ToolCallValidator: Schema, ordering, and result validation."""

    def test_creates_validator(self):
        validator = ToolCallValidator()
        assert validator.schemas == {}

    def test_register_tool_schema(self):
        validator = ToolCallValidator()
        schema = ToolSchema(
            name="git_clone",
            description="Clone a repository",
            parameters={"url": {"type": "string"}, "path": {"type": "string"}},
            required=["url"],
        )
        validator.register_tool(schema)

        assert "git_clone" in validator.schemas
        assert validator.schemas["git_clone"].name == "git_clone"

    def test_register_multiple_schemas(self):
        validator = ToolCallValidator()
        schema1 = ToolSchema("tool_a", "", {}, [])
        schema2 = ToolSchema("tool_b", "", {}, [])
        schema3 = ToolSchema("tool_c", "", {}, [])

        validator.register_tool(schema1)
        validator.register_tool(schema2)
        validator.register_tool(schema3)

        assert len(validator.schemas) == 3

    def test_validate_call_schema_success(self):
        validator = ToolCallValidator()
        schema = ToolSchema(
            name="git_clone",
            description="",
            parameters={"url": {"type": "string"}},
            required=["url"],
        )
        validator.register_tool(schema)

        call = ToolCall(
            id="c1",
            tool_name="git_clone",
            arguments={"url": "https://github.com/foo/bar.git"},
            timestamp=1.0,
            call_number=0,
        )

        valid, msg = validator.validate_call_schema(call)
        assert valid is True
        assert msg == ""

    def test_validate_call_schema_unregistered_tool(self):
        validator = ToolCallValidator()
        call = ToolCall(
            id="c1",
            tool_name="unknown_tool",
            arguments={},
            timestamp=1.0,
            call_number=0,
        )

        valid, msg = validator.validate_call_schema(call)
        assert valid is False
        assert "not registered" in msg

    def test_validate_call_schema_missing_required_param(self):
        validator = ToolCallValidator()
        schema = ToolSchema(
            name="git_clone",
            description="",
            parameters={"url": {"type": "string"}},
            required=["url"],
        )
        validator.register_tool(schema)

        # Missing required 'url' parameter
        call = ToolCall(
            id="c1",
            tool_name="git_clone",
            arguments={},
            timestamp=1.0,
            call_number=0,
        )

        valid, msg = validator.validate_call_schema(call)
        assert valid is False

    def test_validate_call_sequence_in_order(self):
        validator = ToolCallValidator()

        calls = [
            ToolCall("c1", "tool_a", {}, 1.0, 0),
            ToolCall("c2", "tool_b", {}, 2.0, 1),
            ToolCall("c3", "tool_c", {}, 3.0, 2),
        ]

        valid, msg = validator.validate_call_sequence(calls, ["tool_a", "tool_b", "tool_c"])
        assert valid is True
        assert msg == ""

    def test_validate_call_sequence_out_of_order(self):
        validator = ToolCallValidator()

        calls = [
            ToolCall("c1", "tool_a", {}, 1.0, 0),
            ToolCall("c2", "tool_b", {}, 2.0, 1),
            ToolCall("c3", "tool_c", {}, 3.0, 2),
        ]

        valid, msg = validator.validate_call_sequence(calls, ["tool_a", "tool_c", "tool_b"])
        assert valid is False
        assert "Expected" in msg

    def test_validate_call_sequence_no_expected_order(self):
        """When expected_order is None, any order is valid."""
        validator = ToolCallValidator()

        calls = [
            ToolCall("c1", "tool_a", {}, 1.0, 0),
            ToolCall("c2", "tool_b", {}, 2.0, 1),
        ]

        valid, msg = validator.validate_call_sequence(calls, None)
        assert valid is True

    def test_validate_call_sequence_empty_calls(self):
        validator = ToolCallValidator()

        valid, msg = validator.validate_call_sequence([], ["tool_a"])
        assert valid is False

    def test_validate_result_success(self):
        from rfc.agent_tool import ToolResult

        validator = ToolCallValidator()
        call = ToolCall("c1", "tool_a", {}, 1.0, 0)
        result = ToolResult("c1", True, "Success")

        valid, msg = validator.validate_result(call, result)
        assert valid is True

    def test_validate_result_failure(self):
        from rfc.agent_tool import ToolResult

        validator = ToolCallValidator()
        call = ToolCall("c1", "tool_a", {}, 1.0, 0)
        result = ToolResult("c1", False, "", error="Tool failed")

        valid, msg = validator.validate_result(call, result)
        assert valid is False
        assert "failed" in msg.lower()

    def test_validate_result_type_int(self):
        from rfc.agent_tool import ToolResult

        validator = ToolCallValidator()
        call = ToolCall("c1", "count_files", {}, 1.0, 0)
        result = ToolResult("c1", True, "42")

        valid, msg = validator.validate_result(call, result, expected_type=int)
        assert valid is True

    def test_validate_result_type_int_invalid(self):
        from rfc.agent_tool import ToolResult

        validator = ToolCallValidator()
        call = ToolCall("c1", "count_files", {}, 1.0, 0)
        result = ToolResult("c1", True, "not_a_number")

        valid, msg = validator.validate_result(call, result, expected_type=int)
        assert valid is False

    def test_validate_result_type_dict(self):
        from rfc.agent_tool import ToolResult

        validator = ToolCallValidator()
        call = ToolCall("c1", "parse_json", {}, 1.0, 0)
        result = ToolResult("c1", True, json.dumps({"key": "value"}))

        valid, msg = validator.validate_result(call, result, expected_type=dict)
        assert valid is True


class TestToolResultValidator:
    """ToolResultValidator: Assert output properties."""

    def test_creates_validator(self):
        validator = ToolResultValidator()
        assert validator.confidence_threshold == 0.8
        assert validator.assertions == []

    def test_assert_output_contains(self):
        from rfc.agent_tool import ToolResult

        validator = ToolResultValidator()
        validator.assert_output_contains("success")

        result = ToolResult("c1", True, "Operation completed successfully")
        valid, failures = validator.validate(result)

        assert valid is True
        assert failures == []

    def test_assert_output_contains_failure(self):
        from rfc.agent_tool import ToolResult

        validator = ToolResultValidator()
        validator.assert_output_contains("error")

        result = ToolResult("c1", True, "Operation completed successfully")
        valid, failures = validator.validate(result)

        assert valid is False
        assert len(failures) == 1

    def test_assert_output_matches_regex(self):
        from rfc.agent_tool import ToolResult

        validator = ToolResultValidator()
        validator.assert_output_matches_regex(r"PR #\d+")

        result = ToolResult("c1", True, "Created PR #456")
        valid, failures = validator.validate(result)

        assert valid is True

    def test_assert_output_matches_regex_failure(self):
        from rfc.agent_tool import ToolResult

        validator = ToolResultValidator()
        validator.assert_output_matches_regex(r"PR #\d+")

        result = ToolResult("c1", True, "Created merge request")
        valid, failures = validator.validate(result)

        assert valid is False

    def test_assert_result_valid_json(self):
        from rfc.agent_tool import ToolResult

        validator = ToolResultValidator()
        validator.assert_result_valid_json()

        result = ToolResult("c1", True, json.dumps({"status": "ok"}))
        valid, failures = validator.validate(result)

        assert valid is True

    def test_assert_result_valid_json_failure(self):
        from rfc.agent_tool import ToolResult

        validator = ToolResultValidator()
        validator.assert_result_valid_json()

        result = ToolResult("c1", True, "not valid json")
        valid, failures = validator.validate(result)

        assert valid is False

    def test_multiple_assertions(self):
        from rfc.agent_tool import ToolResult

        validator = ToolResultValidator()
        validator.assert_output_contains("success")
        validator.assert_output_matches_regex(r"file:\s+\w+")

        result = ToolResult("c1", True, "Operation completed successfully, file: test.txt")
        valid, failures = validator.validate(result)

        assert valid is True

    def test_multiple_assertions_partial_failure(self):
        from rfc.agent_tool import ToolResult

        validator = ToolResultValidator()
        validator.assert_output_contains("success")
        validator.assert_output_matches_regex(r"error")  # Won't match

        result = ToolResult("c1", True, "Operation completed successfully")
        valid, failures = validator.validate(result)

        assert valid is False
        assert len(failures) == 1

    def test_custom_confidence_threshold(self):
        validator = ToolResultValidator(confidence_threshold=0.9)
        assert validator.confidence_threshold == 0.9
