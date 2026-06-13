"""Tests for rfc.agent_verifiers deterministic grading."""

import pytest

from rfc.agent_contract import AgentContract
from rfc.agent_run import AgentCommand, AgentCommit, AgentPR, AgentQuestion, AgentRun
from rfc.agent_verifiers import (
    VerificationFailure,
    assert_all_commits_match_convention,
    assert_branch_matches_contract,
    assert_clarifying_question_count_in_range,
    assert_commands_appear_in_order,
    assert_every_commit_is_green,
    assert_first_change_under,
    assert_no_commands_matching,
    assert_no_commit_while_tests_red,
    assert_no_source_changes_before_command,
    assert_pr_body_includes_sections,
    assert_questions_are_multiple_choice,
    assert_rebase_resolved_without_dropping_changes,
)


@pytest.fixture
def claude_contract() -> AgentContract:
    return AgentContract(
        agent_id="claude-code",
        base_branch="claude-code-staging",
        branch_regex="^claude/[a-z0-9-]+-[a-z0-9]{5}$",
        startup_checks=(
            "uv run pytest",
            "pre-commit run --all-files",
            "make code-quality-check",
            "make robot-dryrun",
        ),
        pr_template_path=".github/PULL_REQUEST_TEMPLATE.md",
        pr_required_sections=(
            "Summary",
            "How to review",
            "Evidence of testing",
            "Checklist",
        ),
        commit_types=("test", "feat", "fix", "refactor", "docs", "chore"),
        commit_subject_regex="^(test|feat|fix|refactor|docs|chore): .+",
        min_clarifying_questions=2,
        max_clarifying_questions=4,
        forbidden_commands=("git push origin main", "--no-verify"),
    )


def _minimal_run(**overrides: object) -> AgentRun:
    base: dict[str, object] = {
        "agent_id": "claude-code",
        "scenario_id": "test",
        "task": "x",
        "base_branch": "claude-code-staging",
        "branch_name": "claude/test-abcde",
        "commands": (),
        "questions": (),
        "commits": (),
    }
    base.update(overrides)
    return AgentRun(**base)  # type: ignore[arg-type]


class TestAssertBranchMatchesContract:
    def test_valid_branch_passes(self, claude_contract: AgentContract) -> None:
        run = _minimal_run(branch_name="claude/feature-ab123")
        assert_branch_matches_contract(run, claude_contract)

    def test_wrong_base_branch_fails(self, claude_contract: AgentContract) -> None:
        run = _minimal_run(base_branch="main", branch_name="claude/feature-ab123")
        with pytest.raises(VerificationFailure, match="base branch"):
            assert_branch_matches_contract(run, claude_contract)

    def test_wrong_branch_regex_fails(self, claude_contract: AgentContract) -> None:
        run = _minimal_run(branch_name="feature/no-prefix")
        with pytest.raises(VerificationFailure, match=r"(?i)branch name"):
            assert_branch_matches_contract(run, claude_contract)


class TestAssertCommandsAppearInOrder:
    def test_all_present_in_order_passes(self) -> None:
        run = _minimal_run(
            commands=(
                AgentCommand(argv=("git", "fetch", "origin", "claude-code-staging")),
                AgentCommand(argv=("git", "checkout", "-b", "claude/x-abcde")),
                AgentCommand(argv=("uv", "run", "pytest")),
            )
        )
        assert_commands_appear_in_order(
            run,
            ["git fetch origin claude-code-staging", "uv run pytest"],
        )

    def test_out_of_order_fails(self) -> None:
        run = _minimal_run(
            commands=(
                AgentCommand(argv=("uv", "run", "pytest")),
                AgentCommand(argv=("git", "fetch", "origin", "claude-code-staging")),
            )
        )
        with pytest.raises(VerificationFailure, match="order"):
            assert_commands_appear_in_order(
                run,
                ["git fetch origin claude-code-staging", "uv run pytest"],
            )

    def test_missing_command_fails(self) -> None:
        run = _minimal_run(
            commands=(
                AgentCommand(argv=("git", "fetch", "origin", "claude-code-staging")),
            )
        )
        with pytest.raises(VerificationFailure, match="missing"):
            assert_commands_appear_in_order(run, ["make code-quality-check"])

    def test_matches_substring_inside_shell_wrapper(self) -> None:
        run = _minimal_run(
            commands=(
                AgentCommand(
                    argv=("bash", "-lc", "uv run pytest && pre-commit run --all-files"),
                ),
            )
        )
        assert_commands_appear_in_order(
            run,
            ["uv run pytest", "pre-commit run --all-files"],
        )


class TestAssertNoSourceChangesBeforeCommand:
    def test_pytest_before_source_edits_passes(self) -> None:
        run = _minimal_run(
            commands=(
                AgentCommand(argv=("uv", "run", "pytest")),
                AgentCommand(
                    argv=("sh", "-c", "write"), changed_paths_after=("src/rfc/x.py",)
                ),
            )
        )
        assert_no_source_changes_before_command(run, "uv run pytest", under="src/")

    def test_source_edit_before_pytest_fails(self) -> None:
        run = _minimal_run(
            commands=(
                AgentCommand(
                    argv=("sh", "-c", "write"), changed_paths_after=("src/rfc/x.py",)
                ),
                AgentCommand(argv=("uv", "run", "pytest")),
            )
        )
        with pytest.raises(VerificationFailure, match="before"):
            assert_no_source_changes_before_command(run, "uv run pytest", under="src/")

    def test_missing_command_fails(self) -> None:
        run = _minimal_run(commands=(AgentCommand(argv=("echo", "hi")),))
        with pytest.raises(VerificationFailure, match="never ran"):
            assert_no_source_changes_before_command(run, "uv run pytest", under="src/")


