"""Tests for the #423 route-don't-file triage policy docs.

Issue #423: review findings on an open PR must block merge
(changes-requested), not become standalone post-merge issues. The policy
lives in two docs; these tests pin its presence in both so it cannot
silently regress.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRIAGE_SKILL = ROOT / ".claude" / "skills" / "triage-issues-prs" / "SKILL.md"
PM_AGENT = ROOT / ".claude" / "agents" / "project-management.md"


class TestTriageSkillPolicy:
    def test_skill_doc_exists(self) -> None:
        assert TRIAGE_SKILL.is_file()

    def test_route_dont_file_section_present(self) -> None:
        text = TRIAGE_SKILL.read_text(encoding="utf-8")
        assert "## Review findings on open PRs — route, don't file (#423)" in text

    def test_forbids_standalone_issues_for_open_prs(self) -> None:
        text = TRIAGE_SKILL.read_text(encoding="utf-8")
        assert "Never mint a standalone issue from a review finding" in text

    def test_requires_thread_url_on_post_merge_issues(self) -> None:
        text = TRIAGE_SKILL.read_text(encoding="utf-8")
        assert "review-thread URL" in text


class TestProjectManagementPolicy:
    def test_agent_doc_exists(self) -> None:
        assert PM_AGENT.is_file()

    def test_triage_sweep_routes_review_feedback(self) -> None:
        text = PM_AGENT.read_text(encoding="utf-8")
        assert "Route review feedback (#423)" in text

    def test_open_pr_findings_are_changes_requested(self) -> None:
        text = PM_AGENT.read_text(encoding="utf-8")
        assert "changes-requested, not a post-merge issue" in text
