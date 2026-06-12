"""Tests for scripts/check_submodule_ownership.py — CI guard for submodule pointer bumps.

The role contract (ai/GIT.md) assigns each submodule an owning role; only that
role's agent identity (<role>@agents.rfc) may commit a pointer bump. Humans
(any non-@agents.rfc author) always pass — they outrank agents.
"""

from __future__ import annotations

import pytest

from scripts.check_submodule_ownership import (
    SUBMODULE_OWNERS,
    GitlinkChange,
    evaluate_changes,
    is_agent_email,
)


class TestOwnershipTable:
    def test_results_owned_by_test_design(self) -> None:
        assert SUBMODULE_OWNERS["results"] == "test-design@agents.rfc"

    def test_monitoring_logs_owned_by_project_management(self) -> None:
        assert SUBMODULE_OWNERS["monitoring/logs"] == "project-management@agents.rfc"

    def test_elons_algorithm_owned_by_design(self) -> None:
        assert SUBMODULE_OWNERS[".claude/skills/elons-algorithm"] == "design@agents.rfc"


class TestIsAgentEmail:
    @pytest.mark.parametrize(
        "email",
        ["engineering@agents.rfc", "test-design@agents.rfc", "design@agents.rfc"],
    )
    def test_agent_identities(self, email: str) -> None:
        assert is_agent_email(email)

    @pytest.mark.parametrize(
        "email",
        ["tyler.karcheski@gmail.com", "someone@example.com", "noreply@anthropic.com"],
    )
    def test_human_identities(self, email: str) -> None:
        assert not is_agent_email(email)


class TestEvaluateChanges:
    def test_owner_may_bump_own_submodule(self) -> None:
        changes = [
            GitlinkChange(
                path="results", commit="abc1234", author_email="test-design@agents.rfc"
            )
        ]
        assert evaluate_changes(changes) == []

    def test_non_owner_agent_is_rejected(self) -> None:
        changes = [
            GitlinkChange(
                path="results", commit="abc1234", author_email="engineering@agents.rfc"
            )
        ]
        violations = evaluate_changes(changes)
        assert len(violations) == 1
        assert "results" in violations[0]
        assert "engineering@agents.rfc" in violations[0]
        assert "test-design@agents.rfc" in violations[0]

    def test_human_may_bump_anything(self) -> None:
        changes = [
            GitlinkChange(
                path="results", commit="abc1234", author_email="tyler.karcheski@gmail.com"
            ),
            GitlinkChange(
                path="monitoring/logs", commit="def5678", author_email="someone@example.com"
            ),
        ]
        assert evaluate_changes(changes) == []

    def test_unknown_submodule_bumped_by_agent_is_rejected(self) -> None:
        # A gitlink not in the table has no owner, so no agent may bump it.
        changes = [
            GitlinkChange(
                path="some/new/submodule", commit="abc1234", author_email="design@agents.rfc"
            )
        ]
        violations = evaluate_changes(changes)
        assert len(violations) == 1
        assert "some/new/submodule" in violations[0]

    def test_mixed_changes_report_only_violations(self) -> None:
        changes = [
            GitlinkChange(
                path="results", commit="a" * 7, author_email="test-design@agents.rfc"
            ),
            GitlinkChange(
                path="monitoring/logs", commit="b" * 7, author_email="design@agents.rfc"
            ),
        ]
        violations = evaluate_changes(changes)
        assert len(violations) == 1
        assert "monitoring/logs" in violations[0]

    def test_no_changes_no_violations(self) -> None:
        assert evaluate_changes([]) == []


class TestPrefixOwnership:
    def test_skill_pack_bump_by_design_allowed(self) -> None:
        changes = [
            GitlinkChange(
                path="vendor/skill-packs/mattpocock",
                commit="abc1234",
                author_email="design@agents.rfc",
            )
        ]
        assert evaluate_changes(changes) == []

    def test_skill_pack_bump_by_other_agent_rejected(self) -> None:
        changes = [
            GitlinkChange(
                path="vendor/skill-packs/mattpocock",
                commit="abc1234",
                author_email="engineering@agents.rfc",
            )
        ]
        violations = evaluate_changes(changes)
        assert len(violations) == 1
        assert "design@agents.rfc" in violations[0]


class TestKnowledgeOwnership:
    def test_knowledge_owned_by_design(self) -> None:
        assert SUBMODULE_OWNERS["knowledge"] == "design@agents.rfc"

    def test_knowledge_bump_by_other_agent_rejected(self) -> None:
        changes = [
            GitlinkChange(
                path="knowledge", commit="abc1234", author_email="test-design@agents.rfc"
            )
        ]
        violations = evaluate_changes(changes)
        assert len(violations) == 1
        assert "design@agents.rfc" in violations[0]
