"""Tests for scripts/check_agent_signoffs.py — agent commit attribution guard.

Per ai/GIT.md, every agent-authored commit (author email *@agents.rfc) must
carry a Signed-off-by trailer with an @agents.rfc identity AND a Model:
trailer naming the model that drove the role. Human commits are exempt.
"""

from __future__ import annotations

from scripts.check_agent_signoffs import CommitMeta, evaluate_commits


def _commit(
    email: str = "design@agents.rfc",
    signoffs: list[str] | None = None,
    model: str = "claude-fable-5",
) -> CommitMeta:
    return CommitMeta(
        commit="abc1234",
        author_email=email,
        signoff_emails=signoffs if signoffs is not None else [email],
        models=[model] if model else [],
    )


class TestEvaluateCommits:
    def test_compliant_agent_commit_passes(self) -> None:
        assert evaluate_commits([_commit()]) == []

    def test_human_commit_exempt(self) -> None:
        commit = _commit(email="tyler.karcheski@gmail.com", signoffs=[], model="")
        assert evaluate_commits([commit]) == []

    def test_missing_signoff_fails(self) -> None:
        violations = evaluate_commits([_commit(signoffs=[])])
        assert len(violations) == 1
        assert "Signed-off-by" in violations[0]

    def test_human_only_signoff_fails(self) -> None:
        # A sign-off exists but names no agent identity.
        violations = evaluate_commits([_commit(signoffs=["tyler@example.com"])])
        assert len(violations) == 1
        assert "Signed-off-by" in violations[0]

    def test_missing_model_fails(self) -> None:
        violations = evaluate_commits([_commit(model="")])
        assert len(violations) == 1
        assert "Model" in violations[0]

    def test_missing_both_reports_both(self) -> None:
        violations = evaluate_commits([_commit(signoffs=[], model="")])
        assert len(violations) == 1
        assert "Signed-off-by" in violations[0] and "Model" in violations[0]

    def test_sharing_role_signoff_differs_from_author_is_allowed(self) -> None:
        # Mismatch is PM-judged, not CI-failed (legitimate after rewrites);
        # CI only requires that SOME agent identity signed off.
        commit = _commit(
            email="test-design@agents.rfc", signoffs=["design@agents.rfc"]
        )
        assert evaluate_commits([commit]) == []