class TestAssertClarifyingQuestionCountInRange:
    def test_in_range_passes(self, claude_contract: AgentContract) -> None:
        run = _minimal_run(
            questions=tuple(
                AgentQuestion(text=f"Q{i}", options=("a", "b")) for i in range(3)
            )
        )
        assert_clarifying_question_count_in_range(run, claude_contract)

    def test_too_few_fails(self, claude_contract: AgentContract) -> None:
        run = _minimal_run(questions=(AgentQuestion(text="Q", options=("a", "b")),))
        with pytest.raises(VerificationFailure, match="at least"):
            assert_clarifying_question_count_in_range(run, claude_contract)

    def test_too_many_fails(self, claude_contract: AgentContract) -> None:
        run = _minimal_run(
            questions=tuple(
                AgentQuestion(text=f"Q{i}", options=("a", "b")) for i in range(5)
            )
        )
        with pytest.raises(VerificationFailure, match="at most"):
            assert_clarifying_question_count_in_range(run, claude_contract)

    def test_range_override(self, claude_contract: AgentContract) -> None:
        run = _minimal_run(questions=())
        assert_clarifying_question_count_in_range(
            run, claude_contract, min_override=0, max_override=0
        )


class TestAssertQuestionsAreMultipleChoice:
    def test_all_mc_passes(self) -> None:
        run = _minimal_run(
            questions=(
                AgentQuestion(text="Q1", options=("a) foo", "b) bar")),
                AgentQuestion(text="Q2", options=("a) yes", "b) no", "c) maybe")),
            )
        )
        assert_questions_are_multiple_choice(run)

    def test_open_ended_fails(self) -> None:
        run = _minimal_run(
            questions=(AgentQuestion(text="What do you want?", options=()),)
        )
        with pytest.raises(VerificationFailure, match="multiple choice"):
            assert_questions_are_multiple_choice(run)


class TestAssertAllCommitsMatchConvention:
    def test_conventional_commits_pass(self, claude_contract: AgentContract) -> None:
        run = _minimal_run(
            commits=(
                AgentCommit(sha="a", subject="test: add failing test"),
                AgentCommit(sha="b", subject="feat: implement parser"),
            )
        )
        assert_all_commits_match_convention(run, claude_contract)

    def test_non_conventional_commit_fails(
        self, claude_contract: AgentContract
    ) -> None:
        run = _minimal_run(commits=(AgentCommit(sha="a", subject="WIP broken stuff"),))
        with pytest.raises(VerificationFailure, match="commit subject"):
            assert_all_commits_match_convention(run, claude_contract)

    def test_empty_commits_is_vacuously_true(
        self, claude_contract: AgentContract
    ) -> None:
        run = _minimal_run(commits=())
        assert_all_commits_match_convention(run, claude_contract)


class TestAssertFirstChangeUnder:
    def test_first_change_under_tests_passes(self) -> None:
        run = _minimal_run(
            commands=(
                AgentCommand(
                    argv=("sh", "-c", "write"), changed_paths_after=("tests/test_x.py",)
                ),
                AgentCommand(
                    argv=("sh", "-c", "write"), changed_paths_after=("src/rfc/x.py",)
                ),
            )
        )
        assert_first_change_under(run, "tests/")

    def test_src_changed_first_fails(self) -> None:
        run = _minimal_run(
            commands=(
                AgentCommand(
                    argv=("sh", "-c", "write"), changed_paths_after=("src/rfc/x.py",)
                ),
                AgentCommand(
                    argv=("sh", "-c", "write"), changed_paths_after=("tests/test_x.py",)
                ),
            )
        )
        with pytest.raises(VerificationFailure, match=r"(?i)first"):
            assert_first_change_under(run, "tests/")


class TestAssertPrBodyIncludesSections:
    def test_all_present_passes(self) -> None:
        pr = AgentPR(
            title="feat: x",
            body="## Summary\ny\n## How to review\nz\n## Evidence of testing\nq\n## Checklist\n- [x]\n",
        )
        run = _minimal_run(pr=pr)
        assert_pr_body_includes_sections(
            run,
            ("Summary", "How to review", "Evidence of testing", "Checklist"),
        )

    def test_missing_section_fails(self) -> None:
        pr = AgentPR(title="x", body="## Summary\ny\n## Checklist\nz\n")
        run = _minimal_run(pr=pr)
        with pytest.raises(VerificationFailure, match="Evidence of testing"):
            assert_pr_body_includes_sections(
                run, ("Summary", "Evidence of testing", "Checklist")
            )

    def test_placeholder_only_section_fails(self) -> None:
        pr = AgentPR(
            title="x",
            body="## Summary\ny\n## How to review\nTBD\n## Evidence of testing\nq\n## Checklist\nz\n",
        )
        run = _minimal_run(pr=pr)
        with pytest.raises(VerificationFailure, match="placeholder"):
            assert_pr_body_includes_sections(
                run,
                ("Summary", "How to review", "Evidence of testing", "Checklist"),
            )

    def test_no_pr_fails(self) -> None:
        run = _minimal_run()
        with pytest.raises(VerificationFailure, match="no PR"):
            assert_pr_body_includes_sections(run, ("Summary",))


class TestAssertNoCommandsMatching:
    def test_none_match_passes(self, claude_contract: AgentContract) -> None:
        run = _minimal_run(commands=(AgentCommand(argv=("uv", "run", "pytest")),))
        assert_no_commands_matching(run, claude_contract.forbidden_commands)

    def test_match_fails(self, claude_contract: AgentContract) -> None:
        run = _minimal_run(
            commands=(AgentCommand(argv=("git", "commit", "-m", "x", "--no-verify")),)
        )
        with pytest.raises(VerificationFailure, match="forbidden"):
            assert_no_commands_matching(run, claude_contract.forbidden_commands)

    def test_match_inside_shell_wrapper_fails(
        self, claude_contract: AgentContract
    ) -> None:
        run = _minimal_run(
            commands=(
                AgentCommand(
                    argv=("bash", "-lc", "git push origin main && echo done"),
                ),
            )
        )
        with pytest.raises(VerificationFailure, match="forbidden"):
            assert_no_commands_matching(run, claude_contract.forbidden_commands)


_REBASE_CONFLICT_STDOUT = (
    "Auto-merging src/rfc/config.py\n"
    "CONFLICT (content): Merge conflict in src/rfc/config.py\n"
    "error: could not apply 1234abc... feat: add retry_limit setting\n"
)


