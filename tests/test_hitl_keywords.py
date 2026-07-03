"""Tests for rfc.hitl_keywords.HitlKeywords (#384).

The keyword library is the non-interactive MVP surface: humans (or a
test standing in for one) resolve interactions by updating the
``hitl_interactions`` table; ``Wait For Human Input`` polls with a
timeout and fails closed to ``expired``.
"""

import pytest

from rfc.hitl_gate import HitlApprovalError
from rfc.hitl_keywords import HitlKeywords

SESSION = "sess-kw"
ACTION = "deploy:prod"
ARGS = {"target": "prod", "replicas": 3}


@pytest.fixture
def kw(tmp_path) -> HitlKeywords:
    return HitlKeywords(db_path=str(tmp_path / "hitl.db"))


class TestConnection:
    def test_keywords_require_a_connected_database(self):
        lib = HitlKeywords()
        with pytest.raises(RuntimeError, match="Connect Hitl Database"):
            lib.set_goal(SESSION, "ship it")

    def test_connect_requires_a_target(self):
        lib = HitlKeywords()
        with pytest.raises(ValueError):
            lib.connect_hitl_database()

    def test_connect_via_keyword(self, tmp_path):
        lib = HitlKeywords()
        lib.connect_hitl_database(db_path=str(tmp_path / "hitl.db"))
        assert lib.set_goal(SESSION, "ship it")


class TestGoals:
    def test_set_goal_is_recorded_resolved(self, kw):
        goal_id = kw.set_goal(SESSION, "Ship the HITL MVP")
        row = kw.get_interaction(goal_id)
        assert row["kind"] == "goal"
        assert row["status"] == "approved"
        assert row["prompt"] == "Ship the HITL MVP"
        assert row["resolved_at"]

    def test_get_current_goal_returns_latest(self, kw):
        kw.set_goal(SESSION, "first goal")
        kw.set_goal(SESSION, "second goal")
        assert kw.get_current_goal(SESSION) == "second goal"

    def test_get_current_goal_missing_raises(self, kw):
        with pytest.raises(LookupError):
            kw.get_current_goal("no-such-session")


class TestClarificationAndInput:
    def test_request_clarification_is_pending(self, kw):
        cid = kw.request_clarification(SESSION, "Which region?")
        row = kw.get_interaction(cid)
        assert row["kind"] == "clarification"
        assert row["status"] == "pending"
        assert row["expires_at"]

    def test_request_human_input_is_pending(self, kw):
        iid = kw.request_human_input(SESSION, "Provide the deploy window")
        row = kw.get_interaction(iid)
        assert row["kind"] == "input"
        assert row["status"] == "pending"


class TestResolveInteraction:
    def test_resolve_approved_sets_response(self, kw):
        cid = kw.request_clarification(SESSION, "Which region?")
        row = kw.resolve_interaction(cid, "approved", response="us-east-1 only")
        assert row["status"] == "approved"
        assert row["response"] == "us-east-1 only"
        assert row["resolved_at"]

    def test_resolve_denied(self, kw):
        aid = kw.request_human_approval(SESSION, "Roll out?", ACTION, ARGS)
        row = kw.resolve_interaction(aid, "denied", response="not today")
        assert row["status"] == "denied"

    def test_resolve_rejects_bad_status(self, kw):
        cid = kw.request_clarification(SESSION, "Which region?")
        with pytest.raises(ValueError):
            kw.resolve_interaction(cid, "expired")
        with pytest.raises(ValueError):
            kw.resolve_interaction(cid, "pending")

    def test_resolve_twice_fails_closed(self, kw):
        cid = kw.request_clarification(SESSION, "Which region?")
        kw.resolve_interaction(cid, "denied")
        with pytest.raises(HitlApprovalError, match="denied"):
            kw.resolve_interaction(cid, "approved")

    def test_resolve_missing_raises(self, kw):
        with pytest.raises(LookupError):
            kw.resolve_interaction("ghost", "approved")

    def test_stale_resolution_fails_closed_and_marks_expired(self, kw):
        """rpelevin test 3: stale or expired approval responses fail closed."""
        aid = kw.request_human_approval(
            SESSION, "Roll out?", ACTION, ARGS, expires_in=0
        )
        with pytest.raises(HitlApprovalError, match="expire"):
            kw.resolve_interaction(aid, "approved", response="too late")
        assert kw.get_interaction(aid)["status"] == "expired"


