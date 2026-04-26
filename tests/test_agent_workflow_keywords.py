"""Tests for src/rfc/agent_workflow_keywords.py."""

from __future__ import annotations

import json
import logging

import pytest

from rfc.agent_workflow_keywords import AgentWorkflowKeywords


@pytest.fixture
def kw() -> AgentWorkflowKeywords:
    return AgentWorkflowKeywords()


class TestLifecycle:
    def test_summary_after_start_is_running(self, kw: AgentWorkflowKeywords) -> None:
        kw.start_agent_workflow("wf-1", "claude", "Test")
        summary = kw.get_workflow_summary()
        assert summary["workflow_id"] == "wf-1"
        assert summary["agent_id"] == "claude"
        assert summary["turns"] == 0
        assert summary["status"] == "running"

    def test_keyword_before_start_raises(
        self, kw: AgentWorkflowKeywords
    ) -> None:
        with pytest.raises(AssertionError, match="No active agent workflow"):
            kw.get_workflow_summary()
        with pytest.raises(AssertionError, match="No active agent workflow"):
            kw.start_interaction(1)

    def test_end_workflow_emits_rfc_data(
        self,
        kw: AgentWorkflowKeywords,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        kw.start_agent_workflow("wf-emit", "claude", "Emit")
        kw.start_interaction(1)
        kw.agent_message("user", "ping")
        kw.end_interaction(True)
        with caplog.at_level(logging.INFO, logger="RobotFramework"):
            payload = kw.end_agent_workflow(True)
        assert payload["status"] == "completed"
        assert payload["workflow_id"] == "wf-emit"
        # The rfc_data emitter logs through robot.api.logger; the payload
        # itself is what we care about.
        assert payload["interactions"][0]["messages"][0]["content"] == "ping"

    def test_summary_counts_turns_and_tool_calls(
        self, kw: AgentWorkflowKeywords
    ) -> None:
        kw.start_agent_workflow("wf-count", "claude", "Count")
        for turn in (1, 2):
            kw.start_interaction(turn)
            cid = kw.agent_calls_tool("calc", '{"x": 1}')
            kw.agent_receives_tool_result(cid, True, output="ok")
            kw.end_interaction(True)
        summary = kw.get_workflow_summary()
        assert summary["turns"] == 2
        assert summary["tool_calls"] == 2
        assert summary["successful_calls"] == 2


class TestMessages:
    def test_invalid_role_rejected(self, kw: AgentWorkflowKeywords) -> None:
        kw.start_agent_workflow("w", "a", "t")
        kw.start_interaction(1)
        with pytest.raises(ValueError, match="role must be one of"):
            kw.agent_message("not-a-role", "x")


class TestToolCalls:
    def test_invalid_arguments_json_rejected(
        self, kw: AgentWorkflowKeywords
    ) -> None:
        kw.start_agent_workflow("w", "a", "t")
        kw.start_interaction(1)
        with pytest.raises(ValueError, match="must be valid JSON"):
            kw.agent_calls_tool("git", "{not json")

    def test_non_object_arguments_rejected(
        self, kw: AgentWorkflowKeywords
    ) -> None:
        kw.start_agent_workflow("w", "a", "t")
        kw.start_interaction(1)
        with pytest.raises(ValueError, match="must decode to an object"):
            kw.agent_calls_tool("git", "[1,2,3]")

    def test_returns_uuid_call_id(self, kw: AgentWorkflowKeywords) -> None:
        kw.start_agent_workflow("w", "a", "t")
        kw.start_interaction(1)
        cid = kw.agent_calls_tool("git", '{"cmd": "status"}')
        assert isinstance(cid, str) and len(cid) > 10


class TestSchemaValidation:
    def test_register_and_validate_passes(
        self, kw: AgentWorkflowKeywords
    ) -> None:
        schema = json.dumps(
            {
                "description": "filesystem ops",
                "parameters": {"path": {}, "mode": {}},
                "required": ["path"],
            }
        )
        kw.register_tool_schema("fs", schema)
        kw.validate_tool_call_schema("fs", '{"path": "/tmp/x"}')

    def test_validate_missing_required_fails(
        self, kw: AgentWorkflowKeywords
    ) -> None:
        kw.register_tool_schema(
            "fs",
            json.dumps({"parameters": {"path": {}}, "required": ["path"]}),
        )
        with pytest.raises(AssertionError, match="Missing required parameter"):
            kw.validate_tool_call_schema("fs", "{}")

    def test_validate_unregistered_tool_fails(
        self, kw: AgentWorkflowKeywords
    ) -> None:
        with pytest.raises(AssertionError, match="not registered"):
            kw.validate_tool_call_schema("nope", "{}")


class TestAssertions:
    def test_assert_tool_was_called_pass(
        self, kw: AgentWorkflowKeywords
    ) -> None:
        kw.start_agent_workflow("w", "a", "t")
        kw.start_interaction(1)
        kw.agent_calls_tool("git", "{}")
        kw.agent_calls_tool("git", "{}")
        kw.end_interaction(True)
        kw.assert_tool_was_called("git", 2)

    def test_assert_tool_was_called_fail(
        self, kw: AgentWorkflowKeywords
    ) -> None:
        kw.start_agent_workflow("w", "a", "t")
        kw.start_interaction(1)
        kw.agent_calls_tool("git", "{}")
        kw.end_interaction(True)
        with pytest.raises(AssertionError, match="Expected 2"):
            kw.assert_tool_was_called("git", 2)

    def test_assert_tool_calls_in_order_pass(
        self, kw: AgentWorkflowKeywords
    ) -> None:
        kw.start_agent_workflow("w", "a", "t")
        kw.start_interaction(1)
        kw.agent_calls_tool("git", "{}")
        kw.end_interaction(True)
        kw.start_interaction(2)
        kw.agent_calls_tool("fs", "{}")
        kw.end_interaction(True)
        kw.assert_tool_calls_in_order("git", "fs")

    def test_assert_tool_calls_in_order_fail(
        self, kw: AgentWorkflowKeywords
    ) -> None:
        kw.start_agent_workflow("w", "a", "t")
        kw.start_interaction(1)
        kw.agent_calls_tool("fs", "{}")
        kw.agent_calls_tool("git", "{}")
        kw.end_interaction(True)
        with pytest.raises(AssertionError, match="Expected"):
            kw.assert_tool_calls_in_order("git", "fs")

    def test_assert_all_tool_calls_succeeded_pass(
        self, kw: AgentWorkflowKeywords
    ) -> None:
        kw.start_agent_workflow("w", "a", "t")
        kw.start_interaction(1)
        cid = kw.agent_calls_tool("git", "{}")
        kw.agent_receives_tool_result(cid, True, "ok")
        kw.end_interaction(True)
        kw.assert_all_tool_calls_succeeded()

    def test_assert_all_tool_calls_succeeded_fail(
        self, kw: AgentWorkflowKeywords
    ) -> None:
        kw.start_agent_workflow("w", "a", "t")
        kw.start_interaction(1)
        cid = kw.agent_calls_tool("api", "{}")
        kw.agent_receives_tool_result(cid, False, error="500")
        kw.end_interaction(False)
        with pytest.raises(AssertionError, match="failed: 500"):
            kw.assert_all_tool_calls_succeeded()


class TestStateSnapshot:
    def test_set_interaction_state_stores_json(
        self, kw: AgentWorkflowKeywords
    ) -> None:
        kw.start_agent_workflow("w", "a", "t")
        kw.start_interaction(1)
        kw.set_interaction_state(
            "thinking",
            state_before='{"step": 1}',
            state_after='{"step": 2}',
        )
        kw.end_interaction(True)
        payload = kw.end_agent_workflow(True)
        interaction = payload["interactions"][0]
        assert interaction["reasoning"] == "thinking"
        assert interaction["state_before"] == {"step": 1}
        assert interaction["state_after"] == {"step": 2}


class TestBoolCoercion:
    def test_string_true_coerced(self, kw: AgentWorkflowKeywords) -> None:
        kw.start_agent_workflow("w", "a", "t")
        kw.start_interaction(1)
        kw.end_interaction("true")
        payload = kw.end_agent_workflow("True")
        assert payload["status"] == "completed"

    def test_string_false_coerced(self, kw: AgentWorkflowKeywords) -> None:
        kw.start_agent_workflow("w", "a", "t")
        kw.start_interaction(1)
        kw.end_interaction("false")
        payload = kw.end_agent_workflow("false")
        assert payload["status"] == "failed"
