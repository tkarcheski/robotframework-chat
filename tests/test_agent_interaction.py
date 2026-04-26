"""Tests for agent interactions (conversation turns)."""

import pytest
from rfc.agent_tool import ToolCall, ToolResult
from rfc.agent_interaction import AgentMessage, AgentInteraction


class TestAgentMessage:
    """AgentMessage: One message in a multi-turn conversation."""

    def test_creates_message(self):
        msg = AgentMessage(
            role="user", content="Resolve the GitHub issue", timestamp=1234567890.0
        )
        assert msg.role == "user"
        assert msg.content == "Resolve the GitHub issue"
        assert msg.timestamp == 1234567890.0

    def test_message_roles(self):
        """Test valid roles: user, assistant, system."""
        user_msg = AgentMessage("user", "Hello", 1.0)
        assistant_msg = AgentMessage("assistant", "Hi", 2.0)
        system_msg = AgentMessage("system", "Context", 3.0)

        assert user_msg.role == "user"
        assert assistant_msg.role == "assistant"
        assert system_msg.role == "system"

    def test_message_is_frozen(self):
        msg = AgentMessage("user", "Test", 1.0)
        with pytest.raises(Exception):  # FrozenInstanceError
            msg.content = "Changed"


class TestAgentInteraction:
    """AgentInteraction: One complete turn (reasoning, actions, results)."""

    def test_creates_interaction(self):
        msg = AgentMessage("assistant", "I will clone the repo", 1.0)
        interaction = AgentInteraction(
            turn_number=1,
            messages=(msg,),
            tool_calls=(),
            tool_results=(),
            state_before={"cwd": "/tmp"},
            state_after={"cwd": "/tmp/repo"},
            reasoning="The issue requires cloning the repository first",
            duration_ms=1500.0,
            success=True,
        )
        assert interaction.turn_number == 1
        assert len(interaction.messages) == 1
        assert (
            interaction.reasoning == "The issue requires cloning the repository first"
        )
        assert interaction.success is True

    def test_interaction_with_tool_calls_and_results(self):
        call = ToolCall(
            id="call-1",
            tool_name="git_clone",
            arguments={"url": "https://github.com/foo/bar.git"},
            timestamp=1.0,
            call_number=0,
        )
        result = ToolResult(
            tool_call_id="call-1",
            success=True,
            output="Cloned successfully",
            execution_time_ms=1000.0,
        )
        interaction = AgentInteraction(
            turn_number=1,
            messages=(),
            tool_calls=(call,),
            tool_results=(result,),
            state_before={},
            state_after={},
            reasoning="",
            duration_ms=1000.0,
            success=True,
        )
        assert len(interaction.tool_calls) == 1
        assert len(interaction.tool_results) == 1
        assert interaction.tool_calls[0].tool_name == "git_clone"

    def test_interaction_failed_with_error(self):
        interaction = AgentInteraction(
            turn_number=1,
            messages=(),
            tool_calls=(),
            tool_results=(),
            state_before={},
            state_after={},
            reasoning="Attempted to clone",
            duration_ms=500.0,
            success=False,
            error="Repository not found",
        )
        assert interaction.success is False
        assert interaction.error == "Repository not found"

    def test_interaction_tracks_full_conversation_context(self):
        """Each turn includes full conversation history."""
        msg1 = AgentMessage("user", "Resolve issue X", 1.0)
        msg2 = AgentMessage("assistant", "I'll analyze it", 2.0)
        msg3 = AgentMessage("assistant", "Cloning repo...", 3.0)

        interaction = AgentInteraction(
            turn_number=2,
            messages=(msg1, msg2, msg3),  # Full history up to this turn
            tool_calls=(),
            tool_results=(),
            state_before={},
            state_after={},
            reasoning="",
            duration_ms=0.0,
            success=True,
        )
        assert len(interaction.messages) == 3
        assert interaction.messages[0].content == "Resolve issue X"
        assert interaction.messages[2].content == "Cloning repo..."

    def test_interaction_is_frozen(self):
        interaction = AgentInteraction(
            turn_number=1,
            messages=(),
            tool_calls=(),
            tool_results=(),
            state_before={},
            state_after={},
            reasoning="",
            duration_ms=0.0,
            success=True,
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            interaction.reasoning = "changed"

    def test_interaction_state_snapshots(self):
        """State before/after capture execution context."""
        state_before = {
            "cwd": "/tmp",
            "files_modified": [],
            "git_branch": "main",
        }
        state_after = {
            "cwd": "/tmp/repo",
            "files_modified": ["README.md"],
            "git_branch": "feature-x",
        }
        interaction = AgentInteraction(
            turn_number=1,
            messages=(),
            tool_calls=(),
            tool_results=(),
            state_before=state_before,
            state_after=state_after,
            reasoning="Cloned and switched branch",
            duration_ms=1000.0,
            success=True,
        )
        assert interaction.state_before["git_branch"] == "main"
        assert interaction.state_after["git_branch"] == "feature-x"
        assert interaction.state_after["files_modified"] == ["README.md"]
