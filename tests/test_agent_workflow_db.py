"""Tests for src/rfc/agent_workflow_db.py (SQLite backend round-trip)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rfc.agent_interaction import AgentInteraction
from rfc.agent_interaction_tracker import AgentInteractionTracker
from rfc.agent_tool import ToolCall, ToolResult
from rfc.agent_workflow import AgentWorkflow, WorkflowStatus
from rfc.agent_workflow_db import (
    AgentWorkflowDatabase,
    workflow_to_dict,
)


def _build_minimal_workflow(workflow_id: str = "wf-1") -> AgentWorkflow:
    tracker = AgentInteractionTracker(workflow_id, "claude", "Test task")
    tracker.start_interaction(1)
    tracker.add_message("user", "do thing")
    tracker.add_message("assistant", "ok")
    cid = tracker.add_tool_call("git", {"cmd": "status"})
    tracker.add_tool_result(cid, success=True, output="clean", execution_time_ms=12.5)
    tracker.set_interaction_state(
        reasoning="run git status",
        state_before={"branch": "main"},
        state_after={"branch": "main", "dirty": False},
    )
    tracker.end_interaction(success=True)
    return tracker.end_workflow(success=True)


@pytest.fixture
def db(tmp_path: Path) -> AgentWorkflowDatabase:
    return AgentWorkflowDatabase(db_path=str(tmp_path / "agent.db"))


class TestSerialisation:
    def test_workflow_to_dict_includes_interactions(self) -> None:
        wf = _build_minimal_workflow()
        d = workflow_to_dict(wf)
        assert d["workflow_id"] == "wf-1"
        assert d["status"] == WorkflowStatus.COMPLETED
        assert len(d["interactions"]) == 1
        assert d["interactions"][0]["tool_calls"][0]["tool_name"] == "git"

    def test_workflow_to_dict_is_json_serialisable(self) -> None:
        wf = _build_minimal_workflow()
        # Round-trip through json to confirm no non-serialisable values leaked.
        encoded = json.dumps(workflow_to_dict(wf), default=str)
        decoded = json.loads(encoded)
        assert decoded["agent_id"] == "claude"


class TestPersist:
    def test_persist_then_get(self, db: AgentWorkflowDatabase) -> None:
        wf = _build_minimal_workflow()
        pk = db.persist_workflow(wf)
        assert pk > 0
        loaded = db.get_workflow("wf-1")
        assert loaded is not None
        assert loaded["agent_id"] == "claude"
        assert loaded["status"] == "completed"
        assert len(loaded["interactions"]) == 1
        assert loaded["interactions"][0]["tool_calls"][0]["tool_name"] == "git"
        assert loaded["interactions"][0]["tool_results"][0]["success"] is True

    def test_get_returns_none_for_unknown(self, db: AgentWorkflowDatabase) -> None:
        assert db.get_workflow("does-not-exist") is None

    def test_idempotent_persist_does_not_duplicate(
        self, db: AgentWorkflowDatabase
    ) -> None:
        wf = _build_minimal_workflow()
        db.persist_workflow(wf)
        db.persist_workflow(wf)  # Persist twice
        assert db.get_table_row_count("agent_workflows") == 1
        assert db.get_table_row_count("agent_interactions") == 1
        assert db.get_table_row_count("agent_tool_calls") == 1
        assert db.get_table_row_count("agent_tool_results") == 1

    def test_re_persist_with_fewer_turns_drops_stale_rows(
        self, db: AgentWorkflowDatabase
    ) -> None:
        # First persist [1, 2]; then re-persist with only [1]. Old turn 2
        # rows in agent_interactions / agent_tool_calls / agent_tool_results
        # must not survive the re-persist or get_workflow() will return
        # phantom turns from prior runs.
        def _wf(turns: tuple[int, ...]) -> AgentWorkflow:
            interactions = tuple(
                AgentInteraction(
                    turn_number=t,
                    messages=(),
                    tool_calls=(
                        ToolCall(
                            id=f"call-{t}", tool_name="echo",
                            arguments={"n": t}, timestamp=float(t),
                            call_number=0,
                        ),
                    ),
                    tool_results=(
                        ToolResult(
                            tool_call_id=f"call-{t}", success=True,
                            output=str(t), error=None, execution_time_ms=1.0,
                        ),
                    ),
                    state_before={}, state_after={}, reasoning="",
                    duration_ms=0.0, success=True, error=None,
                )
                for t in turns
            )
            return AgentWorkflow(
                workflow_id="wf-shrink", agent_id="claude",
                task_description="Shrink", started_at=0.0, ended_at=10.0,
                status=WorkflowStatus.COMPLETED, interactions=interactions,
            )

        db.persist_workflow(_wf((1, 2)))
        db.persist_workflow(_wf((1,)))

        loaded = db.get_workflow("wf-shrink")
        assert loaded is not None
        assert [i["turn_number"] for i in loaded["interactions"]] == [1]
        assert db.get_table_row_count("agent_interactions") == 1
        assert db.get_table_row_count("agent_tool_calls") == 1
        assert db.get_table_row_count("agent_tool_results") == 1

    def test_re_persist_with_additional_tool_call_keeps_fk_consistent(
        self, db: AgentWorkflowDatabase
    ) -> None:
        # Mirrors the real-world re-persist case: the SAME workflow object
        # gains an additional tool call between two persist() calls, so call
        # IDs are stable across persists. The interaction is upserted (UPDATE
        # path), and the bug here was that cur.lastrowid returns 0 on UPDATE,
        # so the new tool call's interaction_id pointed at no parent row and
        # raised FOREIGN KEY constraint failed.
        call_a = ToolCall(
            id="call-a", tool_name="git", arguments={"cmd": "status"},
            timestamp=1.0, call_number=0,
        )
        call_b = ToolCall(
            id="call-b", tool_name="git", arguments={"cmd": "diff"},
            timestamp=2.0, call_number=1,
        )
        result_a = ToolResult(
            tool_call_id="call-a", success=True, output="clean", error=None,
            execution_time_ms=1.0,
        )
        result_b = ToolResult(
            tool_call_id="call-b", success=True, output="diff out", error=None,
            execution_time_ms=1.0,
        )

        def _wf(calls: tuple[ToolCall, ...], results: tuple[ToolResult, ...]) -> AgentWorkflow:
            interaction = AgentInteraction(
                turn_number=1, messages=(), tool_calls=calls, tool_results=results,
                state_before={}, state_after={}, reasoning="", duration_ms=0.0,
                success=True, error=None,
            )
            return AgentWorkflow(
                workflow_id="wf-extend", agent_id="claude",
                task_description="Extend turn", started_at=0.0, ended_at=10.0,
                status=WorkflowStatus.COMPLETED, interactions=(interaction,),
            )

        db.persist_workflow(_wf((call_a,), (result_a,)))
        db.persist_workflow(_wf((call_a, call_b), (result_a, result_b)))

        loaded = db.get_workflow("wf-extend")
        assert loaded is not None
        assert len(loaded["interactions"]) == 1
        calls = loaded["interactions"][0]["tool_calls"]
        assert sorted(c["call_id"] for c in calls) == ["call-a", "call-b"]
        results = loaded["interactions"][0]["tool_results"]
        assert sorted(r["call_id"] for r in results) == ["call-a", "call-b"]

    def test_persist_workflow_with_multiple_turns(
        self, db: AgentWorkflowDatabase
    ) -> None:
        tracker = AgentInteractionTracker("wf-multi", "claude", "Multi-turn")
        for turn in (1, 2, 3):
            tracker.start_interaction(turn)
            tracker.add_message("user", f"turn {turn}")
            cid = tracker.add_tool_call("calc", {"expr": str(turn)})
            tracker.add_tool_result(cid, success=True, output=str(turn))
            tracker.end_interaction(success=True)
        wf = tracker.end_workflow(success=True)

        db.persist_workflow(wf)
        loaded = db.get_workflow("wf-multi")
        assert loaded is not None
        assert len(loaded["interactions"]) == 3
        assert [i["turn_number"] for i in loaded["interactions"]] == [1, 2, 3]
        assert db.get_table_row_count("agent_tool_calls") == 3
        assert db.get_table_row_count("agent_tool_results") == 3

    def test_persist_workflow_with_failed_tool_call(
        self, db: AgentWorkflowDatabase
    ) -> None:
        tracker = AgentInteractionTracker("wf-fail", "claude", "Failure case")
        tracker.start_interaction(1)
        cid = tracker.add_tool_call("api", {"url": "/broken"})
        tracker.add_tool_result(
            cid, success=False, output="", error="500 Internal Server Error"
        )
        tracker.end_interaction(success=False, error="API call failed")
        wf = tracker.end_workflow(success=False, error="Workflow aborted")

        db.persist_workflow(wf)
        loaded = db.get_workflow("wf-fail")
        assert loaded is not None
        assert loaded["status"] == "failed"
        assert loaded["error"] == "Workflow aborted"
        assert loaded["interactions"][0]["success"] is False
        assert loaded["interactions"][0]["tool_results"][0]["success"] is False
        assert loaded["interactions"][0]["tool_results"][0]["error"] == (
            "500 Internal Server Error"
        )

    def test_messages_round_trip_via_json_column(
        self, db: AgentWorkflowDatabase
    ) -> None:
        wf = _build_minimal_workflow()
        db.persist_workflow(wf)
        loaded = db.get_workflow("wf-1")
        assert loaded is not None
        messages = loaded["interactions"][0]["messages"]
        assert [m["role"] for m in messages] == ["user", "assistant"]
        assert [m["content"] for m in messages] == ["do thing", "ok"]

    def test_state_snapshots_round_trip(self, db: AgentWorkflowDatabase) -> None:
        wf = _build_minimal_workflow()
        db.persist_workflow(wf)
        loaded = db.get_workflow("wf-1")
        assert loaded is not None
        assert loaded["interactions"][0]["state_before"] == {"branch": "main"}
        assert loaded["interactions"][0]["state_after"] == {
            "branch": "main",
            "dirty": False,
        }


class TestConstruction:
    def test_url_with_sqlite_prefix(self, tmp_path: Path) -> None:
        url = f"sqlite:///{tmp_path / 'x.db'}"
        db = AgentWorkflowDatabase(database_url=url)
        wf = _build_minimal_workflow("wf-url")
        db.persist_workflow(wf)
        assert db.get_table_row_count("agent_workflows") == 1

    def test_no_path_no_env_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AGENT_WORKFLOW_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(Exception, match="DATABASE_URL"):
            AgentWorkflowDatabase()

    def test_env_var_picked_up(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(
            "AGENT_WORKFLOW_DATABASE_URL", f"sqlite:///{tmp_path / 'env.db'}"
        )
        db = AgentWorkflowDatabase()
        assert db.get_table_row_count("agent_workflows") == 0