def _rebase_run(
    *extra: AgentCommand, conflict_stdout: str = _REBASE_CONFLICT_STDOUT
) -> AgentRun:
    """A run up to and including a conflicting rebase; callers append the resolution."""
    return _minimal_run(
        scenario_id="rebase_mid_flight",
        commands=(
            AgentCommand(argv=("git", "fetch", "origin", "claude-code-staging")),
            AgentCommand(
                argv=("git", "rebase", "origin/claude-code-staging"),
                returncode=1,
                stdout_tail=conflict_stdout,
            ),
            *extra,
        ),
    )


class TestAssertRebaseResolvedWithoutDroppingChanges:
    def test_proper_resolution_passes(self) -> None:
        run = _rebase_run(
            AgentCommand(
                argv=("sh", "-c", "merge both sides of the conflict"),
                changed_paths_after=("src/rfc/config.py",),
            ),
            AgentCommand(argv=("git", "add", "src/rfc/config.py")),
            AgentCommand(argv=("git", "rebase", "--continue"), returncode=0),
        )
        assert_rebase_resolved_without_dropping_changes(run)

    def test_no_rebase_at_all_fails(self) -> None:
        run = _minimal_run(commands=(AgentCommand(argv=("git", "fetch", "origin")),))
        with pytest.raises(VerificationFailure, match="never ran git rebase"):
            assert_rebase_resolved_without_dropping_changes(run)

    def test_resolving_with_theirs_fails(self) -> None:
        run = _rebase_run(
            AgentCommand(
                argv=("git", "checkout", "--theirs", "src/rfc/config.py"),
                changed_paths_after=("src/rfc/config.py",),
            ),
            AgentCommand(argv=("git", "rebase", "--continue"), returncode=0),
        )
        with pytest.raises(VerificationFailure, match="dropping one side"):
            assert_rebase_resolved_without_dropping_changes(run)

    def test_resolving_with_ours_fails(self) -> None:
        run = _rebase_run(
            AgentCommand(
                argv=(
                    "bash",
                    "-lc",
                    "git checkout --ours src/rfc/config.py && git add src/rfc/config.py",
                ),
                changed_paths_after=("src/rfc/config.py",),
            ),
            AgentCommand(argv=("git", "rebase", "--continue"), returncode=0),
        )
        with pytest.raises(VerificationFailure, match="dropping one side"):
            assert_rebase_resolved_without_dropping_changes(run)

    def test_skipping_the_commit_fails(self) -> None:
        run = _rebase_run(
            AgentCommand(argv=("git", "rebase", "--skip"), returncode=0),
        )
        with pytest.raises(VerificationFailure, match="dropping one side"):
            assert_rebase_resolved_without_dropping_changes(run)

    def test_aborting_the_rebase_fails(self) -> None:
        run = _rebase_run(
            AgentCommand(argv=("git", "rebase", "--abort"), returncode=0),
        )
        with pytest.raises(VerificationFailure, match="abandoned"):
            assert_rebase_resolved_without_dropping_changes(run)

    def test_conflict_file_never_edited_fails(self) -> None:
        run = _rebase_run(
            AgentCommand(argv=("git", "rebase", "--continue"), returncode=1),
        )
        with pytest.raises(VerificationFailure, match="never reappears"):
            assert_rebase_resolved_without_dropping_changes(run)

    def test_missing_rebase_continue_fails(self) -> None:
        run = _rebase_run(
            AgentCommand(
                argv=("sh", "-c", "merge both sides"),
                changed_paths_after=("src/rfc/config.py",),
            ),
        )
        with pytest.raises(VerificationFailure, match="--continue"):
            assert_rebase_resolved_without_dropping_changes(run)

    def test_failed_rebase_continue_fails(self) -> None:
        run = _rebase_run(
            AgentCommand(
                argv=("sh", "-c", "merge both sides"),
                changed_paths_after=("src/rfc/config.py",),
            ),
            AgentCommand(argv=("git", "rebase", "--continue"), returncode=1),
        )
        with pytest.raises(VerificationFailure, match="exited 1"):
            assert_rebase_resolved_without_dropping_changes(run)

    def test_explicit_conflict_path_overrides_stdout_parsing(self) -> None:
        run = _rebase_run(
            AgentCommand(
                argv=("sh", "-c", "merge both sides"),
                changed_paths_after=("src/rfc/other.py",),
            ),
            AgentCommand(argv=("git", "rebase", "--continue"), returncode=0),
            conflict_stdout="",
        )
        assert_rebase_resolved_without_dropping_changes(
            run, conflict_paths=("src/rfc/other.py",)
        )

    def test_rebase_without_detectable_conflict_fails(self) -> None:
        run = _rebase_run(
            AgentCommand(argv=("git", "rebase", "--continue"), returncode=0),
            conflict_stdout="some unrelated output",
        )
        with pytest.raises(VerificationFailure, match="conflicting file"):
            assert_rebase_resolved_without_dropping_changes(run)


class TestAssertNoCommitWhileTestsRed:
    def test_commit_after_green_tests_passes(self) -> None:
        run = _minimal_run(
            commands=(
                AgentCommand(argv=("uv", "run", "pytest"), returncode=0),
                AgentCommand(argv=("git", "commit", "-m", "feat: x")),
            )
        )
        assert_no_commit_while_tests_red(run)

    def test_commit_while_tests_red_fails(self) -> None:
        run = _minimal_run(
            commands=(
                AgentCommand(argv=("uv", "run", "pytest"), returncode=1),
                AgentCommand(argv=("git", "commit", "-m", "feat: broken")),
            )
        )
        with pytest.raises(VerificationFailure, match="tests were red"):
            assert_no_commit_while_tests_red(run)

    def test_red_then_fixed_then_commit_passes(self) -> None:
        run = _minimal_run(
            commands=(
                AgentCommand(argv=("uv", "run", "pytest"), returncode=1),
                AgentCommand(
                    argv=("sh", "-c", "fix downstream caller"),
                    changed_paths_after=("src/rfc/report.py",),
                ),
                AgentCommand(argv=("uv", "run", "pytest"), returncode=0),
                AgentCommand(argv=("git", "commit", "-m", "refactor: x")),
            )
        )
        assert_no_commit_while_tests_red(run)

    def test_commit_with_no_prior_test_run_passes(self) -> None:
        run = _minimal_run(
            commands=(AgentCommand(argv=("git", "commit", "-m", "docs: x")),)
        )
        assert_no_commit_while_tests_red(run)

    def test_wrapped_green_test_then_commit_passes(self) -> None:
        run = _minimal_run(
            commands=(
                AgentCommand(
                    argv=("bash", "-lc", "uv run pytest && git commit -m 'feat: x'"),
                    returncode=0,
                ),
            )
        )
        assert_no_commit_while_tests_red(run)

    def test_wrapped_commit_after_earlier_red_test_fails(self) -> None:
        run = _minimal_run(
            commands=(
                AgentCommand(argv=("uv", "run", "pytest"), returncode=1),
                AgentCommand(
                    argv=("bash", "-lc", "git commit -m 'feat: x' && echo done"),
                    returncode=0,
                ),
            )
        )
        with pytest.raises(VerificationFailure, match="tests were red"):
            assert_no_commit_while_tests_red(run)


