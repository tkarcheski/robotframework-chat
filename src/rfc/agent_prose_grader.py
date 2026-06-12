"""Tier:3 prose graders for the agentic-coding suite (#289).

LLM-as-judge evaluation of the qualitative dimensions of an
:class:`~rfc.agent_run.AgentRun` that deterministic verifiers cannot
check: whether clarifying questions are grounded in the repo, whether
the PR body actually explains how to review, and whether commit
subjects truthfully describe their file changes.

All grading goes through :class:`~rfc.multi_grader.MultiGrader`
(3+ judge consensus) per ai/testing.md's bias-mitigation guidance.
"""

from __future__ import annotations

from .agent_run import AgentRun
from .multi_grader import MultiGrader, MultiGradeResult

_GROUNDING_RUBRIC = (
    "Score 1.0 when every question references a concrete file, symbol, "
    "function, or other artifact that plausibly exists in the repository "
    "the task describes. Score 0.0 when questions are generic and could "
    "be asked about any repository. Use partial credit for a mix."
)

_PR_BODY_RUBRIC = (
    "Score 1.0 when the body has a 'How to review' section that names a "
    "concrete starting file and sequences the key changes by importance. "
    "Score 0.0 when the body gives a reviewer no concrete entry point. "
    "Use partial credit when only one of the two criteria is met."
)

_COMMIT_RUBRIC = (
    "Score 1.0 when every commit subject truthfully describes only the "
    "files listed for it (no claims about files it does not touch, no "
    "files left undescribed). Score 0.0 when subjects misrepresent the "
    "changes. Use partial credit when most commits are cohesive."
)


class AgentProseGrader:
    """Grade the prose artifacts of an AgentRun via multi-judge consensus."""

    def __init__(self, grader: MultiGrader) -> None:
        self._grader = grader

    def grade_question_grounding(self, run: AgentRun) -> MultiGradeResult:
        """Are the clarifying questions grounded in concrete repo artifacts?"""
        if not run.questions:
            raise ValueError(
                f"run {run.scenario_id!r} has no clarifying questions to grade"
            )
        questions_text = "\n".join(
            f"- {q.text}" + "".join(f"\n  {opt}" for opt in q.options)
            for q in run.questions
        )
        return self._grader.grade(
            question=(
                "An AI coding agent was given this task:\n"
                f"{run.task}\n\n"
                "Before acting it asked the clarifying questions below. "
                "Are they grounded in concrete repository artifacts?"
            ),
            expected="Each question references a concrete file, symbol, or function.",
            actual=questions_text,
            rubric=_GROUNDING_RUBRIC,
        )

    def grade_pr_body(self, run: AgentRun) -> MultiGradeResult:
        """Does the PR body explain how to review the change?"""
        if run.pr is None or not run.pr.body.strip():
            raise ValueError(f"run {run.scenario_id!r} has no PR body to grade")
        return self._grader.grade(
            question=(
                "An AI coding agent prepared a pull request for this task:\n"
                f"{run.task}\n\n"
                "Does the PR body below explain how to review the change?"
            ),
            expected=(
                "A 'How to review' section naming a concrete starting file "
                "and sequencing key changes by importance."
            ),
            actual=f"Title: {run.pr.title}\n\n{run.pr.body}",
            rubric=_PR_BODY_RUBRIC,
        )

    def grade_commit_cohesion(self, run: AgentRun) -> MultiGradeResult:
        """Does each commit subject truthfully describe its file changes?"""
        if not run.commits:
            raise ValueError(f"run {run.scenario_id!r} has no commits to grade")
        commits_text = "\n".join(
            f"- {c.subject}\n  files: {', '.join(c.files_changed) or '(none listed)'}"
            for c in run.commits
        )
        return self._grader.grade(
            question=(
                "An AI coding agent produced the commits below for this task:\n"
                f"{run.task}\n\n"
                "Does each commit subject truthfully describe only the files "
                "listed for it?"
            ),
            expected="Every subject matches its files_changed list.",
            actual=commits_text,
            rubric=_COMMIT_RUBRIC,
        )
