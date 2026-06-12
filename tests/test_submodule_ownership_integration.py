"""End-to-end tests for scripts/check_submodule_ownership.py against real git repos.

The unit tests in test_submodule_ownership.py cover evaluate_changes() in
isolation; these tests exercise the full git plumbing path — diff parsing,
per-commit attribution, exit codes, and stderr output — using synthetic
repositories with fake gitlinks (created via ``git update-index --add
--cacheinfo 160000,<sha>,<path>``; no network, no real submodule clones).

Written by the test-design role for the PR #432 test plan
(ai/test-plans/PR-432.md), cases H2, H3, E1-E6, R4, N1, N2.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parent.parent / "scripts" / "check_submodule_ownership.py"
)

OWNER = "test-design@agents.rfc"
NON_OWNER = "engineering@agents.rfc"
HUMAN = "tyler.karcheski@gmail.com"

# Arbitrary valid object ids to use as fake submodule pointers.
SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40


def _git(repo: Path, *args: str, email: str = HUMAN) -> str:
    env_args = [
        "-c",
        f"user.name={email.split('@')[0]}",
        "-c",
        f"user.email={email}",
    ]
    result = subprocess.run(
        ["git", "-C", str(repo), *env_args, *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _commit_gitlink(repo: Path, path: str, sha: str, email: str, msg: str) -> None:
    """Commit a submodule pointer (gitlink) change authored by ``email``."""
    _git(repo, "update-index", "--add", "--cacheinfo", f"160000,{sha},{path}")
    _git(repo, "commit", "-m", msg, email=email)


def _remove_gitlink(repo: Path, path: str, email: str, msg: str) -> None:
    _git(repo, "rm", "--cached", path)
    _git(repo, "commit", "-m", msg, email=email)


def _run_guard(repo: Path, base: str = "base") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--base", base],
        cwd=repo,
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Repo with one human-authored base commit holding a 'results' gitlink,
    tagged as branch 'base'; HEAD stays on 'work' for PR-style commits."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "work")
    (repo / "README.md").write_text("synthetic repo\n")
    _git(repo, "add", "README.md")
    _commit_gitlink(repo, "results", SHA_A, HUMAN, "base: add results gitlink")
    _git(repo, "branch", "base")
    return repo


class TestHappyPaths:
    def test_owner_bump_passes(self, repo: Path) -> None:  # H2
        _commit_gitlink(repo, "results", SHA_B, OWNER, "owner bumps results")
        result = _run_guard(repo)
        assert result.returncode == 0, result.stderr
        assert "1 pointer change(s) checked" in result.stdout

    def test_human_bump_passes(self, repo: Path) -> None:  # H3
        _commit_gitlink(repo, "results", SHA_B, HUMAN, "human bumps results")
        result = _run_guard(repo)
        assert result.returncode == 0, result.stderr

    def test_no_gitlink_changes_passes(self, repo: Path) -> None:  # R4
        (repo / "code.py").write_text("x = 1\n")
        _git(repo, "add", "code.py")
        _git(repo, "commit", "-m", "agent commits ordinary file", email=NON_OWNER)
        result = _run_guard(repo)
        assert result.returncode == 0, result.stderr
        assert "0 pointer change(s) checked" in result.stdout


class TestViolations:
    def test_non_owner_agent_bump_fails_end_to_end(self, repo: Path) -> None:  # N1
        _commit_gitlink(repo, "results", SHA_B, NON_OWNER, "engineering bumps results")
        result = _run_guard(repo)
        assert result.returncode == 1
        assert "Submodule ownership violations" in result.stderr  # N2
        assert NON_OWNER in result.stderr
        assert OWNER in result.stderr

    def test_unknown_submodule_added_by_agent_fails(self, repo: Path) -> None:  # E4
        _commit_gitlink(
            repo, "vendor/newmod", SHA_B, NON_OWNER, "agent adds new gitlink"
        )
        result = _run_guard(repo)
        assert result.returncode == 1
        assert "no owner" in result.stderr
        assert "vendor/newmod" in result.stderr

    def test_gitlink_deletion_by_non_owner_fails(self, repo: Path) -> None:  # E5
        _remove_gitlink(repo, "results", NON_OWNER, "agent deletes results gitlink")
        result = _run_guard(repo)
        assert result.returncode == 1
        assert "results" in result.stderr

    def test_mixed_submodules_only_violation_reported(self, repo: Path) -> None:  # E6
        # Owner-correct bump of results plus a non-owner bump of monitoring/logs.
        _commit_gitlink(repo, "results", SHA_B, OWNER, "owner bumps results")
        _commit_gitlink(
            repo, "monitoring/logs", SHA_C, NON_OWNER, "engineering bumps logs"
        )
        result = _run_guard(repo)
        assert result.returncode == 1
        assert "monitoring/logs" in result.stderr
        assert result.stderr.count("  - ") == 1  # exactly one violation line


class TestMultiCommitAttribution:
    def test_non_owner_bump_flagged_despite_later_owner_bump(
        self, repo: Path
    ) -> None:  # E1
        """Two commits move the same gitlink; the non-owner one is still
        attributed and rejected even though the owner moved it again later."""
        _commit_gitlink(repo, "results", SHA_B, NON_OWNER, "engineering bumps results")
        _commit_gitlink(repo, "results", SHA_C, OWNER, "owner bumps results again")
        result = _run_guard(repo)
        assert result.returncode == 1
        assert NON_OWNER in result.stderr

    def test_bump_then_revert_is_net_zero_and_passes(self, repo: Path) -> None:  # E2
        """A bump reverted before merge leaves the net tree unchanged, so the
        guard passes — accepted behavior (only what lands on merge matters)."""
        _commit_gitlink(repo, "results", SHA_B, NON_OWNER, "engineering bumps results")
        _commit_gitlink(repo, "results", SHA_A, NON_OWNER, "engineering reverts bump")
        result = _run_guard(repo)
        assert result.returncode == 0, result.stderr
        assert "0 pointer change(s) checked" in result.stdout


class TestFailureModes:
    def test_missing_base_ref_fails_closed(self, repo: Path) -> None:  # E3
        """A bad/missing base ref must never silently pass."""
        result = _run_guard(repo, base="origin/does-not-exist")
        assert result.returncode != 0


class TestPathVsGitlinkAttribution:
    def test_file_changes_under_submodule_path_not_attributed(
        self, repo: Path
    ) -> None:  # Codex P2: directory<->submodule conversion
        """Converting a gitlink to a directory (or back) makes `git log -- path`
        list commits that only touched ordinary files under that path; those
        must not be attributed as pointer bumps."""
        # Owner legitimately moves the pointer first (a real gitlink change).
        _commit_gitlink(repo, "results", SHA_B, OWNER, "owner bumps results")
        # Non-owner converts the gitlink to a plain directory with a file in it:
        # commit 1 removes the gitlink (a real gitlink change, owner does it),
        # commit 2 (non-owner) only adds a regular file under results/.
        _remove_gitlink(repo, "results", OWNER, "owner removes results gitlink")
        results_dir = repo / "results"
        results_dir.mkdir()
        (results_dir / "report.txt").write_text("plain file, not a gitlink\n")
        _git(repo, "add", "results/report.txt")
        _git(repo, "commit", "-m", "engineering adds plain file", email=NON_OWNER)
        result = _run_guard(repo)
        # The only gitlink-mode commits are owner-authored; the non-owner
        # file-only commit under results/ must not produce a violation.
        assert result.returncode == 0, result.stderr

    def test_combined_file_and_gitlink_change_still_attributed(
        self, repo: Path
    ) -> None:  # Re-verdict D4 (adversarial, test-design)
        """A single commit that changes BOTH an ordinary file under the
        submodule path AND the gitlink itself must still be attributed: the
        path-vs-gitlink filter may only skip commits with no gitlink-mode
        change, never a commit that hides a pointer change behind file noise.
        """
        # Non-owner converts gitlink -> directory in ONE commit: removes the
        # 'results' gitlink (mode 160000 disappears) and adds a regular file
        # under results/ at the same time.
        _git(repo, "rm", "--cached", "results")
        results_dir = repo / "results"
        results_dir.mkdir()
        (results_dir / "report.txt").write_text("smuggled alongside the bump\n")
        _git(repo, "add", "results/report.txt")
        _git(
            repo,
            "commit",
            "-m",
            "engineering converts results to a plain directory",
            email=NON_OWNER,
        )
        result = _run_guard(repo)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "results" in result.stderr
        assert NON_OWNER in result.stderr