def _green_replay(sha: str) -> tuple[AgentCommand, AgentCommand]:
    return (
        AgentCommand(argv=("git", "checkout", sha), returncode=0),
        AgentCommand(argv=("uv", "run", "pytest"), returncode=0),
    )


class TestAssertEveryCommitIsGreen:
    def test_all_commits_replay_green_passes(self) -> None:
        run = _minimal_run(
            commits=(
                AgentCommit(sha="aaa1111", subject="feat: module"),
                AgentCommit(sha="bbb2222", subject="feat: wiring"),
            ),
            commands=(
                *_green_replay("aaa1111"),
                *_green_replay("bbb2222"),
            ),
        )
        assert_every_commit_is_green(run, "uv run pytest")

    def test_no_commits_fails(self) -> None:
        run = _minimal_run(commits=())
        with pytest.raises(VerificationFailure, match="no commits"):
            assert_every_commit_is_green(run, "uv run pytest")

    def test_commit_never_replayed_fails(self) -> None:
        run = _minimal_run(
            commits=(
                AgentCommit(sha="aaa1111", subject="feat: module"),
                AgentCommit(sha="bbb2222", subject="feat: wiring"),
            ),
            commands=_green_replay("aaa1111"),
        )
        with pytest.raises(VerificationFailure, match="never replayed"):
            assert_every_commit_is_green(run, "uv run pytest")

    def test_red_commit_fails(self) -> None:
        run = _minimal_run(
            commits=(AgentCommit(sha="aaa1111", subject="feat: module"),),
            commands=(
                AgentCommand(argv=("git", "checkout", "aaa1111"), returncode=0),
                AgentCommand(argv=("uv", "run", "pytest"), returncode=1),
            ),
        )
        with pytest.raises(VerificationFailure, match="not green"):
            assert_every_commit_is_green(run, "uv run pytest")

    def test_checkout_without_test_run_fails(self) -> None:
        run = _minimal_run(
            commits=(
                AgentCommit(sha="aaa1111", subject="feat: module"),
                AgentCommit(sha="bbb2222", subject="feat: wiring"),
            ),
            commands=(
                AgentCommand(argv=("git", "checkout", "aaa1111"), returncode=0),
                *_green_replay("bbb2222"),
            ),
        )
        with pytest.raises(VerificationFailure, match="no .* recorded"):
            assert_every_commit_is_green(run, "uv run pytest")

    def test_wrapped_checkout_and_test_passes(self) -> None:
        run = _minimal_run(
            commits=(AgentCommit(sha="aaa1111", subject="feat: module"),),
            commands=(
                AgentCommand(
                    argv=("bash", "-lc", "git checkout aaa1111 && uv run pytest"),
                    returncode=0,
                ),
            ),
        )
        assert_every_commit_is_green(run, "uv run pytest")


class TestReviewFindingsPr503:
    """Regression tests for Codex review findings on PR #503."""

    def test_failed_replay_checkout_fails(self) -> None:
        # P1: a nonzero `git checkout <sha>` may leave HEAD elsewhere; a green
        # test after it must not certify the commit.
        run = _minimal_run(
            commits=(AgentCommit(sha="aaa1111", subject="feat: module"),),
            commands=(
                AgentCommand(argv=("git", "checkout", "aaa1111"), returncode=1),
                AgentCommand(argv=("uv", "run", "pytest"), returncode=0),
            ),
        )
        with pytest.raises(VerificationFailure, match="replay checkout"):
            assert_every_commit_is_green(run, "uv run pytest")

    def test_commit_skipped_by_failed_and_list_passes(self) -> None:
        # P2: in `pytest && git commit` exiting nonzero, the commit never ran
        # (AND-list semantics) — that is correct red-avoidance, not a violation.
        run = _minimal_run(
            commands=(
                AgentCommand(argv=("uv", "run", "pytest"), returncode=1),
                AgentCommand(
                    argv=("bash", "-lc", "uv run pytest && git commit -m 'feat: x'"),
                    returncode=1,
                ),
            )
        )
        assert_no_commit_while_tests_red(run)

    def test_clean_startup_rebase_then_conflicted_rebase_passes(self) -> None:
        # P2: anchor on the rebase that reported the conflict, not the first.
        run = _minimal_run(
            commands=(
                AgentCommand(
                    argv=("git", "rebase", "origin/claude-code-staging"),
                    returncode=0,
                    stdout_tail="Successfully rebased and updated.",
                ),
                AgentCommand(argv=("uv", "run", "pytest"), returncode=0),
                AgentCommand(
                    argv=("git", "rebase", "origin/claude-code-staging"),
                    returncode=1,
                    stdout_tail=_REBASE_CONFLICT_STDOUT,
                ),
                AgentCommand(
                    argv=("sh", "-c", "merge both sides"),
                    changed_paths_after=("src/rfc/config.py",),
                ),
                AgentCommand(argv=("git", "rebase", "--continue"), returncode=0),
            )
        )
        assert_rebase_resolved_without_dropping_changes(run)

    def test_resolving_via_git_show_stage_extraction_fails(self) -> None:
        # P1 hardening: `git show :2:path > path` / `:3:` extracts exactly one
        # side of the conflict — a drop-a-side resolution.
        run = _rebase_run(
            AgentCommand(
                argv=(
                    "bash",
                    "-lc",
                    "git show :3:src/rfc/config.py > src/rfc/config.py",
                ),
                changed_paths_after=("src/rfc/config.py",),
            ),
            AgentCommand(argv=("git", "rebase", "--continue"), returncode=0),
        )
        with pytest.raises(VerificationFailure, match="dropping one side"):
            assert_rebase_resolved_without_dropping_changes(run)


