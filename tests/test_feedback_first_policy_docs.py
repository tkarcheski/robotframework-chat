"""Pin the feedback-first loop policy (#499) into the role docs.

The pipeline's automation north star is human-approves-PRs-only; these tests
keep the load-bearing policy text from silently regressing out of the role
prompts and the shared contract.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (REPO / rel).read_text()


class TestRolesContract:
    def test_rule_11_feedback_before_new_work(self) -> None:
        text = _read("ai/ROLES.md")
        assert "Feedback before new work" in text
        assert "Automation north star" in text
        assert "reviewing and approving PRs" in text


class TestEngineeringPrompt:
    def test_step_zero_services_open_prs_first(self) -> None:
        text = _read(".claude/agents/engineering.md")
        assert "Service your open PRs FIRST" in text
        # step 0 must come before the queue pull
        assert text.index("Service your open PRs FIRST") < text.index(
            "Pull the queue"
        )
        assert "TEST-PLAN: FAIL" in text
        assert "gh pr checks" in text


class TestProjectManagementPrompt:
    def test_flow_sweep_enforces_feedback_aging(self) -> None:
        text = _read(".claude/agents/project-management.md")
        assert "PR feedback aging" in text

    def test_merge_ready_requires_pass_and_resolved_threads(self) -> None:
        text = _read(".claude/agents/project-management.md")
        assert "Merge-ready has two conditions" in text
        assert "zero unresolved review threads" in text


class TestTestDesignPrompt:
    def test_verdict_threads_serviced_first(self) -> None:
        text = _read(".claude/agents/test-design.md")
        assert "Service your verdict threads FIRST" in text
        assert "stale verdict" in text

    def test_current_verdict_invariant(self) -> None:
        # normalize hard wraps so the pin survives reflowing
        text = " ".join(_read(".claude/agents/test-design.md").split())
        assert "every open PR carries a current verdict" in text


class TestDesignPrompt:
    def test_heartbeat_routes_through_pm(self) -> None:
        text = _read(".claude/agents/design.md")
        assert "The heartbeat" in text
        assert "Route through project-management" in text
