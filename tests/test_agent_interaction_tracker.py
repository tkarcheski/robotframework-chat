"""Tests for agent interaction tracking in real-time."""

import pytest

from rfc.agent_interaction_tracker import AgentInteractionTracker
from rfc.agent_workflow import WorkflowStatus


@pytest.fixture
def tracker() -> AgentInteractionTracker:
    return AgentInteractionTracker("wf-001", "agent", "Task")


@pytest.fixture
def active_tracker(tracker: AgentInteractionTracker) -> AgentInteractionTracker:
    tracker.start_interaction(1)
    return tracker


class TestAgentInteractionTracker:
    """AgentInteractionTracker: Capture multi-turn interactions in real-time."""

    def test_creates_tracker(self):
        tracker = AgentInteractionTracker(
            workflow_id="wf-001",
            agent_id="claude-agent",
            task="Resolve GitHub issue",
        )
        assert tracker.workflow.workflow_id == "wf-001"
        assert tracker.workflow.agent_id == "claude-agent"
        assert tracker.workflow.task_description == "Resolve GitHub issue"
        assert tracker.workflow.status == WorkflowStatus.RUNNING

    def test_tracker_initializes_workflow_correctly(self, tracker):
        assert tracker.workflow.interaction_count() == 0
        assert tracker.workflow.ended_at is None
        assert tracker.is_interaction_active() is False

    def test_start_and_end_single_interaction(self, tracker):
        tracker.start_interaction(1)
        tracker.add_message("user", "Hello")
        tracker.add_message("assistant", "I will help")

        interaction = tracker.end_interaction(True)

        assert interaction.turn_number == 1
        assert len(interaction.messages) == 2
        assert interaction.success is True
        assert tracker.workflow.interaction_count() == 1

    def test_add_messages_in_order(self, active_tracker):
        active_tracker.add_message("user", "First message")
        active_tracker.add_message("assistant", "Second message")
        active_tracker.add_message("system", "Third message")

        interaction = active_tracker.end_interaction(True)
        assert len(interaction.messages) == 3
        assert interaction.messages[0].role == "user"
        assert interaction.messages[1].role == "assistant"
        assert interaction.messages[2].role == "system"

    def test_add_tool_call_returns_call_id(self, active_tracker):
        call_id_1 = active_tracker.add_tool_call(
            "git_clone", {"url": "https://github.com/foo/bar"}
        )
        call_id_2 = active_tracker.add_tool_call(
            "filesystem", {"cmd": "write", "path": "/tmp/file"}
        )

        assert isinstance(call_id_1, str)
        assert isinstance(call_id_2, str)
        assert call_id_1 != call_id_2

    def test_tool_calls_tracked_in_order(self, active_tracker):
        id1 = active_tracker.add_tool_call("tool_a", {})
        active_tracker.add_tool_call("tool_b", {})
        id3 = active_tracker.add_tool_call("tool_c", {})

        interaction = active_tracker.end_interaction(True)
        assert len(interaction.tool_calls) == 3
        assert interaction.tool_calls[0].call_number == 0
        assert interaction.tool_calls[1].call_number == 1
        assert interaction.tool_calls[2].call_number == 2
        assert interaction.tool_calls[0].id == id1
        assert interaction.tool_calls[2].id == id3

    def test_add_tool_result(self, active_tracker):
        call_id = active_tracker.add_tool_call(
            "git_clone", {"url": "https://github.com/foo/bar"}
        )
        active_tracker.add_tool_result(
            call_id, True, "Cloned successfully", execution_time_ms=1500
        )

        interaction = active_tracker.end_interaction(True)
        assert len(interaction.tool_results) == 1
        assert interaction.tool_results[0].tool_call_id == call_id
        assert interaction.tool_results[0].success is True
        assert interaction.tool_results[0].output == "Cloned successfully"
        assert interaction.tool_results[0].execution_time_ms == 1500

    def test_tool_result_with_error(self, active_tracker):
        call_id = active_tracker.add_tool_call("api_call", {})
        active_tracker.add_tool_result(
            call_id, False, "", error="API returned 500", execution_time_ms=200
        )

        interaction = active_tracker.end_interaction(True)
        assert interaction.tool_results[0].success is False
        assert interaction.tool_results[0].error == "API returned 500"

    def test_set_interaction_state(self, active_tracker):
        state_before = {"cwd": "/tmp", "files": []}
        state_after = {"cwd": "/tmp/repo", "files": ["README.md"]}

        active_tracker.set_interaction_state(
            "Cloned and analyzed repo",
            state_before,
            state_after,
        )

        interaction = active_tracker.end_interaction(True)
        assert interaction.reasoning == "Cloned and analyzed repo"
        assert interaction.state_before == state_before
        assert interaction.state_after == state_after

    def test_end_interaction_with_failure(self, active_tracker):
        interaction = active_tracker.end_interaction(False, "Repository not found")
        assert interaction.success is False
        assert interaction.error == "Repository not found"

    def test_multiple_interactions_in_workflow(self, tracker):
        tracker.start_interaction(1)
        tracker.add_message("user", "Analyze issue")
        tracker.end_interaction(True)

        tracker.start_interaction(2)
        tracker.add_message("assistant", "Issue analyzed")
        id1 = tracker.add_tool_call("git_clone", {})
        tracker.add_tool_result(id1, True, "Cloned")
        tracker.end_interaction(True)

        tracker.start_interaction(3)
        tracker.add_message("assistant", "Creating PR")
        tracker.end_interaction(True)

        assert tracker.workflow.interaction_count() == 3

    def test_end_workflow(self, tracker):
        tracker.start_interaction(1)
        tracker.add_message("user", "Hello")
        tracker.end_interaction(True)

        workflow = tracker.end_workflow(True)

        assert workflow.status == WorkflowStatus.COMPLETED
        assert workflow.ended_at is not None
        assert workflow.error is None

    def test_end_workflow_with_failure(self, tracker):
        tracker.start_interaction(1)
        tracker.end_interaction(False, "Internal error")

        workflow = tracker.end_workflow(False, "Could not complete task")

        assert workflow.status == WorkflowStatus.FAILED
        assert workflow.error == "Could not complete task"

    def test_add_message_without_active_interaction_raises(self, tracker):
        with pytest.raises(RuntimeError, match="No active interaction"):
            tracker.add_message("user", "Hello")

    def test_start_interaction_while_active_raises(self, active_tracker):
        """Cannot start a new interaction while one is already active."""
        with pytest.raises(RuntimeError, match="already active"):
            active_tracker.start_interaction(2)

    def test_set_interaction_state_snapshots_dicts(self, active_tracker):
        """Mutating caller dicts after set_interaction_state must not affect the
        recorded interaction — snapshots must be independent of caller state."""
        state_before = {"step": "init", "files": ["a"]}
        state_after = {"step": "done", "files": ["a", "b"]}

        active_tracker.set_interaction_state("ran", state_before, state_after)

        state_before["step"] = "MUTATED"
        state_before["files"].append("x")
        state_after["step"] = "MUTATED"
        state_after["files"].append("y")

        interaction = active_tracker.end_interaction(True)

        assert interaction.state_before == {"step": "init", "files": ["a"]}
        assert interaction.state_after == {"step": "done", "files": ["a", "b"]}

    def test_full_realistic_workflow(self):
        """Simulate realistic agent workflow: analyze issue → clone → edit → create PR."""
        tracker = AgentInteractionTracker(
            workflow_id="wf-issue-123",
            agent_id="claude-agent",
            task="Resolve GitHub issue #123: Add dark mode",
        )

        tracker.start_interaction(1)
        tracker.add_message("user", "Resolve issue: Add dark mode toggle")
        tracker.add_message("assistant", "I'll analyze the issue and create a PR")
        tracker.set_interaction_state(
            "Starting analysis",
            {"step": "init"},
            {"step": "analyzed"},
        )
        tracker.end_interaction(True)

        tracker.start_interaction(2)
        clone_id = tracker.add_tool_call(
            "git_clone", {"url": "https://github.com/foo/bar.git"}
        )
        tracker.add_tool_result(
            clone_id, True, "Repository cloned", execution_time_ms=2000
        )

        edit_id = tracker.add_tool_call("filesystem_write", {"path": "src/theme.js"})
        tracker.add_tool_result(edit_id, True, "File written", execution_time_ms=100)

        tracker.set_interaction_state(
            "Cloned and edited source",
            {"files_modified": 0},
            {"files_modified": 1},
        )
        tracker.end_interaction(True)

        tracker.start_interaction(3)
        pr_id = tracker.add_tool_call(
            "github_create_pr",
            {"title": "Add dark mode", "body": "Implements dark mode toggle"},
        )
        tracker.add_tool_result(pr_id, True, "PR created #456", execution_time_ms=500)
        tracker.set_interaction_state(
            "Created PR",
            {"pr_created": False},
            {"pr_created": True, "pr_number": 456},
        )
        tracker.end_interaction(True)

        workflow = tracker.end_workflow(True)

        assert workflow.interaction_count() == 3
        assert workflow.status == WorkflowStatus.COMPLETED
        assert len(workflow.tool_calls_by_name()["git_clone"]) == 1
        assert len(workflow.tool_calls_by_name()["filesystem_write"]) == 1
        assert len(workflow.tool_calls_by_name()["github_create_pr"]) == 1
        assert len(workflow.successful_tool_calls()) == 3