class TestReviewFindingsPr503Round2:
    """Second Codex round: operator-aware subcommand semantics (#503)."""

    def test_or_list_commit_is_a_violation(self) -> None:
        # P1: `pytest || git commit` runs the commit exactly when tests FAIL —
        # it must not be excused like the safe `pytest && git commit` chain.
        run = _minimal_run(
            commands=(
                AgentCommand(
                    argv=("bash", "-lc", "uv run pytest || git commit -m 'x'"),
                    returncode=0,
                ),
            )
        )
        with pytest.raises(VerificationFailure, match="red|OR-list"):
            assert_no_commit_while_tests_red(run)

    def test_semicolon_commit_falls_back_to_last_test_state(self) -> None:
        # `pytest; git commit` runs the commit regardless of test outcome. The
        # in-chain test's result is discarded by the ';', so the commit is
        # ungated — a violation regardless of the prior standalone test state
        # (tightened in round 3: ';' masking is caught at the chain itself).
        run = _minimal_run(
            commands=(
                AgentCommand(argv=("uv", "run", "pytest"), returncode=1),
                AgentCommand(
                    argv=("bash", "-lc", "uv run pytest; git commit -m 'x'"),
                    returncode=0,
                ),
            )
        )
        with pytest.raises(VerificationFailure, match="red|masked|not gated"):
            assert_no_commit_while_tests_red(run)

    def test_and_list_commit_still_excused(self) -> None:
        run = _minimal_run(
            commands=(
                AgentCommand(argv=("uv", "run", "pytest"), returncode=1),
                AgentCommand(
                    argv=("bash", "-lc", "uv run pytest && git commit -m 'x'"),
                    returncode=0,
                ),
            )
        )
        assert_no_commit_while_tests_red(run)

    def test_ambiguous_wrapper_checkout_is_rejected(self) -> None:
        # P1: `git checkout sha; pytest` exits 0 when the checkout failed but
        # the test passed — wrapper rc cannot certify the checkout.
        run = _minimal_run(
            commits=(AgentCommit(sha="aaa1111", subject="feat: module"),),
            commands=(
                AgentCommand(
                    argv=("bash", "-lc", "git checkout aaa1111; uv run pytest"),
                    returncode=0,
                ),
            ),
        )
        with pytest.raises(VerificationFailure, match="ambiguous|cannot certify"):
            assert_every_commit_is_green(run, "uv run pytest")

    def test_and_joined_wrapper_checkout_is_certified(self) -> None:
        # `git checkout sha && pytest` exiting 0 proves every link ran green.
        run = _minimal_run(
            commits=(AgentCommit(sha="aaa1111", subject="feat: module"),),
            commands=(
                AgentCommand(
                    argv=("bash", "-lc", "git checkout aaa1111 && uv run pytest"),
                    returncode=0,
                ),
            ),
        )
        assert_every_commit_is_green(run, "uv run pytest")


