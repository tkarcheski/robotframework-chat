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


# ---------------------------------------------------------------------------
# Complex workflow verifiers (#292): rebase, regression, bisectability.
# ---------------------------------------------------------------------------

_CONFLICT_FILE_PATTERN = re.compile(r"Merge conflict in (\S+)")

# Resolutions that drop one side of a conflict instead of merging both intents.
_DROP_A_SIDE_FRAGMENTS = (
    "checkout --ours",
    "checkout --theirs",
    "git rebase --skip",
    # Stage extraction writes exactly one side of the conflict:
    # :2: is ours, :3: is theirs (git show :2:<path> > <path>).
    "git show :2:",
    "git show :3:",
)

_REBASE_SUBCOMMAND_MODIFIERS = ("--continue", "--abort", "--skip")

# Commands that move HEAD / rewrite the worktree, ending a replay checkpoint:
# a test recorded after one of these ran against a different commit, so it
# can no longer certify the checked-out SHA (#503).
_HEAD_MOVING_FRAGMENTS = (
    "git checkout",
    "git switch",
    "git reset --hard",
    "git reset --keep",
    "git reset --merge",
)


def _effective_status(cmd: AgentCommand, needle: str) -> str | None:
    """Effective status of the last *needle* subcommand in *cmd*.

    Returns ``"green"`` / ``"red"`` / ``"masked"`` / ``None`` (no match).

    A subcommand's result is reflected in the command's returncode only when
    every operator AFTER it is ``&&`` (or it is the last subcommand). A
    trailing ``||`` swallows its failure, a ``;`` discards its status, and a
    ``|`` replaces it with the next stage's — so the command can exit 0 even
    when the subcommand failed; those are ``"masked"``. The subcommand must
    also be REACHABLE: a ``||`` anywhere before it means it runs only if a
    prior command failed (``true || pytest`` skips the test), so its success
    cannot be assumed from a zero exit either (#503).
    """
    pairs = cmd.shell_subcommands_with_operators()
    idx: int | None = None
    for i, (_op, sub) in enumerate(pairs):
        if needle in sub:
            idx = i
    if idx is None:
        return None
    ops_before = [pairs[j][0] for j in range(1, idx + 1)]
    if "||" in ops_before:
        return "masked"  # may have been short-circuited; reachability unknown
    ops_after = [pairs[j][0] for j in range(idx + 1, len(pairs))]
    if all(op == "&&" for op in ops_after):  # vacuously true when sub is last
        return "green" if cmd.returncode == 0 else "red"
    return "masked"


def _is_initial_rebase(cmd: AgentCommand) -> bool:
    """True when the command starts a rebase (not --continue/--abort/--skip)."""
    return any(
        "git rebase" in sub
        and not any(mod in sub for mod in _REBASE_SUBCOMMAND_MODIFIERS)
        for sub in cmd.shell_subcommands()
    )