class TestApprovals:
    def test_request_human_approval_binds_digest(self, kw):
        aid = kw.request_human_approval(SESSION, "Roll out?", ACTION, ARGS)
        row = kw.get_interaction(aid)
        assert row["kind"] == "approval"
        assert row["target_action_id"] == ACTION
        assert len(row["args_digest"]) == 64
        assert row["expires_at"]

    def test_request_human_approval_requires_action_id(self, kw):
        with pytest.raises(ValueError):
            kw.request_human_approval(SESSION, "Roll out?", "", ARGS)

    def test_pending_approval_does_not_authorize(self, kw):
        kw.request_human_approval(SESSION, "Roll out?", ACTION, ARGS)
        assert kw.is_action_approved(SESSION, ACTION, ARGS) is False

    def test_approved_approval_authorizes_exact_action(self, kw):
        aid = kw.request_human_approval(SESSION, "Roll out?", ACTION, ARGS)
        kw.resolve_interaction(aid, "approved", response="go")
        assert kw.is_action_approved(SESSION, ACTION, ARGS) is True
        assert kw.ensure_action_approved(SESSION, ACTION, ARGS) == aid

    def test_digest_mismatch_fails_closed(self, kw):
        aid = kw.request_human_approval(SESSION, "Roll out?", ACTION, ARGS)
        kw.resolve_interaction(aid, "approved")
        assert (
            kw.is_action_approved(SESSION, ACTION, {"target": "prod", "replicas": 4})
            is False
        )

    def test_clarification_response_does_not_authorize(self, kw):
        """rpelevin test 1: a clarification response resumes reasoning but
        cannot authorize a high-risk action — even when it spoofs the
        action id and args of the pending action."""
        cid = kw.request_clarification(
            SESSION, "Should I run it?", target_action_id=ACTION, args=ARGS
        )
        kw.resolve_interaction(cid, "approved", response="yes, run it")
        assert kw.is_action_approved(SESSION, ACTION, ARGS) is False
        with pytest.raises(HitlApprovalError):
            kw.ensure_action_approved(SESSION, ACTION, ARGS)

    def test_expired_approval_fails_closed(self, kw):
        aid = kw.request_human_approval(
            SESSION, "Roll out?", ACTION, ARGS, expires_in=0.05
        )
        kw.resolve_interaction(aid, "approved")
        import time

        time.sleep(0.1)
        assert kw.is_action_approved(SESSION, ACTION, ARGS) is False


class TestWaitForHumanInput:
    def test_returns_resolved_row_immediately(self, kw):
        cid = kw.request_clarification(SESSION, "Which region?")
        kw.resolve_interaction(cid, "approved", response="us-east-1")
        row = kw.wait_for_human_input(cid, timeout=1, poll_interval=0.05)
        assert row["status"] == "approved"
        assert row["response"] == "us-east-1"

    def test_timeout_marks_row_expired(self, kw):
        iid = kw.request_human_input(SESSION, "Deploy window?")
        row = kw.wait_for_human_input(iid, timeout=0.3, poll_interval=0.05)
        assert row["status"] == "expired"
        # Fail-closed persistence: the table row itself is expired, so a
        # late human response can no longer resurrect the request.
        assert kw.get_interaction(iid)["status"] == "expired"

    def test_row_expiry_beats_wait_timeout(self, kw):
        iid = kw.request_human_input(SESSION, "Deploy window?", expires_in=0)
        row = kw.wait_for_human_input(iid, timeout=5, poll_interval=0.05)
        assert row["status"] == "expired"

    def test_missing_interaction_raises(self, kw):
        with pytest.raises(LookupError):
            kw.wait_for_human_input("ghost", timeout=0.1)


class TestCheckApprovalStatus:
    def test_reports_stored_status(self, kw):
        cid = kw.request_clarification(SESSION, "Which region?")
        assert kw.check_approval_status(cid) == "pending"
        kw.resolve_interaction(cid, "approved")
        assert kw.check_approval_status(cid) == "approved"

    def test_reports_effective_expiry_of_pending_row(self, kw):
        aid = kw.request_human_approval(
            SESSION, "Roll out?", ACTION, ARGS, expires_in=0
        )
        assert kw.check_approval_status(aid) == "expired"