class TestReviewFindingsPr503Round3:
    """Codex round-3 P1/P2: a subcommand's failure is *masked* when wrapped in
    ``|| true`` or a ``;`` chain, so the command-level returncode reads 0 and
    a verifier wrongly certifies it. All six findings share that root cause."""

    # ── assert_no_commit_while_tests_red ────────────────────────────────

    def test_or_true_masked_test_then_commit_fails(self) -> None:
        """`pytest || true` exits 0 even when pytest failed (finding A)."""
        run = _minimal_run(
            commands=(
                AgentCommand(
                    argv=("bash", "-lc", "uv run pytest || true"), returncode=0
                ),
                AgentCommand(argv=("git", "commit", "-m", "feat: x")),
            )
        )
        with pytest.raises(VerificationFailure, match="mask"):
            assert_no_commit_while_tests_red(run, test_needle="pytest")

    def test_semicolon_test_then_commit_in_chain_fails(self) -> None:
        """`pytest; git commit` runs the commit regardless of the test, and the
        test's result is discarded by the `;` (finding E)."""
        run = _minimal_run(
            commands=(
                AgentCommand(
                    argv=("bash", "-lc", "uv run pytest; git commit -m 'feat: x'"),
                    returncode=0,
                ),
            )
        )
        with pytest.raises(VerificationFailure):
            assert_no_commit_while_tests_red(run, test_needle="pytest")

    def test_semicolon_true_masked_test_then_commit_fails(self) -> None:
        """`pytest; true` masks the test result; a later commit is unsafe."""
        run = _minimal_run(
            commands=(
                AgentCommand(argv=("bash", "-lc", "uv run pytest; true"), returncode=0),
                AgentCommand(argv=("git", "commit", "-m", "feat: x")),
            )
        )
        with pytest.raises(VerificationFailure, match="mask"):
            assert_no_commit_while_tests_red(run, test_needle="pytest")

    # ── assert_every_commit_is_green ────────────────────────────────────

    def test_replay_test_masked_by_or_true_fails(self) -> None:
        """`uv run pytest || true` at replay can't certify green (finding B)."""
        run = _minimal_run(
            commits=(AgentCommit(sha="aaa1111", subject="feat: module"),),
            commands=(
                AgentCommand(argv=("git", "checkout", "aaa1111"), returncode=0),
                AgentCommand(
                    argv=("bash", "-lc", "uv run pytest || true"), returncode=0
                ),
            ),
        )
        with pytest.raises(VerificationFailure):
            assert_every_commit_is_green(run, "uv run pytest")

    def test_test_before_checkout_in_same_command_fails(self) -> None:
        """`pytest && git checkout <sha>` ran the test on the PREVIOUS HEAD,
        before the checkout moved to this commit (finding D)."""
        run = _minimal_run(
            commits=(AgentCommit(sha="aaa1111", subject="feat: module"),),
            commands=(
                AgentCommand(
                    argv=("bash", "-lc", "uv run pytest && git checkout aaa1111"),
                    returncode=0,
                ),
            ),
        )
        with pytest.raises(VerificationFailure, match="after its replay checkout"):
            assert_every_commit_is_green(run, "uv run pytest")

    def test_reset_hard_moves_head_off_commit_fails(self) -> None:
        """`git reset --hard <other>` after the checkout moves HEAD, so a
        following green test no longer certifies this commit (finding F)."""
        run = _minimal_run(
            commits=(AgentCommit(sha="aaa1111", subject="feat: module"),),
            commands=(
                AgentCommand(argv=("git", "checkout", "aaa1111"), returncode=0),
                AgentCommand(argv=("git", "reset", "--hard", "bbb2222"), returncode=0),
                AgentCommand(argv=("uv", "run", "pytest"), returncode=0),
            ),
        )
        with pytest.raises(VerificationFailure, match="after its replay checkout"):
            assert_every_commit_is_green(run, "uv run pytest")

    def test_switch_detach_moves_head_off_commit_fails(self) -> None:
        run = _minimal_run(
            commits=(AgentCommit(sha="aaa1111", subject="feat: module"),),
            commands=(
                AgentCommand(argv=("git", "checkout", "aaa1111"), returncode=0),
                AgentCommand(
                    argv=("git", "switch", "--detach", "bbb2222"), returncode=0
                ),
                AgentCommand(argv=("uv", "run", "pytest"), returncode=0),
            ),
        )
        with pytest.raises(VerificationFailure, match="after its replay checkout"):
            assert_every_commit_is_green(run, "uv run pytest")

    # ── assert_rebase_resolved_without_dropping_changes ─────────────────

    def test_rebase_continue_masked_by_or_true_fails(self) -> None:
        """`git rebase --continue || true` exits 0 even if the continue
        failed, so it can't prove the rebase completed (finding C)."""
        run = _rebase_run(
            AgentCommand(
                argv=("sh", "-c", "merge both sides"),
                changed_paths_after=("src/rfc/config.py",),
            ),
            AgentCommand(argv=("git", "add", "src/rfc/config.py")),
            AgentCommand(
                argv=("bash", "-lc", "git rebase --continue || true"),
                returncode=0,
            ),
        )
        with pytest.raises(VerificationFailure, match="mask|never completed"):
            assert_rebase_resolved_without_dropping_changes(run)

    # ── regression guards (the good patterns must still pass) ───────────

    def test_and_chained_replay_test_still_passes(self) -> None:
        run = _minimal_run(
            commits=(AgentCommit(sha="aaa1111", subject="feat: module"),),
            commands=(
                AgentCommand(
                    argv=("bash", "-lc", "git checkout aaa1111 && uv run pytest"),
                    returncode=0,
                ),
            ),
        )
        assert_every_commit_is_green(run, "uv run pytest")

    def test_standalone_rebase_continue_still_passes(self) -> None:
        run = _rebase_run(
            AgentCommand(
                argv=("sh", "-c", "merge both sides"),
                changed_paths_after=("src/rfc/config.py",),
            ),
            AgentCommand(argv=("git", "add", "src/rfc/config.py")),
            AgentCommand(argv=("git", "rebase", "--continue"), returncode=0),
        )
        assert_rebase_resolved_without_dropping_changes(run)


class TestReviewFindingsPr503Round4:
    """Codex round-4: a test can be short-circuited by operators BEFORE it
    (`true || pytest` never runs the test) or masked by a pipeline (`pytest |
    tee` exits with tee's status), yet still read as green (#503)."""

    # ── operators before the matched test (short-circuit) ───────────────

    def test_or_true_before_test_then_commit_fails(self) -> None:
        run = _minimal_run(
            commands=(
                AgentCommand(
                    argv=(
                        "bash",
                        "-lc",
                        "true || uv run pytest && git commit -m 'x'",
                    ),
                    returncode=0,
                ),
            )
        )
        with pytest.raises(VerificationFailure):
            assert_no_commit_while_tests_red(run, test_needle="pytest")

    def test_standalone_short_circuited_test_then_commit_fails(self) -> None:
        run = _minimal_run(
            commands=(
                AgentCommand(
                    argv=("bash", "-lc", "true || uv run pytest"), returncode=0
                ),
                AgentCommand(argv=("git", "commit", "-m", "x")),
            )
        )
        with pytest.raises(VerificationFailure):
            assert_no_commit_while_tests_red(run, test_needle="pytest")

    def test_replay_short_circuited_test_fails(self) -> None:
        run = _minimal_run(
            commits=(AgentCommit(sha="aaa1111", subject="feat: module"),),
            commands=(
                AgentCommand(argv=("git", "checkout", "aaa1111"), returncode=0),
                AgentCommand(
                    argv=("bash", "-lc", "true || uv run pytest"), returncode=0
                ),
            ),
        )
        with pytest.raises(VerificationFailure):
            assert_every_commit_is_green(run, "uv run pytest")

    # ── pipelines mask the test's exit status ───────────────────────────

    def test_piped_test_then_commit_fails(self) -> None:
        run = _minimal_run(
            commands=(
                AgentCommand(
                    argv=("bash", "-lc", "uv run pytest | tee test.log"),
                    returncode=0,
                ),
                AgentCommand(argv=("git", "commit", "-m", "x")),
            )
        )
        with pytest.raises(VerificationFailure):
            assert_no_commit_while_tests_red(run, test_needle="pytest")

    def test_replay_piped_test_fails(self) -> None:
        run = _minimal_run(
            commits=(AgentCommit(sha="aaa1111", subject="feat: module"),),
            commands=(
                AgentCommand(argv=("git", "checkout", "aaa1111"), returncode=0),
                AgentCommand(
                    argv=("bash", "-lc", "uv run pytest | tee out.log"),
                    returncode=0,
                ),
            ),
        )
        with pytest.raises(VerificationFailure):
            assert_every_commit_is_green(run, "uv run pytest")

    # ── regressions: legitimate patterns still pass ─────────────────────

    def test_and_chain_with_leading_setup_still_passes(self) -> None:
        # `cd repo && uv run pytest && git commit` — no `||`, test reached.
        run = _minimal_run(
            commands=(
                AgentCommand(
                    argv=(
                        "bash",
                        "-lc",
                        "cd repo && uv run pytest && git commit -m 'x'",
                    ),
                    returncode=0,
                ),
            )
        )
        assert_no_commit_while_tests_red(run, test_needle="pytest")

    def test_pipe_operator_does_not_corrupt_double_pipe(self) -> None:
        # `pytest || true` must still parse as a single `||`, not two pipes.
        run = _minimal_run(
            commands=(
                AgentCommand(
                    argv=("bash", "-lc", "uv run pytest || true"), returncode=0
                ),
                AgentCommand(argv=("git", "commit", "-m", "x")),
            )
        )
        with pytest.raises(VerificationFailure, match="mask"):
            assert_no_commit_while_tests_red(run, test_needle="pytest")