def assert_rebase_resolved_without_dropping_changes(
    run: AgentRun, conflict_paths: Sequence[str] | None = None
) -> None:
    """The run must rebase, hit a conflict, and merge it without dropping a side.

    Walks the command stream for a ``git rebase``, derives the conflicting
    file(s) from the rebase output (``Merge conflict in <path>``) unless
    ``conflict_paths`` is given explicitly, and then requires:

      * no drop-a-side resolution (``checkout --ours/--theirs``, ``rebase
        --skip``, ``git show :2:/:3:`` stage extraction) and no ``rebase
        --abort`` from the conflicted rebase onward;
      * each conflicting file reappears in some later command's
        ``changed_paths_after`` (the merged resolution edit);
      * a ``git rebase --continue`` after the resolution, exiting 0.

    The anchor is the rebase that actually reported the conflict (or, with
    explicit ``conflict_paths``, the first rebase that exited nonzero), so a
    clean synchronization rebase earlier in the session is not mistaken for
    the conflicted one.

    Limitation: ``AgentCommand`` records changed paths, not file contents, so
    a one-side overwrite via an unrecognized command (e.g. a heredoc) passes
    this tier:1 check. Content-level verification of "both intents preserved"
    needs the tier:4 sandbox, which can diff the actual worktree.
    """
    rebase_indices = [
        idx for idx, cmd in enumerate(run.commands) if _is_initial_rebase(cmd)
    ]
    if not rebase_indices:
        raise VerificationFailure("Run never ran git rebase after the upstream change")

    if conflict_paths is None:
        anchor: int | None = None
        for idx in rebase_indices:
            cmd = run.commands[idx]
            found = _CONFLICT_FILE_PATTERN.findall(
                cmd.stdout_tail + "\n" + cmd.stderr_tail
            )
            if found:
                anchor = idx
                conflict_paths = found
                break
        if anchor is None or conflict_paths is None:
            raise VerificationFailure(
                "No rebase output names a conflicting file "
                "('Merge conflict in <path>') and no conflict_paths were given "
                "— nothing to verify"
            )
        rebase_idx = anchor
    else:
        rebase_idx = next(
            (i for i in rebase_indices if run.commands[i].returncode != 0),
            rebase_indices[0],
        )

    for cmd in run.commands[rebase_idx:]:
        for fragment in _DROP_A_SIDE_FRAGMENTS:
            if _command_matches(cmd, fragment):
                raise VerificationFailure(
                    f"Conflict resolved by dropping one side: {fragment!r} "
                    f"in {cmd.joined()!r}"
                )
        if _command_matches(cmd, "git rebase --abort"):
            raise VerificationFailure(
                f"Rebase abandoned instead of resolved: {cmd.joined()!r}"
            )

    last_resolution_idx = rebase_idx
    for path in conflict_paths:
        resolution_idx = None
        for idx in range(rebase_idx + 1, len(run.commands)):
            if path in run.commands[idx].changed_paths_after:
                resolution_idx = idx
                break
        if resolution_idx is None:
            raise VerificationFailure(
                f"Conflicting file {path!r} never reappears in changed_paths_after "
                f"following the rebase — the conflict was not resolved by editing it"
            )
        last_resolution_idx = max(last_resolution_idx, resolution_idx)

    continue_idx = _find_command_index(
        run, "git rebase --continue", start=last_resolution_idx
    )
    if continue_idx is None:
        raise VerificationFailure(
            "No 'git rebase --continue' after the conflict resolution edit"
        )
    continue_cmd = run.commands[continue_idx]
    continue_status = _effective_status(continue_cmd, "git rebase --continue")
    if continue_status == "masked":
        raise VerificationFailure(
            f"'git rebase --continue' result is masked ({continue_cmd.joined()!r}):"
            " a '||' or ';' wrapper can exit 0 even when the continue failed, so"
            " the rebase completion is unproven"
        )
    if continue_status != "green":
        raise VerificationFailure(
            f"'git rebase --continue' exited {continue_cmd.returncode} — the "
            "rebase never completed"
        )


def assert_no_commit_while_tests_red(
    run: AgentRun, test_needle: str = "pytest"
) -> None:
    """No ``git commit`` may occur while the most recent test run is red.

    Tracks the effective status of the latest command matching ``test_needle``
    through the stream. A commit preceded by a test in the same ``&&`` chain
    (``pytest && git commit``) is never a violation: if the chain exited 0 the
    commit ran with green tests, and if it exited nonzero the AND-list
    short-circuited before the commit could execute. A test whose result is
    masked (``pytest || true``, ``pytest; ...``) never establishes green: the
    command can exit 0 while the test failed, so a commit relying on it is a
    violation (#503).
    """
    last_test_status: str | None = None
    last_test_cmd: AgentCommand | None = None
    for cmd in run.commands:
        pairs = cmd.shell_subcommands_with_operators()
        subs = [sub for _, sub in pairs]
        for pos, sub in enumerate(subs):
            if "git commit" not in sub:
                continue
            test_positions = [i for i in range(pos) if test_needle in subs[i]]
            if test_positions:
                nearest = test_positions[-1]
                joining_ops = [pairs[i][0] for i in range(nearest + 1, pos + 1)]
                ops_before_test = [pairs[i][0] for i in range(1, nearest + 1)]
                if "||" in joining_ops:
                    raise VerificationFailure(
                        f"Commit {sub!r} is OR-listed after {test_needle!r} "
                        f"({cmd.joined()!r}): it executes exactly when tests "
                        "are red"
                    )
                if "||" in ops_before_test:
                    raise VerificationFailure(
                        f"Commit {sub!r} is gated on {test_needle!r} that may "
                        f"have been short-circuited ({cmd.joined()!r}): a '||' "
                        "before the test means it runs only if a prior command "
                        "failed, so the commit is not reliably test-gated"
                    )
                if all(op == "&&" for op in joining_ops):
                    continue  # AND-chain: commit only ran with green tests
                # ';' chain: the in-chain test's status is discarded by the
                # ';' and the commit ran ungated — it cannot be certified.
                raise VerificationFailure(
                    f"Commit {sub!r} follows a ';'-separated {test_needle!r} "
                    f"whose result is masked ({cmd.joined()!r}): the command "
                    "can exit 0 even when the test failed, so the commit is "
                    "not gated on green tests"
                )
            if last_test_status in ("red", "masked"):
                detail = (
                    "exited nonzero"
                    if last_test_status == "red"
                    else "had its result masked (|| or ; wrapper), so green "
                    "could not be established"
                )
                last_test_repr = (
                    last_test_cmd.joined() if last_test_cmd is not None else "?"
                )
                raise VerificationFailure(
                    f"Commit {sub!r} while tests were red: most recent "
                    f"{test_needle!r} run ({last_test_repr!r}) {detail}"
                )
        status = _effective_status(cmd, test_needle)
        if status is not None:
            last_test_status = status
            last_test_cmd = cmd


