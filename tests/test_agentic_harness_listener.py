"""Tests for rfc.agentic_harness_listener (#352).

The listener auto-captures per-run LLM metrics into the EAV
``agentic_metrics`` table while an ``rfc harness start`` session is
active, joining Robot runs to the harness row via the sidecar
session_id (env-var fallback). No sidecar means warn-once-and-continue,
per the CLAUDE.md skip-and-log rule.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from rfc.agentic_harness_listener import LLM_METRICS_DATA_KEY, AgenticHarnessListener
from rfc.harness_cli import active_session_id
from rfc.harness_db import HarnessDatabase
from rfc.harness_models import AgenticHarness

T0 = "2026-06-11T00:00:00Z"


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)


def _db_url(root: Path) -> str:
    return f"sqlite:///{root / 'h.db'}"


def _seed_harness(root: Path, session_id: str = "sess-1") -> HarnessDatabase:
    db = HarnessDatabase(database_url=_db_url(root))
    db.save_harness(
        AgenticHarness(session_id=session_id, tool_name="claude-code", started_at=T0)
    )
    return db


def _metrics_payload(**overrides) -> str:
    base = {
        "prompt_eval_count": 100,
        "eval_count": 40,
        "total_duration_ns": 2_500_000_000,
    }
    base.update(overrides)
    return json.dumps(base)


def _run_one_test(listener: AgenticHarnessListener, rfc_data: dict[str, str]) -> None:
    listener.start_suite(SimpleNamespace(name="root"), SimpleNamespace())
    listener.start_test(SimpleNamespace(name="t1"), SimpleNamespace())
    for key, payload in rfc_data.items():
        listener._current_test_data[key] = payload
        listener._rfc_data_history.setdefault(key, []).append(payload)
    listener.end_test(SimpleNamespace(name="t1"), SimpleNamespace())
    listener.end_suite(SimpleNamespace(name="root"), SimpleNamespace())


@pytest.fixture()
def plain_cwd(tmp_path, monkeypatch):
    """A non-git cwd with no session env, so no sidecar is found."""
    cwd = tmp_path / "plain"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("SESSION_ID", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("HARNESS_DATABASE_URL", raising=False)
    return cwd


class TestSessionResolution:
    def test_session_id_from_env(self, plain_cwd, tmp_path, monkeypatch):
        monkeypatch.setenv("SESSION_ID", "sess-1")
        db = _seed_harness(tmp_path)
        listener = AgenticHarnessListener(database_url=_db_url(tmp_path))
        _run_one_test(listener, {LLM_METRICS_DATA_KEY: _metrics_payload()})
        assert {m.metric_key for m in db.get_metrics("sess-1")} == {
            "tokens_in",
            "tokens_out",
            "latency_ms",
        }

    def test_session_id_from_sidecar(self, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo(repo)
        monkeypatch.chdir(repo)
        monkeypatch.delenv("SESSION_ID", raising=False)
        (repo / ".git" / "rfc-harness-session.json").write_text(
            json.dumps({"session_id": "sess-2"})
        )
        db = _seed_harness(tmp_path, "sess-2")
        listener = AgenticHarnessListener(database_url=_db_url(tmp_path))
        _run_one_test(listener, {LLM_METRICS_DATA_KEY: _metrics_payload()})
        assert len(db.get_metrics("sess-2")) == 3

    def test_env_session_without_harness_row_skips_persist(
        self, plain_cwd, tmp_path, monkeypatch, caplog
    ):
        """A Make-generated SESSION_ID has no agentic_harnesses row (#419).

        The Makefile exports a fresh UUID when no harness is active;
        persisting against it would violate the FK on every test. The
        listener must verify the row exists, warn once, and disable.
        """
        monkeypatch.setenv("SESSION_ID", "make-fresh-uuid")
        db = HarnessDatabase(database_url=_db_url(tmp_path))  # no seeded row
        listener = AgenticHarnessListener(database_url=_db_url(tmp_path))
        with caplog.at_level("WARNING"):
            _run_one_test(listener, {LLM_METRICS_DATA_KEY: _metrics_payload()})
            _run_one_test(listener, {LLM_METRICS_DATA_KEY: _metrics_payload()})
        assert listener.persisted_count == 0
        assert db.get_metrics("make-fresh-uuid") == []
        warnings = [r for r in caplog.records if "harness" in r.message.lower()]
        assert len(warnings) == 1

    def test_no_session_warns_once_and_continues(self, plain_cwd, tmp_path, caplog):
        listener = AgenticHarnessListener(database_url=_db_url(tmp_path))
        with caplog.at_level("WARNING"):
            _run_one_test(listener, {LLM_METRICS_DATA_KEY: _metrics_payload()})
        warnings = [r for r in caplog.records if "session" in r.message.lower()]
        assert len(warnings) == 1
        assert listener.persisted_count == 0


class TestMetricCapture:
    def test_llm_metrics_event_produces_eav_rows(
        self, plain_cwd, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("SESSION_ID", "sess-1")
        db = _seed_harness(tmp_path)
        listener = AgenticHarnessListener(database_url=_db_url(tmp_path))
        _run_one_test(listener, {LLM_METRICS_DATA_KEY: _metrics_payload()})
        by_key = {m.metric_key: m.metric_value for m in db.get_metrics("sess-1")}
        assert by_key["tokens_in"] == 100.0
        assert by_key["tokens_out"] == 40.0
        assert by_key["latency_ms"] == 2500.0
        assert listener.persisted_count == 3

    def test_grader_score_captured(self, plain_cwd, tmp_path, monkeypatch):
        monkeypatch.setenv("SESSION_ID", "sess-1")
        db = _seed_harness(tmp_path)
        listener = AgenticHarnessListener(database_url=_db_url(tmp_path))
        _run_one_test(
            listener,
            {LLM_METRICS_DATA_KEY: _metrics_payload(), "score": "0.75"},
        )
        by_key = {m.metric_key: m.metric_value for m in db.get_metrics("sess-1")}
        assert by_key["grader_score"] == 0.75

    def test_every_emission_in_history_is_captured(
        self, plain_cwd, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("SESSION_ID", "sess-1")
        db = _seed_harness(tmp_path)
        listener = AgenticHarnessListener(database_url=_db_url(tmp_path))
        listener.start_suite(SimpleNamespace(name="root"), SimpleNamespace())
        listener.start_test(SimpleNamespace(name="t1"), SimpleNamespace())
        listener._rfc_data_history[LLM_METRICS_DATA_KEY] = [
            _metrics_payload(eval_count=10),
            _metrics_payload(eval_count=20),
        ]
        listener.end_test(SimpleNamespace(name="t1"), SimpleNamespace())
        listener.end_suite(SimpleNamespace(name="root"), SimpleNamespace())
        tokens_out = [
            m.metric_value for m in db.get_metrics("sess-1", metric_key="tokens_out")
        ]
        assert sorted(tokens_out) == [10.0, 20.0]

    def test_partial_payload_skips_missing_keys(self, plain_cwd, tmp_path, monkeypatch):
        monkeypatch.setenv("SESSION_ID", "sess-1")
        db = _seed_harness(tmp_path)
        listener = AgenticHarnessListener(database_url=_db_url(tmp_path))
        _run_one_test(
            listener,
            {LLM_METRICS_DATA_KEY: json.dumps({"eval_count": 7})},
        )
        assert {m.metric_key for m in db.get_metrics("sess-1")} == {"tokens_out"}

    def test_bad_payload_logged_and_skipped(
        self, plain_cwd, tmp_path, monkeypatch, caplog
    ):
        monkeypatch.setenv("SESSION_ID", "sess-1")
        _seed_harness(tmp_path)
        listener = AgenticHarnessListener(database_url=_db_url(tmp_path))
        with caplog.at_level("WARNING"):
            _run_one_test(listener, {LLM_METRICS_DATA_KEY: "{not json"})
        assert listener.persisted_count == 0

    def test_db_failure_skip_and_log(self, plain_cwd, tmp_path, monkeypatch, caplog):
        monkeypatch.setenv("SESSION_ID", "sess-1")
        listener = AgenticHarnessListener(
            database_url=f"sqlite:///{tmp_path}/no/such/dir/x.db"
        )
        with caplog.at_level("WARNING"):
            _run_one_test(listener, {LLM_METRICS_DATA_KEY: _metrics_payload()})
        assert listener.persisted_count == 0


class TestActiveSessionId:
    def test_returns_empty_outside_git(self, plain_cwd):
        assert active_session_id() == ""

    def test_returns_sidecar_value(self, tmp_path, monkeypatch):
        repo = tmp_path / "r"
        repo.mkdir()
        _init_repo(repo)
        monkeypatch.chdir(repo)
        (repo / ".git" / "rfc-harness-session.json").write_text(
            json.dumps({"session_id": "sess-7"})
        )
        assert active_session_id() == "sess-7"


class TestListenerRegistration:
    """The listener must be wired into every runner actually in use
    (lesson from #409: ci.listeners alone is retired)."""

    REPO_ROOT = Path(__file__).resolve().parent.parent
    LISTENER = "rfc.agentic_harness_listener.AgenticHarnessListener"

    def test_registered_in_test_suites_yaml(self):
        import yaml

        config = yaml.safe_load(
            (self.REPO_ROOT / "config" / "test_suites.yaml").read_text()
        )
        assert self.LISTENER in config["ci"]["listeners"]

    def test_registered_in_local_models_config(self):
        import yaml

        config = yaml.safe_load(
            (self.REPO_ROOT / "config" / "local_models.yaml").read_text()
        )
        assert self.LISTENER in config["execution"]["listeners"]

    def test_registered_in_makefile_listener_var(self):
        makefile = (self.REPO_ROOT / "Makefile").read_text()
        listener_line = next(
            line for line in makefile.splitlines() if line.startswith("LISTENER ")
        )
        assert self.LISTENER in listener_line

    def test_registered_in_tasks_listeners(self):
        import tasks

        assert self.LISTENER in tasks.LISTENERS