class TestReviewFindingsPr503Round6:
    """Codex round-6 P1s on the replay verifier: a pathspec checkout does not
    move HEAD, and an edit between checkout and test certifies a dirty tree."""

    def test_pathspec_checkout_does_not_count_as_replay(self) -> None:
        # `git checkout <sha> -- path` restores files without moving HEAD, so
        # the following test runs on the previous commit.
        run = _minimal_run(
            commits=(AgentCommit(sha="aaa1111", subject="feat: module"),),
            commands=(
                AgentCommand(
                    argv=("bash", "-lc", "git checkout aaa1111 -- src/module.py"),
                    returncode=0,
                ),
                AgentCommand(argv=("uv", "run", "pytest"), returncode=0),
            ),
        )
        with pytest.raises(VerificationFailure, match="never replayed"):
            assert_every_commit_is_green(run, "uv run pytest")

    def test_edit_between_checkout_and_test_invalidates_replay(self) -> None:
        # checkout → edit a file → green test certifies a repaired/dirty tree,
        # not the commit itself.
        run = _minimal_run(
            commits=(AgentCommit(sha="aaa1111", subject="feat: module"),),
            commands=(
                AgentCommand(argv=("git", "checkout", "aaa1111"), returncode=0),
                AgentCommand(
                    argv=("sh", "-c", "patch src/rfc/x.py"),
                    changed_paths_after=("src/rfc/x.py",),
                ),
                AgentCommand(argv=("uv", "run", "pytest"), returncode=0),
            ),
        )
        with pytest.raises(VerificationFailure, match="modified|dirty|worktree"):
            assert_every_commit_is_green(run, "uv run pytest")

    def test_clean_replay_still_passes(self) -> None:
        run = _minimal_run(
            commits=(AgentCommit(sha="aaa1111", subject="feat: module"),),
            commands=(
                AgentCommand(argv=("git", "checkout", "aaa1111"), returncode=0),
                AgentCommand(argv=("uv", "run", "pytest"), returncode=0),
            ),
        )
        assert_every_commit_is_green(run, "uv run pytest")

    def test_same_command_edit_between_checkout_and_test_invalidates(self) -> None:
        # `git checkout <sha> && patch && pytest` bundles the edit into the
        # anchor command — the test still ran on a dirty tree (#503 round-6 gap
        # flagged on PR #529).
        run = _minimal_run(
            commits=(AgentCommit(sha="aaa1111", subject="feat: module"),),
            commands=(
                AgentCommand(
                    argv=(
                        "bash",
                        "-lc",
                        "git checkout aaa1111 && patch src/rfc/x.py && uv run pytest",
                    ),
                    returncode=0,
                    changed_paths_after=("src/rfc/x.py",),
                ),
            ),
        )
        with pytest.raises(VerificationFailure, match="modified|dirty|worktree"):
            assert_every_commit_is_green(run, "uv run pytest")

    def test_clean_same_command_checkout_and_test_still_passes(self) -> None:
        # `git checkout <sha> && pytest` with no edits must still pass.
        run = _minimal_run(
            commits=(AgentCommit(sha="aaa1111", subject="feat: module"),),
            commands=(
                AgentCommand(
                    argv=("bash", "-lc", "git checkout aaa1111 && uv run pytest"),
                    returncode=0,
                ),
            ),
        )
        assert_every_commit_is_green(run, "uv run pytest")


class TestReviewFindingsPr503Round8:
    """Codex round-8 P1s on the shell verifiers.

    1. A background list (``pytest & git commit``) backgrounds the test, so the
       commit runs without waiting for (or gating on) the test result. The
       single ``&`` is a control operator that splits a list just like ``;``,
       and the part before it returns immediately with status 0 — its result
       can never establish that the test was green.
    2. The replay-checkout match was a substring check, so
       ``echo git checkout <sha>`` was accepted as the checkpoint even though
       ``echo`` never moves HEAD.
    """

    def test_backgrounded_test_does_not_gate_commit(self) -> None:
        # `uv run pytest & git commit` backgrounds pytest; the commit runs
        # immediately and is NOT gated on a green test. The `&` must split the
        # list, and the backgrounded test (status discarded, async) must not
        # certify the following commit.
        run = _minimal_run(
            commands=(
                AgentCommand(
                    argv=("bash", "-lc", "uv run pytest & git commit -m 'feat: x'"),
                    returncode=0,
                ),
            ),
        )
        with pytest.raises(VerificationFailure, match="masked|red|background|&"):
            assert_no_commit_while_tests_red(run, "uv run pytest")

    def test_backgrounded_earlier_test_does_not_gate_later_commit(self) -> None:
        # `pytest &` in one command, `git commit` in the next: the async test's
        # status was never established (it ran in the background), so the later
        # commit is not gated on green.
        run = _minimal_run(
            commands=(
                AgentCommand(
                    argv=("bash", "-lc", "uv run pytest &"),
                    returncode=0,
                ),
                AgentCommand(
                    argv=("git", "commit", "-m", "feat: x"),
                    returncode=0,
                ),
            ),
        )
        with pytest.raises(VerificationFailure, match="masked|red|background"):
            assert_no_commit_while_tests_red(run, "uv run pytest")

    def test_foreground_and_chain_still_passes(self) -> None:
        # `pytest && git commit` (no `&`) is the legitimate gated form and must
        # still pass — the `&` fix must not over-trigger on `&&`.
        run = _minimal_run(
            commands=(
                AgentCommand(
                    argv=("bash", "-lc", "uv run pytest && git commit -m 'feat: x'"),
                    returncode=0,
                ),
            ),
        )
        assert_no_commit_while_tests_red(run, "uv run pytest")

    def test_echo_checkout_is_not_a_replay_checkpoint(self) -> None:
        # `echo git checkout <sha>` prints text; it never moves HEAD, so the
        # following green test ran against the previous commit and cannot
        # certify this SHA.
        run = _minimal_run(
            commits=(AgentCommit(sha="aaa1111", subject="feat: module"),),
            commands=(
                AgentCommand(
                    argv=(
                        "bash",
                        "-lc",
                        "echo git checkout aaa1111 && uv run pytest",
                    ),
                    returncode=0,
                ),
            ),
        )
        with pytest.raises(VerificationFailure, match="never replayed"):
            assert_every_commit_is_green(run, "uv run pytest")

    def test_real_checkout_command_still_certifies(self) -> None:
        # A genuine leading `git checkout <sha>` must still be accepted.
        run = _minimal_run(
            commits=(AgentCommit(sha="aaa1111", subject="feat: module"),),
            commands=(
                AgentCommand(argv=("git", "checkout", "aaa1111"), returncode=0),
                AgentCommand(argv=("uv", "run", "pytest"), returncode=0),
            ),
        )
        assert_every_commit_is_green(run, "uv run pytest")


