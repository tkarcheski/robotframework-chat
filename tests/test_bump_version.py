"""Tests for scripts/bump_version.py — version auto-increment logic.

Tests cover:
- Commit message parsing to determine bump type
- Version arithmetic (major/minor/patch increments)
- File update logic (both pyproject.toml and __init__.py)
- Highest-bump-wins when multiple commits are present
- Dry-run mode (no file modification)
- Repository platform detection (GitHub/GitLab/unknown)
- Git tag creation
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from bump_version import (  # noqa: E402
    BumpType,
    apply_version,
    bump_version,
    create_version_tag,
    detect_repo_platform,
    determine_bump,
)


# ── Commit message parsing ──────────────────────────────────────────


class TestDetermineBump:
    """Test commit message parsing to determine bump type."""

    def test_major_from_release(self) -> None:
        """Commit containing 'release' triggers a major bump."""
        commits = ["release: version 1.0.0"]
        assert determine_bump(commits) == BumpType.MAJOR

    def test_minor_from_breaking(self) -> None:
        """Commit containing 'breaking' triggers a minor bump."""
        commits = ["fix: breaking change in API"]
        assert determine_bump(commits) == BumpType.MINOR

    def test_minor_from_bang(self) -> None:
        """Commit with '!' after type prefix triggers a minor bump."""
        commits = ["feat!: redesign config format"]
        assert determine_bump(commits) == BumpType.MINOR

    def test_patch_from_feat(self) -> None:
        """Commit starting with 'feat:' triggers a patch bump."""
        commits = ["feat: add new grading tier"]
        assert determine_bump(commits) == BumpType.PATCH

    def test_patch_from_fix(self) -> None:
        """Commit starting with 'fix:' triggers a patch bump."""
        commits = ["fix: correct token counting in listener"]
        assert determine_bump(commits) == BumpType.PATCH

    def test_none_from_docs(self) -> None:
        """Commit starting with 'docs:' triggers no bump."""
        commits = ["docs: update README with new examples"]
        assert determine_bump(commits) is None

    def test_none_from_chore(self) -> None:
        """Commit starting with 'chore:' triggers no bump."""
        commits = ["chore: update dependencies"]
        assert determine_bump(commits) is None

    def test_none_from_test(self) -> None:
        """Commit starting with 'test:' triggers no bump."""
        commits = ["test: add coverage for grading module"]
        assert determine_bump(commits) is None

    def test_none_from_refactor(self) -> None:
        """Commit starting with 'refactor:' triggers no bump."""
        commits = ["refactor: simplify listener registration"]
        assert determine_bump(commits) is None

    def test_none_from_empty(self) -> None:
        """Empty commit list triggers no bump."""
        assert determine_bump([]) is None

    def test_highest_bump_wins(self) -> None:
        """When multiple commits exist, the highest bump type wins."""
        commits = [
            "fix: patch-level change",
            "feat!: breaking minor change",
            "docs: no bump",
        ]
        assert determine_bump(commits) == BumpType.MINOR

    def test_release_beats_breaking(self) -> None:
        """Release (major) outranks breaking (minor)."""
        commits = [
            "feat!: breaking change",
            "release: version 2.0.0",
        ]
        assert determine_bump(commits) == BumpType.MAJOR

    def test_bang_in_scope_triggers_minor(self) -> None:
        """Conventional commit with scope and bang triggers minor."""
        commits = ["refactor(core)!: rework database schema"]
        assert determine_bump(commits) == BumpType.MINOR

    def test_case_insensitive_release(self) -> None:
        """'release' detection is case-insensitive."""
        commits = ["Release: version 1.0.0"]
        assert determine_bump(commits) == BumpType.MAJOR

    def test_case_insensitive_breaking(self) -> None:
        """'breaking' detection is case-insensitive."""
        commits = ["fix: Breaking change in API"]
        assert determine_bump(commits) == BumpType.MINOR


# ── Version arithmetic ───────────────────────────────────────────────


class TestBumpVersion:
    """Test version string arithmetic."""

    def test_patch_bump(self) -> None:
        assert bump_version("0.133.0", BumpType.PATCH) == "0.133.1"

    def test_minor_bump(self) -> None:
        assert bump_version("0.133.0", BumpType.MINOR) == "0.134.0"

    def test_major_bump(self) -> None:
        assert bump_version("0.133.0", BumpType.MAJOR) == "1.0.0"

    def test_patch_bump_increments_only_patch(self) -> None:
        assert bump_version("1.2.3", BumpType.PATCH) == "1.2.4"

    def test_minor_bump_resets_patch(self) -> None:
        assert bump_version("1.2.3", BumpType.MINOR) == "1.3.0"

    def test_major_bump_resets_minor_and_patch(self) -> None:
        assert bump_version("1.2.3", BumpType.MAJOR) == "2.0.0"


# ── File update logic ────────────────────────────────────────────────


class TestApplyVersion:
    """Test updating version strings in project files."""

    def test_updates_pyproject(self, tmp_path: Path) -> None:
        """apply_version updates version in pyproject.toml."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            textwrap.dedent("""\
                [project]
                name = "test"
                version = "0.1.0"
            """)
        )
        init_file = tmp_path / "__init__.py"
        init_file.write_text('__version__ = "0.1.0"\n')

        apply_version("0.2.0", pyproject_path=pyproject, init_path=init_file)

        assert 'version = "0.2.0"' in pyproject.read_text()

    def test_updates_init(self, tmp_path: Path) -> None:
        """apply_version updates __version__ in __init__.py."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            textwrap.dedent("""\
                [project]
                name = "test"
                version = "0.1.0"
            """)
        )
        init_file = tmp_path / "__init__.py"
        init_file.write_text('__version__ = "0.1.0"\n')

        apply_version("0.2.0", pyproject_path=pyproject, init_path=init_file)

        assert '__version__ = "0.2.0"' in init_file.read_text()

    def test_updates_both_files_in_sync(self, tmp_path: Path) -> None:
        """Both files are updated to the same version."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            textwrap.dedent("""\
                [project]
                name = "test"
                version = "0.5.0"
            """)
        )
        init_file = tmp_path / "__init__.py"
        init_file.write_text('__version__ = "0.5.0"\n')

        apply_version("0.6.0", pyproject_path=pyproject, init_path=init_file)

        assert 'version = "0.6.0"' in pyproject.read_text()
        assert '__version__ = "0.6.0"' in init_file.read_text()

    def test_dry_run_does_not_modify(self, tmp_path: Path) -> None:
        """Dry run leaves files unchanged."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            textwrap.dedent("""\
                [project]
                name = "test"
                version = "0.1.0"
            """)
        )
        init_file = tmp_path / "__init__.py"
        init_file.write_text('__version__ = "0.1.0"\n')

        apply_version(
            "0.2.0", pyproject_path=pyproject, init_path=init_file, dry_run=True
        )

        assert 'version = "0.1.0"' in pyproject.read_text()
        assert '__version__ = "0.1.0"' in init_file.read_text()


# ── Quality gate enforcement ─────────────────────────────────────────


class TestQualityGates:
    """Test that major bumps require quality gates to pass."""

    def test_major_bump_fails_without_passing_gates(self, tmp_path: Path) -> None:
        """Major bump aborts when quality gates fail."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            textwrap.dedent("""\
                [project]
                name = "test"
                version = "0.1.0"
            """)
        )
        init_file = tmp_path / "__init__.py"
        init_file.write_text('__version__ = "0.1.0"\n')

        with patch("bump_version.run_quality_gates", return_value=False):
            with pytest.raises(SystemExit):
                apply_version(
                    "1.0.0",
                    pyproject_path=pyproject,
                    init_path=init_file,
                    bump_type=BumpType.MAJOR,
                )

        # Files should not be modified
        assert 'version = "0.1.0"' in pyproject.read_text()

    def test_major_bump_with_known_issues_bypasses_gates(self, tmp_path: Path) -> None:
        """Major bump succeeds with --known-issues even if gates fail."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            textwrap.dedent("""\
                [project]
                name = "test"
                version = "0.1.0"
            """)
        )
        init_file = tmp_path / "__init__.py"
        init_file.write_text('__version__ = "0.1.0"\n')

        with patch("bump_version.run_quality_gates", return_value=False):
            apply_version(
                "1.0.0",
                pyproject_path=pyproject,
                init_path=init_file,
                bump_type=BumpType.MAJOR,
                known_issues=True,
            )

        assert 'version = "1.0.0"' in pyproject.read_text()


# ── Repository platform detection ────────────────────────────────────


class TestDetectRepoPlatform:
    """Test auto-detection of GitHub vs GitLab from git remote URL."""

    def test_github_https(self) -> None:
        """HTTPS GitHub remote detected as 'github'."""
        with patch("bump_version.subprocess.run") as mock_run:
            mock_run.return_value.stdout = "https://github.com/user/repo.git\n"
            mock_run.return_value.returncode = 0
            assert detect_repo_platform() == "github"

    def test_github_ssh(self) -> None:
        """SSH GitHub remote detected as 'github'."""
        with patch("bump_version.subprocess.run") as mock_run:
            mock_run.return_value.stdout = "git@github.com:user/repo.git\n"
            mock_run.return_value.returncode = 0
            assert detect_repo_platform() == "github"

    def test_gitlab_https(self) -> None:
        """HTTPS GitLab remote detected as 'gitlab'."""
        with patch("bump_version.subprocess.run") as mock_run:
            mock_run.return_value.stdout = "https://gitlab.com/user/repo.git\n"
            mock_run.return_value.returncode = 0
            assert detect_repo_platform() == "gitlab"

    def test_gitlab_ssh(self) -> None:
        """SSH GitLab remote detected as 'gitlab'."""
        with patch("bump_version.subprocess.run") as mock_run:
            mock_run.return_value.stdout = "git@gitlab.com:user/repo.git\n"
            mock_run.return_value.returncode = 0
            assert detect_repo_platform() == "gitlab"

    def test_self_hosted_gitlab(self) -> None:
        """Self-hosted GitLab detected via CI env var."""
        with patch("bump_version.subprocess.run") as mock_run:
            mock_run.return_value.stdout = "https://git.example.com/user/repo.git\n"
            mock_run.return_value.returncode = 0
            with patch.dict("os.environ", {"GITLAB_CI": "true"}):
                assert detect_repo_platform() == "gitlab"

    def test_self_hosted_github(self) -> None:
        """Self-hosted GitHub detected via CI env var."""
        with patch("bump_version.subprocess.run") as mock_run:
            mock_run.return_value.stdout = "https://git.example.com/user/repo.git\n"
            mock_run.return_value.returncode = 0
            with patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}):
                assert detect_repo_platform() == "github"

    def test_unknown_remote(self) -> None:
        """Unknown remote URL returns 'unknown'."""
        with patch("bump_version.subprocess.run") as mock_run:
            mock_run.return_value.stdout = "https://bitbucket.org/user/repo.git\n"
            mock_run.return_value.returncode = 0
            with patch.dict("os.environ", {}, clear=False):
                # Ensure no CI env vars leak in
                env = dict(os.environ)
                env.pop("GITLAB_CI", None)
                env.pop("GITHUB_ACTIONS", None)
                with patch.dict("os.environ", env, clear=True):
                    assert detect_repo_platform() == "unknown"

    def test_no_remote(self) -> None:
        """No git remote returns 'unknown'."""
        with patch(
            "bump_version.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "git"),
        ):
            assert detect_repo_platform() == "unknown"


# ── Git tag creation ─────────────────────────────────────────────────


class TestCreateVersionTag:
    """Test git tag creation."""

    def test_creates_tag(self) -> None:
        """create_version_tag runs git tag with correct version."""
        with patch("bump_version.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            create_version_tag("1.2.3", push=False)

        calls = mock_run.call_args_list
        tag_call = calls[0]
        assert tag_call[0][0] == ["git", "tag", "-a", "v1.2.3", "-m", "v1.2.3"]

    def test_creates_tag_with_v_prefix(self) -> None:
        """Tag always gets v prefix."""
        with patch("bump_version.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            create_version_tag("0.134.0", push=False)

        tag_call = mock_run.call_args_list[0]
        assert "v0.134.0" in tag_call[0][0]

    def test_push_false_does_not_push(self) -> None:
        """push=False creates tag but does not push."""
        with patch("bump_version.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            create_version_tag("1.0.0", push=False)

        assert len(mock_run.call_args_list) == 1  # Only git tag, no push

    def test_push_true_pushes_tag(self) -> None:
        """push=True creates tag then pushes it."""
        with patch("bump_version.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            create_version_tag("1.0.0", push=True)

        calls = mock_run.call_args_list
        assert len(calls) == 2
        push_call = calls[1]
        assert push_call[0][0] == ["git", "push", "origin", "v1.0.0"]

    def test_dry_run_does_nothing(self) -> None:
        """dry_run=True prints but does not create or push."""
        with patch("bump_version.subprocess.run") as mock_run:
            create_version_tag("1.0.0", push=True, dry_run=True)

        mock_run.assert_not_called()