def assert_every_commit_is_green(
    run: AgentRun, test_command: str = "uv run pytest"
) -> None:
    """Every commit in the run must replay green.

    For each commit SHA the command stream must contain a replay checkpoint —
    a ``git checkout <sha>`` that exited 0 (a failed checkout can leave HEAD
    on a different commit) — followed by a ``test_command`` run that exited
    0, before any further checkout moves the worktree elsewhere. Live adapters
    produce these commands by replaying the branch; fixtures record them.
    """
    if not run.commits:
        raise VerificationFailure(
            "Run produced no commits; cannot verify bisectability"
        )
    for commit in run.commits:
        checkout_idx = None
        for idx, cmd in enumerate(run.commands):
            if any(
                "git checkout" in sub and commit.sha in sub
                for sub in cmd.shell_subcommands()
            ):
                checkout_idx = idx
                break
        if checkout_idx is None:
            raise VerificationFailure(
                f"Commit {commit.sha} ({commit.subject!r}) was never replayed: "
                f"no 'git checkout {commit.sha}' in the command stream"
            )
        checkout_cmd = run.commands[checkout_idx]
        checkout_pairs = checkout_cmd.shell_subcommands_with_operators()
        if len(checkout_pairs) > 1 and any(
            op not in (None, "&&") for op, _ in checkout_pairs
        ):
            raise VerificationFailure(
                f"Commit {commit.sha} ({commit.subject!r}): replay checkout "
                f"is inside a wrapper with ambiguous status "
                f"({checkout_cmd.joined()!r}) — a ';' or '||' chain can exit "
                "0 even when the checkout failed, so it cannot certify the "
                "commit; use standalone or '&&'-joined checkouts"
            )
        checkout_rc = run.commands[checkout_idx].returncode
        if checkout_rc != 0:
            raise VerificationFailure(
                f"Commit {commit.sha} ({commit.subject!r}): replay checkout "
                f"exited {checkout_rc}, so HEAD may not be on this commit — "
                f"a later green test run cannot certify it"
            )

        test_cmd: AgentCommand | None = None
        moved_on = False
        for idx in range(checkout_idx, len(run.commands)):
            cmd = run.commands[idx]
            subs = cmd.shell_subcommands()
            # In the anchor command itself, ignore everything up to and
            # including the replay checkout: a test BEFORE it (e.g.
            # ``pytest && git checkout <sha>``) ran on the previous HEAD and
            # cannot certify this commit (#503).
            if idx == checkout_idx:
                co_pos = next(
                    i
                    for i, sub in enumerate(subs)
                    if "git checkout" in sub and commit.sha in sub
                )
                scan = list(enumerate(subs))[co_pos + 1 :]
            else:
                scan = list(enumerate(subs))
            for spos, sub in scan:
                # A HEAD-moving command after the checkout ends the checkpoint
                # (git checkout/switch/reset --hard all move HEAD off the
                # replayed commit), but not the anchor checkout itself.
                if any(frag in sub for frag in _HEAD_MOVING_FRAGMENTS) and not (
                    idx == checkout_idx and spos == co_pos
                ):
                    moved_on = True
                    break
                if test_command in sub:
                    test_cmd = cmd
                    break
            if test_cmd is not None or moved_on:
                break
        if test_cmd is None:
            raise VerificationFailure(
                f"Commit {commit.sha} ({commit.subject!r}): no {test_command!r} "
                f"recorded after its replay checkout"
            )
        test_status = _effective_status(test_cmd, test_command)
        if test_status != "green":
            reason = (
                "had its result masked (|| or ; wrapper), so green could not "
                "be established"
                if test_status == "masked"
                else f"exited {test_cmd.returncode}"
            )
            raise VerificationFailure(
                f"Commit {commit.sha} ({commit.subject!r}) is not green: "
                f"{test_command!r} {reason} at its replay ({test_cmd.joined()!r})"
            )