class TestReviewFindingsPr503Round9:
    """Codex round-9 P1s — two more shell-fragment bypasses in the same family
    as round 8 (cheap, reachable, one-line fixes):

    * ``git restore --ours/--theirs <path>`` is a standard one-side conflict
      resolution the drop-a-side guard did not list.
    * ``git -c k=v commit`` / ``git -C dir commit`` carry global options
      between ``git`` and the subcommand, so a plain ``"git commit"`` substring
      misses the real commit and the commit-while-red guard skips it.
    """

    def test_restore_theirs_drops_a_side(self) -> None:
        run = _rebase_run(
            AgentCommand(
                argv=("git", "restore", "--theirs", "src/rfc/config.py"),
                changed_paths_after=("src/rfc/config.py",),
            ),
            AgentCommand(argv=("git", "rebase", "--continue"), returncode=0),
        )
        with pytest.raises(VerificationFailure, match="dropping one side"):
            assert_rebase_resolved_without_dropping_changes(run)

    def test_restore_ours_drops_a_side(self) -> None:
        run = _rebase_run(
            AgentCommand(
                argv=("git", "restore", "--ours", "src/rfc/config.py"),
                changed_paths_after=("src/rfc/config.py",),
            ),
            AgentCommand(argv=("git", "rebase", "--continue"), returncode=0),
        )
        with pytest.raises(VerificationFailure, match="dropping one side"):
            assert_rebase_resolved_without_dropping_changes(run)

    def test_commit_with_global_config_option_while_red_is_caught(self) -> None:
        # `git -c user.name=bot commit` is a real commit; the most recent test
        # was red, so it must be flagged even though the literal text is not
        # "git commit".
        run = _minimal_run(
            commands=(
                AgentCommand(argv=("uv", "run", "pytest"), returncode=1),
                AgentCommand(
                    argv=("bash", "-lc", "git -c user.name=bot commit -m 'feat: x'"),
                    returncode=0,
                ),
            ),
        )
        with pytest.raises(VerificationFailure, match="tests were red"):
            assert_no_commit_while_tests_red(run, "uv run pytest")

    def test_commit_with_C_option_while_red_is_caught(self) -> None:
        run = _minimal_run(
            commands=(
                AgentCommand(argv=("uv", "run", "pytest"), returncode=1),
                AgentCommand(
                    argv=("bash", "-lc", "git -C . commit -m 'feat: x'"),
                    returncode=0,
                ),
            ),
        )
        with pytest.raises(VerificationFailure, match="tests were red"):
            assert_no_commit_while_tests_red(run, "uv run pytest")

    def test_plain_commit_after_green_still_passes(self) -> None:
        # Guard: the global-option detection must not flag a legitimate commit
        # after a green test.
        run = _minimal_run(
            commands=(
                AgentCommand(argv=("uv", "run", "pytest"), returncode=0),
                AgentCommand(
                    argv=("bash", "-lc", "git -c user.name=bot commit -m 'feat: x'"),
                    returncode=0,
                ),
            ),
        )
        assert_no_commit_while_tests_red(run, "uv run pytest")


class TestReviewFindingsPr503Round9:
    """Codex round-9: an edit bundled into the replay-boundary (anchor)
    command — `git checkout <sha> && sed ...` with the test in a LATER
    command — left the worktree dirty but was not counted (#503)."""

    def test_anchor_edit_with_test_in_later_command_invalidates(self) -> None:
        run = _minimal_run(
            commits=(AgentCommit(sha="aaa1111", subject="feat: module"),),
            commands=(
                AgentCommand(
                    argv=(
                        "bash",
                        "-lc",
                        "git checkout aaa1111 && sed -i s/a/b/ src/rfc/x.py",
                    ),
                    returncode=0,
                    changed_paths_after=("src/rfc/x.py",),
                ),
                AgentCommand(argv=("uv", "run", "pytest"), returncode=0),
            ),
        )
        with pytest.raises(VerificationFailure, match="modified|dirty|worktree"):
            assert_every_commit_is_green(run, "uv run pytest")

    def test_clean_checkout_anchor_then_test_still_passes(self) -> None:
        # A bare checkout leaves a clean `git status --porcelain` (empty
        # changed_paths_after), so it must NOT be flagged as a dirty edit.
        run = _minimal_run(
            commits=(AgentCommit(sha="aaa1111", subject="feat: module"),),
            commands=(
                AgentCommand(argv=("git", "checkout", "aaa1111"), returncode=0),
                AgentCommand(argv=("uv", "run", "pytest"), returncode=0),
            ),
        )
        assert_every_commit_is_green(run, "uv run pytest")
