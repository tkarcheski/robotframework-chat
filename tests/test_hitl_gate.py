"""Tests for the fail-closed HITL approval gate and its enforcement in
the AgentSandbox tool-execution path (#384).

Authority model settled with @rpelevin on issue #384: only a
``kind='approval'`` row can authorize execution, the approval binds to
the exact ``target_action_id`` + ``args_digest``, and stale / expired /
missing approvals fail closed. A clarification (or goal / input) row
must never authorize — even when it references the same action and
carries an approved status.
"""

from datetime import datetime, timezone

import pytest

from rfc.agent_config import SandboxLimits
from rfc.agent_sandbox import AgentSandbox, sandbox_action_args, sandbox_action_id
from rfc.harness_db import HarnessDatabase
from rfc.harness_models import HitlInteraction
from rfc.hitl_gate import (
    HitlApprovalError,
    HitlApprovalGate,
    compute_args_digest,
)

SESSION = "sess-gate"
ACTION = "deploy:prod"
ARGS = {"target": "prod", "replicas": 3}
NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
PAST = "2026-07-01T11:00:00+00:00"
FUTURE = "2026-07-01T13:00:00+00:00"
CREATED = "2026-07-01T10:00:00+00:00"


class TestComputeArgsDigest:
    def test_deterministic_across_key_order(self):
        assert compute_args_digest({"a": 1, "b": 2}) == compute_args_digest(
            {"b": 2, "a": 1}
        )

    def test_changes_when_values_change(self):
        assert compute_args_digest({"a": 1}) != compute_args_digest({"a": 2})

    def test_changes_when_keys_change(self):
        assert compute_args_digest({"a": 1}) != compute_args_digest({"b": 1})

    def test_nested_mappings_supported(self):
        digest = compute_args_digest({"outer": {"inner": [1, 2, 3]}})
        assert len(digest) == 64

    def test_is_sha256_hex(self):
        digest = compute_args_digest({})
        assert len(digest) == 64
        int(digest, 16)  # raises if not hex


@pytest.fixture
def db(tmp_path) -> HarnessDatabase:
    return HarnessDatabase(db_path=str(tmp_path / "harness.db"))


@pytest.fixture
def gate(db) -> HitlApprovalGate:
    return HitlApprovalGate(db, SESSION, now=lambda: NOW)


def insert(db: HarnessDatabase, **overrides) -> str:
    row = dict(
        session_id=SESSION,
        kind="approval",
        prompt="May I?",
        created_at=CREATED,
        target_action_id=ACTION,
        args_digest=compute_args_digest(ARGS),
        status="approved",
        expires_at=FUTURE,
        resolved_at=CREATED,
    )
    row.update(overrides)
    return db.save_interaction(HitlInteraction(**row))


class TestGateDecisions:
    def test_no_rows_denies(self, gate):
        decision = gate.check(ACTION, ARGS)
        assert decision.allowed is False
        assert "no interaction" in decision.reason

    def test_valid_approval_allows(self, db, gate):
        row_id = insert(db)
        decision = gate.check(ACTION, ARGS)
        assert decision.allowed is True
        assert decision.interaction_id == row_id

    def test_clarification_never_authorizes(self, db, gate):
        """THE negative case: an approved clarification row referencing the
        exact action id and args digest still must not authorize."""
        insert(db, kind="clarification", response="yes, go ahead")
        decision = gate.check(ACTION, ARGS)
        assert decision.allowed is False
        assert "never authorizes" in decision.reason

    def test_goal_never_authorizes(self, db, gate):
        insert(db, kind="goal")
        assert gate.check(ACTION, ARGS).allowed is False

    def test_input_never_authorizes(self, db, gate):
        insert(db, kind="input")
        assert gate.check(ACTION, ARGS).allowed is False

    def test_pending_approval_denies(self, db, gate):
        insert(db, status="pending", resolved_at="")
        decision = gate.check(ACTION, ARGS)
        assert decision.allowed is False
        assert "not granted" in decision.reason

    def test_denied_approval_denies(self, db, gate):
        insert(db, status="denied")
        assert gate.check(ACTION, ARGS).allowed is False

    def test_digest_mismatch_denies(self, db, gate):
        insert(db)
        decision = gate.check(ACTION, {"target": "prod", "replicas": 4})
        assert decision.allowed is False
        assert "digest" in decision.reason

    def test_action_id_mismatch_denies(self, db, gate):
        insert(db)
        assert gate.check("deploy:staging", ARGS).allowed is False

    def test_expired_approval_fails_closed(self, db, gate):
        insert(db, expires_at=PAST)
        decision = gate.check(ACTION, ARGS)
        assert decision.allowed is False
        assert "expire" in decision.reason

    def test_approval_without_expiry_fails_closed(self, db, gate):
        insert(db, expires_at="")
        decision = gate.check(ACTION, ARGS)
        assert decision.allowed is False
        assert "expir" in decision.reason

    def test_expired_row_status_denies(self, db, gate):
        insert(db, status="expired")
        assert gate.check(ACTION, ARGS).allowed is False

    def test_valid_approval_wins_over_expired_sibling(self, db, gate):
        insert(db, expires_at=PAST)
        valid_id = insert(db)
        decision = gate.check(ACTION, ARGS)
        assert decision.allowed is True
        assert decision.interaction_id == valid_id

    def test_other_session_approval_denies(self, db):
        insert(db, session_id="someone-else")
        gate = HitlApprovalGate(db, SESSION, now=lambda: NOW)
        assert gate.check(ACTION, ARGS).allowed is False

    def test_require_raises_on_denial(self, db, gate):
        insert(db, kind="clarification")
        with pytest.raises(HitlApprovalError, match="never authorizes"):
            gate.require(ACTION, ARGS)

    def test_require_passes_on_approval(self, db, gate):
        insert(db)
        gate.require(ACTION, ARGS)  # must not raise


