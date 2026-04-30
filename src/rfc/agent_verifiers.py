"""Deterministic verifiers over :class:`AgentRun` artifacts.

Each verifier raises :class:`VerificationFailure` on failure with a clear
human-readable reason. All checks in this module are Tier 1: pure Python logic
over a normalized artifact, no LLM calls, no network, no I/O.

Verifiers treat ``bash -lc "A && B"`` shell-wrapper invocations as if the inner
subcommands were run directly, so agents that bundle commands are not penalized.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from rfc.agent_contract import AgentContract
from rfc.agent_run import AgentCommand, AgentRun

_PLACEHOLDER_PATTERN = re.compile(
    r"^\s*(?:tbd|todo|see above|placeholder|x+)\s*$", re.IGNORECASE
)


class VerificationFailure(AssertionError):
    """Raised when an :class:`AgentRun` fails a deterministic verifier."""


def _command_matches(cmd: AgentCommand, needle: str) -> bool:
    for sub in cmd.shell_subcommands():
        if needle in sub:
            return True
    return False


def _find_command_index(run: AgentRun, needle: str, start: int = 0) -> int | None:
    for idx in range(start, len(run.commands)):
        if _command_matches(run.commands[idx], needle):
            return idx
    return None


def _flatten_subcommands(run: AgentRun) -> list[str]:
    """Return all subcommands across every command, in order."""
    subs: list[str] = []
    for cmd in run.commands:
        subs.extend(cmd.shell_subcommands())
    return subs


def assert_branch_matches_contract(run: AgentRun, contract: AgentContract) -> None:
    """Run's branch name and base branch must match the contract."""
    if run.base_branch != contract.base_branch:
        raise VerificationFailure(
            f"Wrong base branch: expected {contract.base_branch!r}, got {run.base_branch!r}"
        )
    if not contract.branch_matches(run.branch_name):
        raise VerificationFailure(
            f"Branch name {run.branch_name!r} does not match "
            f"contract regex {contract.branch_regex!r}"
        )


def assert_commands_appear_in_order(
    run: AgentRun, ordered_needles: Sequence[str]
) -> None:
    """Each needle must appear as a subcommand, in the given order.

    Subcommands from ``bash -lc "A && B"`` wrappers are flattened, so needles
    that ran as part of the same wrapped invocation still satisfy ordering.

    Raises:
        ValueError: If ``ordered_needles`` is empty. An empty needle list
            would vacuously pass even against an empty agent run, hiding
            misconfigured tests.
    """
    if not ordered_needles:
        raise ValueError(
            "ordered_needles must not be empty: "
            "an empty expectation would vacuously pass any run"
        )
    subs = _flatten_subcommands(run)
    cursor = 0
    for needle in ordered_needles:
        idx: int | None = None
        for i in range(cursor, len(subs)):
            if needle in subs[i]:
                idx = i
                break
        if idx is None:
            if any(needle in s for s in subs):
                raise VerificationFailure(f"Command {needle!r} ran in the wrong order")
            raise VerificationFailure(f"Command {needle!r} missing from run")
        cursor = idx + 1


def assert_no_source_changes_before_command(
    run: AgentRun, needle: str, *, under: str
) -> None:
    """No file under ``under`` may be modified before the first occurrence of ``needle``."""
    idx = _find_command_index(run, needle)
    if idx is None:
        raise VerificationFailure(f"Run never ran command {needle!r}")
    for cmd in run.commands[:idx]:
        for path in cmd.changed_paths_after:
            if path.startswith(under):
                raise VerificationFailure(
                    f"Path {path!r} under {under!r} was modified before {needle!r}"
                )


def assert_clarifying_question_count_in_range(
    run: AgentRun,
    contract: AgentContract,
    *,
    min_override: int | None = None,
    max_override: int | None = None,
) -> None:
    """Question count must be within the (possibly overridden) contract bounds."""
    lo = contract.min_clarifying_questions if min_override is None else min_override
    hi = contract.max_clarifying_questions if max_override is None else max_override
    n = len(run.questions)
    if n < lo:
        raise VerificationFailure(
            f"Agent asked {n} clarifying questions; contract requires at least {lo}"
        )
    if n > hi:
        raise VerificationFailure(
            f"Agent asked {n} clarifying questions; contract allows at most {hi}"
        )


def assert_questions_are_multiple_choice(run: AgentRun) -> None:
    """Every clarifying question must carry two or more options."""
    for q in run.questions:
        if not q.is_multiple_choice:
            raise VerificationFailure(
                f"Question {q.text!r} is not multiple choice (options={q.options!r})"
            )


def assert_all_commits_match_convention(run: AgentRun, contract: AgentContract) -> None:
    """Every commit subject must match the contract's conventional-commit regex."""
    for commit in run.commits:
        if not contract.commit_subject_matches(commit.subject):
            raise VerificationFailure(
                f"Non-conventional commit subject: {commit.subject!r}"
            )


def assert_first_change_under(run: AgentRun, prefix: str) -> None:
    """The earliest changed path in the run must start with ``prefix``."""
    for cmd in run.commands:
        for path in cmd.changed_paths_after:
            if path.startswith(prefix):
                return
            raise VerificationFailure(
                f"First changed path {path!r} is not under {prefix!r}"
            )
    raise VerificationFailure(
        f"Run has no changed paths; expected first change under {prefix!r}"
    )


def _extract_section(body: str, heading: str) -> str | None:
    pattern = re.compile(
        rf"^\s*#{{1,6}}\s*{re.escape(heading)}\s*$(.*?)(?=^\s*#{{1,6}}\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(body)
    return m.group(1).strip() if m else None


def assert_pr_body_includes_sections(run: AgentRun, sections: Iterable[str]) -> None:
    """The run's PR body must contain each heading with non-placeholder content."""
    if run.pr is None:
        raise VerificationFailure("Run produced no PR; cannot verify PR body sections")
    body = run.pr.body
    for heading in sections:
        content = _extract_section(body, heading)
        if content is None:
            raise VerificationFailure(f"PR body missing section: {heading!r}")
        stripped = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL).strip()
        if not stripped:
            raise VerificationFailure(f"PR body section {heading!r} is empty")
        if _PLACEHOLDER_PATTERN.match(stripped):
            raise VerificationFailure(
                f"PR body section {heading!r} is a placeholder: {stripped!r}"
            )


def assert_no_commands_matching(run: AgentRun, forbidden: Iterable[str]) -> None:
    """No command (or shell subcommand) may match any forbidden needle."""
    for needle in forbidden:
        for cmd in run.commands:
            if _command_matches(cmd, needle):
                raise VerificationFailure(
                    f"Run contains forbidden command fragment: {needle!r} in {cmd.joined()!r}"
                )
