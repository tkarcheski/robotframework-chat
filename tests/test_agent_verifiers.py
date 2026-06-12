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
