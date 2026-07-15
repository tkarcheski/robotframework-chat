"""Tests for rfc.harness_cli — the `rfc harness start|end|status` CLI."""

import json
import subprocess
from pathlib import Path

import pytest

from rfc.harness_cli import main, makefile_session_id
from rfc.harness_db import HarnessDatabase


def _init_worktree(root: Path) -> None:
    """Create a minimal git repo so the sidecar has a .git dir to live in."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "root",
        ],
        cwd=root,
        check=True,
    )


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """A throwaway git repo as cwd, with a sqlite DB and no inherited env."""
    _init_worktree(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DEFAULT_MODEL", raising=False)
    return tmp_path


def _db_url(root: Path) -> str:
    return f"sqlite:///{root / 'harness.db'}"


def _sidecar(root: Path) -> Path:
    return root / ".git" / "rfc-harness-session.json"


def _start(root: Path, *extra: str) -> int:
    return main(
        [
            "harness",
            "start",
            "--tool",
            "claude-code",
            "--tool-version",
            "1.0.0",
            "--database-url",
            _db_url(root),
            *extra,
        ]
    )


class TestStart:
    def test_writes_sidecar_and_db_row(self, repo):
        assert _start(repo) == 0
        sidecar = json.loads(_sidecar(repo).read_text())
        assert set(sidecar) == {"session_id", "tool_name", "tool_version", "started_at"}
        assert sidecar["tool_name"] == "claude-code"
        db = HarnessDatabase(database_url=_db_url(repo))
        harness = db.get_harness(sidecar["session_id"])
        assert harness is not None
        assert harness.tool_name == "claude-code"
        assert harness.tool_version == "1.0.0"
        assert harness.outcome == ""

    def test_snapshots_plugins_and_skills(self, repo):
        (repo / "robot").mkdir()
        (repo / "robot" / "x.resource").write_text("*** Keywords ***\n")
        subprocess.run(["git", "add", "robot/x.resource"], cwd=repo, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "-q",
                "-m",
                "r",
            ],
            cwd=repo,
            check=True,
        )
        assert _start(repo) == 0
        session_id = json.loads(_sidecar(repo).read_text())["session_id"]
        db = HarnessDatabase(database_url=_db_url(repo))
        assert any(
            p.plugin_name == "robotframework" for p in db.get_plugins(session_id)
        )
        assert [s.skill_path for s in db.get_skills(session_id)] == ["robot/x.resource"]

    def test_existing_sidecar_blocks_without_force(self, repo, capsys):
        assert _start(repo) == 0
        first = json.loads(_sidecar(repo).read_text())["session_id"]
        assert _start(repo) == 1
        assert json.loads(_sidecar(repo).read_text())["session_id"] == first

    def test_force_overwrite_replaces_session(self, repo):
        assert _start(repo) == 0
        first = json.loads(_sidecar(repo).read_text())["session_id"]
        assert _start(repo, "--force-overwrite") == 0
        assert json.loads(_sidecar(repo).read_text())["session_id"] != first

    def test_force_overwrite_closes_previous_db_row(self, repo):
        assert _start(repo) == 0
        first = json.loads(_sidecar(repo).read_text())["session_id"]
        assert _start(repo, "--force-overwrite") == 0
        db = HarnessDatabase(database_url=_db_url(repo))
        old = db.get_harness(first)
        assert old is not None
        assert old.outcome == "abandoned"
        assert old.ended_at

    def test_force_overwrite_survives_unreachable_db(self, repo, capsys):
        assert _start(repo) == 0
        rc = main(
            [
                "harness",
                "start",
                "--tool",
                "claude-code",
                "--tool-version",
                "1",
                "--database-url",
                f"sqlite:///{repo}/no/such/dir/x.db",
                "--force-overwrite",
            ]
        )
        assert rc == 0
        assert _sidecar(repo).exists()

    def test_snapshots_skills_from_repo_root_when_run_in_subdir(
        self, repo, monkeypatch
    ):
        (repo / "robot").mkdir()
        (repo / "robot" / "x.resource").write_text("*** Keywords ***\n")
        subprocess.run(["git", "add", "robot/x.resource"], cwd=repo, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "-q",
                "-m",
                "r",
            ],
            cwd=repo,
            check=True,
        )
        subdir = repo / "src"
        subdir.mkdir()
        monkeypatch.chdir(subdir)
        assert _start(repo) == 0
        session_id = json.loads(_sidecar(repo).read_text())["session_id"]
        db = HarnessDatabase(database_url=_db_url(repo))
        assert [s.skill_path for s in db.get_skills(session_id)] == ["robot/x.resource"]

    def test_model_falls_back_to_default_model_env(self, repo, monkeypatch):
        monkeypatch.setenv("DEFAULT_MODEL", "llama3:latest")
        assert _start(repo) == 0
        session_id = json.loads(_sidecar(repo).read_text())["session_id"]
        db = HarnessDatabase(database_url=_db_url(repo))
        harness = db.get_harness(session_id)
        assert harness is not None
        assert harness.model_id == "llama3:latest"

    def test_no_database_url_hard_fails(self, repo, capsys):
        rc = main(["harness", "start", "--tool", "claude-code", "--tool-version", "1"])
        assert rc == 2
        assert not _sidecar(repo).exists()

    def test_unreachable_db_still_writes_sidecar(self, repo, capsys):
        rc = main(
            [
                "harness",
                "start",
                "--tool",
                "claude-code",
                "--tool-version",
                "1",
                "--database-url",
                f"sqlite:///{repo}/no/such/dir/x.db",
            ]
        )
        assert rc == 0
        assert _sidecar(repo).exists()
        assert "skip" in capsys.readouterr().err.lower()


class TestEnd:
    def test_end_closes_db_row_and_removes_sidecar(self, repo):
        assert _start(repo) == 0
        session_id = json.loads(_sidecar(repo).read_text())["session_id"]
        rc = main(
            ["harness", "end", "--outcome", "success", "--database-url", _db_url(repo)]
        )
        assert rc == 0
        assert not _sidecar(repo).exists()
        db = HarnessDatabase(database_url=_db_url(repo))
        harness = db.get_harness(session_id)
        assert harness is not None
        assert harness.outcome == "success"
        assert harness.ended_at

    def test_end_without_active_session_fails(self, repo, capsys):
        rc = main(
            ["harness", "end", "--outcome", "success", "--database-url", _db_url(repo)]
        )
        assert rc == 1
        assert "no active session" in capsys.readouterr().err.lower()


class TestStatus:
    def test_status_prints_active_session(self, repo, capsys):
        assert _start(repo) == 0
        session_id = json.loads(_sidecar(repo).read_text())["session_id"]
        assert main(["harness", "status"]) == 0
        out = capsys.readouterr().out
        assert session_id in out
        assert "claude-code" in out

    def test_status_without_session(self, repo, capsys):
        assert main(["harness", "status"]) == 0
        assert "no active session" in capsys.readouterr().out.lower()


class TestToolVersion:
    def test_claude_code_probes_claude_executable(self, monkeypatch):
        from rfc import harness_cli

        seen: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            seen.append(cmd)

            class Result:
                returncode = 0
                stdout = "1.2.3\n"

            return Result()

        monkeypatch.setattr(harness_cli.subprocess, "run", fake_run)
        assert harness_cli._tool_version("claude-code", "") == "1.2.3"
        assert seen == [["claude", "--version"]]

    def test_other_tools_probe_their_own_name(self, monkeypatch):
        from rfc import harness_cli

        seen: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            seen.append(cmd)

            class Result:
                returncode = 0
                stdout = "0.1\n"

            return Result()

        monkeypatch.setattr(harness_cli.subprocess, "run", fake_run)
        assert harness_cli._tool_version("codex", "") == "0.1"
        assert seen == [["codex", "--version"]]

    def test_no_version_probe_skips_subprocess(self, repo, monkeypatch):
        from rfc import harness_cli

        real_run = harness_cli.subprocess.run

        def boom(cmd, **kwargs):
            if "--version" in cmd:
                raise AssertionError(f"probe ran: {cmd}")
            return real_run(cmd, **kwargs)

        monkeypatch.setattr(harness_cli.subprocess, "run", boom)
        rc = main(
            [
                "harness",
                "start",
                "--tool",
                "claude-code",
                "--database-url",
                _db_url(repo),
                "--no-version-probe",
            ]
        )
        assert rc == 0
        assert json.loads(_sidecar(repo).read_text())["tool_version"] == ""


class TestMakefileSessionId:
    def test_returns_active_sidecar_session_id(self, repo):
        assert _start(repo) == 0
        session_id = json.loads(_sidecar(repo).read_text())["session_id"]
        assert makefile_session_id() == session_id

    def test_returns_fresh_uuid_without_sidecar(self, repo):
        value = makefile_session_id()
        assert len(value) == 32
        int(value, 16)
        assert makefile_session_id() != value

    def test_returns_fresh_uuid_outside_git_repo(self, tmp_path, monkeypatch):
        outside = tmp_path / "plain"
        outside.mkdir()
        monkeypatch.chdir(outside)
        value = makefile_session_id()
        assert len(value) == 32
        int(value, 16)


class TestWorktreeIsolation:
    def test_concurrent_starts_do_not_collide(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("DEFAULT_MODEL", raising=False)
        a, b = tmp_path / "a", tmp_path / "b"
        sessions = []
        for root in (a, b):
            root.mkdir()
            _init_worktree(root)
            monkeypatch.chdir(root)
            assert _start(root) == 0
            sessions.append(json.loads(_sidecar(root).read_text())["session_id"])
        assert _sidecar(a).exists() and _sidecar(b).exists()
        assert sessions[0] != sessions[1]


class TestScoreboard:
    """`rfc harness scoreboard` — the RFC-010 S1 read surface (#258)."""

    def _seed(self, root: Path, session_id: str = "s-eff") -> HarnessDatabase:
        from rfc.harness_models import AgenticHarness, AgenticMetric

        db = HarnessDatabase(database_url=_db_url(root))
        db.save_harness(
            AgenticHarness(
                session_id=session_id,
                tool_name="claude-code",
                started_at="2026-06-11T00:00:00Z",
            )
        )
        db.save_metrics(
            [
                AgenticMetric(
                    session_id=session_id,
                    metric_key="cache_hit_rate",
                    recorded_at="2026-06-11T00:00:01Z",
                    metric_value=0.5,
                ),
                AgenticMetric(
                    session_id=session_id,
                    metric_key="cache_hit_rate",
                    recorded_at="2026-06-11T00:00:02Z",
                    metric_value=1.0,
                ),
                AgenticMetric(
                    session_id=session_id,
                    metric_key="suite_runtime_ms",
                    recorded_at="2026-06-11T00:00:03Z",
                    metric_value=1200.0,
                ),
            ]
        )
        return db

    def test_prints_aggregated_metrics(self, repo, capsys):
        self._seed(repo)
        rc = main(
            [
                "harness",
                "scoreboard",
                "--session",
                "s-eff",
                "--database-url",
                _db_url(repo),
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "cache_hit_rate:   0.750" in out  # AVG(0.5, 1.0)
        assert "suite_runtime_ms: 1200.0" in out

    def test_defaults_to_active_sidecar_session(self, repo, capsys):
        self._seed(repo, "s-side")
        _sidecar(repo).write_text(json.dumps({"session_id": "s-side"}))
        rc = main(["harness", "scoreboard", "--database-url", _db_url(repo)])
        assert rc == 0
        assert "session s-side" in capsys.readouterr().out

    def test_reports_when_no_metrics_recorded(self, repo, capsys):
        from rfc.harness_models import AgenticHarness

        db = HarnessDatabase(database_url=_db_url(repo))
        db.save_harness(
            AgenticHarness(
                session_id="empty",
                tool_name="claude-code",
                started_at="2026-06-11T00:00:00Z",
            )
        )
        rc = main(
            [
                "harness",
                "scoreboard",
                "--session",
                "empty",
                "--database-url",
                _db_url(repo),
            ]
        )
        assert rc == 0
        assert "no efficiency metrics" in capsys.readouterr().out

    def test_no_session_is_an_error(self, repo, capsys):
        rc = main(["harness", "scoreboard", "--database-url", _db_url(repo)])
        assert rc == 1
        assert "no session" in capsys.readouterr().err

    def test_pre_s1_session_reports_no_efficiency_metrics(self, repo, capsys):
        """Rows that predate S1 (per-test keys only) must not crash or divide.

        Added during the test-design verdict on PR #298: a session whose
        agentic_metrics rows carry only the pre-S1 keys (tokens/latency)
        exercises the empty-aggregate path with a NON-empty metrics table.
        """
        from rfc.harness_models import AgenticHarness, AgenticMetric

        db = HarnessDatabase(database_url=_db_url(repo))
        db.save_harness(
            AgenticHarness(
                session_id="pre-s1",
                tool_name="claude-code",
                started_at="2026-06-11T00:00:00Z",
            )
        )
        db.save_metrics(
            [
                AgenticMetric(
                    session_id="pre-s1",
                    metric_key="tokens_in",
                    recorded_at="2026-06-11T00:00:01Z",
                    metric_value=100.0,
                ),
                AgenticMetric(
                    session_id="pre-s1",
                    metric_key="latency_ms",
                    recorded_at="2026-06-11T00:00:02Z",
                    metric_value=2500.0,
                ),
            ]
        )
        rc = main(
            [
                "harness",
                "scoreboard",
                "--session",
                "pre-s1",
                "--database-url",
                _db_url(repo),
            ]
        )
        assert rc == 0
        assert "no efficiency metrics" in capsys.readouterr().out

    def test_no_database_is_an_error(self, repo, capsys):
        rc = main(["harness", "scoreboard", "--session", "s-eff"])
        assert rc == 1
        assert "no database" in capsys.readouterr().err
