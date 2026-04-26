"""Tests for agent tool definitions and call tracking."""

import json
import pytest
from rfc.agent_tool import ToolSchema, ToolCall, ToolResult


class TestToolSchema:
    """ToolSchema: Define tool interface with JSON Schema parameters."""

    def test_creates_tool_schema(self):
        schema = ToolSchema(
            name="git_clone",
            description="Clone a Git repository",
            parameters={"url": {"type": "string"}, "path": {"type": "string"}},
            required=["url"],
        )
        assert schema.name == "git_clone"
        assert schema.description == "Clone a Git repository"
        assert "url" in schema.parameters
        assert schema.required == ["url"]

    def test_schema_is_frozen(self):
        schema = ToolSchema(
            name="test_tool",
            description="Test",
            parameters={},
            required=[],
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            schema.name = "other_name"

    def test_schema_with_complex_parameters(self):
        params = {
            "config": {
                "type": "object",
                "properties": {
                    "timeout": {"type": "integer"},
                    "retries": {"type": "integer"},
                },
            },
            "flags": {"type": "array", "items": {"type": "string"}},
        }
        schema = ToolSchema(
            name="complex_tool", description="", parameters=params, required=["config"]
        )
        assert schema.parameters == params


class TestToolCall:
    """ToolCall: Capture one tool invocation with arguments and metadata."""

    def test_creates_tool_call(self):
        call = ToolCall(
            id="call-001",
            tool_name="git_clone",
            arguments={"url": "https://github.com/foo/bar.git", "path": "/tmp/bar"},
            timestamp=1234567890.0,
            call_number=1,
        )
        assert call.id == "call-001"
        assert call.tool_name == "git_clone"
        assert call.arguments["url"] == "https://github.com/foo/bar.git"
        assert call.call_number == 1

    def test_tool_call_is_frozen(self):
        call = ToolCall(
            id="call-001",
            tool_name="test",
            arguments={},
            timestamp=0.0,
            call_number=0,
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            call.arguments = {}

    def test_tool_call_with_empty_arguments(self):
        call = ToolCall(
            id="call-001",
            tool_name="get_time",
            arguments={},
            timestamp=1234567890.0,
            call_number=0,
        )
        assert call.arguments == {}

    def test_tool_call_tracks_order(self):
        call1 = ToolCall("c1", "tool_a", {}, 100.0, 0)
        call2 = ToolCall("c2", "tool_b", {}, 101.0, 1)
        call3 = ToolCall("c3", "tool_c", {}, 102.0, 2)

        assert call1.call_number < call2.call_number < call3.call_number


class TestToolResult:
    """ToolResult: Capture outcome of one tool execution."""

    def test_creates_successful_result(self):
        result = ToolResult(
            tool_call_id="call-001",
            success=True,
            output="Repository cloned successfully",
            error=None,
            execution_time_ms=1250.5,
        )
        assert result.tool_call_id == "call-001"
        assert result.success is True
        assert result.output == "Repository cloned successfully"
        assert result.error is None
        assert result.execution_time_ms == 1250.5

    def test_creates_failed_result(self):
        result = ToolResult(
            tool_call_id="call-002",
            success=False,
            output="",
            error="Repository not found",
            execution_time_ms=500.0,
        )
        assert result.success is False
        assert result.error == "Repository not found"

    def test_result_with_json_output(self):
        json_output = json.dumps({"status": "ok", "files": 42})
        result = ToolResult(
            tool_call_id="call-003",
            success=True,
            output=json_output,
            execution_time_ms=100.0,
        )
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert parsed["files"] == 42

    def test_result_defaults(self):
        result = ToolResult(tool_call_id="call-004", success=True, output="Done")
        assert result.error is None
        assert result.execution_time_ms == 0.0

    def test_result_is_frozen(self):
        result = ToolResult("c1", True, "output")
        with pytest.raises(Exception):  # FrozenInstanceError
            result.output = "changed"