# ---------------------------------------------------------------------------
# Enforcement in the AgentSandbox tool-execution path
# ---------------------------------------------------------------------------


class FakeManager:
    """Minimal ContainerBackend double recording every call."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def create_container(self, config, name=None) -> str:
        self.calls.append("create_container")
        return "cid-1"

    def execute_command(self, container_id, command, timeout=30, workdir=None):
        self.calls.append("execute_command")
        return {"exit_code": 0, "stdout": ""}

    def copy_to_container(self, container_id, host_path, container_path) -> None:
        self.calls.append("copy_to_container")

    def stop_container(self, container_id, timeout=10) -> None:
        self.calls.append("stop_container")


@pytest.fixture
def scenario_dir(tmp_path):
    root = tmp_path / "scenarios" / "hello"
    (root / "repo").mkdir(parents=True)
    (root / "repo" / "app.py").write_text("print('hi')\n")
    (root / "agents").mkdir()
    (root / "agents" / "good.sh").write_text("#!/bin/sh\ntrue\n")
    (root / "scenario.yaml").write_text(
        "scenario_id: hello\n"
        "task: say hello\n"
        "test_command: pytest\n"
        "agents:\n"
        "  good: agents/good.sh\n"
    )
    return root


def make_sandbox(manager, gate=None) -> AgentSandbox:
    return AgentSandbox(
        limits=SandboxLimits(),
        manager=manager,
        approval_gate=gate,
    )


class TestSandboxEnforcement:
    def test_action_id_and_args_are_stable(self):
        assert sandbox_action_id("hello", "good") == "agent-sandbox:hello:good"
        assert sandbox_action_args("hello", "good", "claude-code") == {
            "scenario_id": "hello",
            "variant": "good",
            "agent_id": "claude-code",
        }

    def test_no_gate_runs_unchanged(self, scenario_dir):
        manager = FakeManager()
        result = make_sandbox(manager).run_scenario(scenario_dir)
        assert result.scenario_id == "hello"
        assert "create_container" in manager.calls

    def test_unapproved_action_is_blocked_before_any_execution(
        self, db, gate, scenario_dir
    ):
        manager = FakeManager()
        sandbox = make_sandbox(manager, gate=gate)
        with pytest.raises(HitlApprovalError):
            sandbox.run_scenario(scenario_dir)
        assert manager.calls == []  # fail closed: nothing executed

    def test_clarification_row_does_not_unblock_sandbox(self, db, gate, scenario_dir):
        """Negative enforcement test required by #384: a clarification row
        binding the same action id + digest must not gate-open the sandbox."""
        insert(
            db,
            kind="clarification",
            target_action_id=sandbox_action_id("hello", "good"),
            args_digest=compute_args_digest(
                sandbox_action_args("hello", "good", "claude-code")
            ),
        )
        manager = FakeManager()
        sandbox = make_sandbox(manager, gate=gate)
        with pytest.raises(HitlApprovalError, match="never authorizes"):
            sandbox.run_scenario(scenario_dir)
        assert manager.calls == []

    def test_approved_action_executes(self, db, gate, scenario_dir):
        insert(
            db,
            target_action_id=sandbox_action_id("hello", "good"),
            args_digest=compute_args_digest(
                sandbox_action_args("hello", "good", "claude-code")
            ),
        )
        manager = FakeManager()
        result = make_sandbox(manager, gate=gate).run_scenario(scenario_dir)
        assert result.scenario_id == "hello"
        assert "create_container" in manager.calls
        assert "stop_container" in manager.calls
