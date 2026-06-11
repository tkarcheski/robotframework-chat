"""Tests for ``ci/backup_push.sh``.

The script clones the backup repo (preserving any artifacts already in the
backups dir), commits everything, and pushes to ``main``. These tests exercise
that contract against a local bare repo so no network is needed.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "ci" / "backup_push.sh"


def _env(backups_dir: Path, repo_url: str) -> dict[str, str]:
    """Environment for running the script — identity is required for `git commit`.

    GIT_CONFIG_GLOBAL/SYSTEM are pointed at /dev/null so the test is hermetic:
    any commit-signing or hook config the host environment has set won't leak
    in and turn the script's `git commit` into a signing call.
    """
    return {
        **os.environ,
        "BACKUPS_DIR": str(backups_dir),
        "BACKUPS_REPO_URL": repo_url,
        "GIT_AUTHOR_NAME": "RFC Backup Test",
        "GIT_AUTHOR_EMAIL": "rfc-backup@example.com",
        "GIT_COMMITTER_NAME": "RFC Backup Test",
        "GIT_COMMITTER_EMAIL": "rfc-backup@example.com",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }


def _run(
    backups_dir: Path, repo_url: str, msg: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), msg],
        env=_env(backups_dir, repo_url),
        capture_output=True,
        text=True,
    )


def _init_bare(path: Path) -> Path:
    subprocess.run(
        ["git", "init", "--quiet", "--bare", str(path)], check=True, capture_output=True
    )
    return path


def _files_on_remote_main(remote: Path, tmp_path: Path) -> list[str]:
    """Clone the bare remote's `main` and list tracked files."""
    verify = tmp_path / "verify"
    subprocess.run(
        ["git", "clone", "--quiet", "--branch", "main", str(remote), str(verify)],
        check=True,
        capture_output=True,
    )
    out = subprocess.run(
        ["git", "-C", str(verify), "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted(out.stdout.split())


def test_clones_bare_remote_and_pushes_artifact_to_main(tmp_path: Path) -> None:
    # Fresh state: backups/ holds an artifact but is not yet a git clone. The
    # script must graft a clone of the (empty) backup repo into backups/, commit
    # the artifact, and push it to main — without erasing the artifact.
    remote = _init_bare(tmp_path / "remote.git")
    backups = tmp_path / "backups"
    backups.mkdir()
    (backups / "db_20260527_010203.sql.gz").write_bytes(b"fake dump")

    result = _run(backups, str(remote), "chore: backup 20260527_010203")

    assert result.returncode == 0, result.stderr
    assert (backups / ".git").exists(), (
        "script should have grafted a .git into backups/"
    )
    assert _files_on_remote_main(remote, tmp_path) == ["db_20260527_010203.sql.gz"]


def test_skips_silently_when_remote_unreachable(tmp_path: Path) -> None:
    # A non-existent remote URL is the realistic "backup repo not yet created"
    # case. The script must exit 0 (so superset-export doesn't hard-fail),
    # leave the artifact on disk, and not create a half-initialized .git.
    backups = tmp_path / "backups"
    backups.mkdir()
    artifact = backups / "db_20260527_010203.sql.gz"
    artifact.write_bytes(b"fake dump")
    unreachable = tmp_path / "does-not-exist.git"

    result = _run(backups, str(unreachable), "chore: backup")

    assert result.returncode == 0
    assert "could not clone" in result.stderr
    assert artifact.exists(), "artifact must survive a failed backup push"
    assert not (backups / ".git").exists()


def test_idempotent_when_no_new_artifacts(tmp_path: Path) -> None:
    # Running the script twice without producing new artifacts must not create
    # an empty commit; the second invocation should report nothing-to-commit
    # and exit 0.
    remote = _init_bare(tmp_path / "remote.git")
    backups = tmp_path / "backups"
    backups.mkdir()
    (backups / "db_20260527_010203.sql.gz").write_bytes(b"fake dump")

    first = _run(backups, str(remote), "chore: backup 20260527_010203")
    assert first.returncode == 0, first.stderr

    second = _run(backups, str(remote), "chore: backup 20260527_010203")
    assert second.returncode == 0, second.stderr
    assert "No new backup artifacts to commit" in second.stdout


@pytest.mark.parametrize("missing", ["BACKUPS_DIR", "BACKUPS_REPO_URL"])
def test_defaults_when_env_unset(
    tmp_path: Path, missing: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # When the optional env vars aren't set, the script must fall back to its
    # documented defaults rather than expanding `set -u` undefined references.
    # We don't actually push here — just confirm the script reaches the clone
    # attempt without an unset-variable error.
    monkeypatch.chdir(tmp_path)
    env = _env(tmp_path / "backups", str(tmp_path / "does-not-exist.git"))
    env.pop(missing, None)
    result = subprocess.run(
        ["bash", str(SCRIPT), "chore: backup"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "unbound variable" not in result.stderr
