"""Tests for rfc.harness_listener_kw — Robot keyword library for the
AgenticHarnessListener integration suite (Issue #431, merged PR #416).

The library brackets a real harness session via the ``rfc harness`` CLI,
generates a minimal inner Robot suite whose tests emit ``RFC_DATA:llm_metrics``
payloads, runs that suite as a *separate OS process* with the
AgenticHarnessListener attached, and queries the resulting ``agentic_metrics``
rows — so the Robot suite asserts the real end-to-end contract:
run a suite → metrics rows exist keyed to the run's session_id.
"""

from __future__ import annotations

import pytest

from rfc.harness_listener_kw import HarnessListenerRunner

METRIC_KEYS_PER_TEST = {"tokens_in", "tokens_out", "latency_ms"}


@pytest.fixture()
def runner():
    return HarnessListenerRunner()


@pytest.fixture()
def workspace(runner, tmp_path):
    return runner.create_listener_workspace(str(tmp_path))


class TestCreateListenerWorkspace:
    def test_creates_git_repo_with_sqlite_url(self, runner, tmp_path):
        ws = runner.create_listener_workspace(str(tmp_path))
        assert (tmp_path / ".git").is_dir()
        assert ws["path"] == str(tmp_path)
        assert ws["database_url"].startswith("sqlite:///")


class TestStartHarnessSession:
    def test_returns_session_id_with_db_row(self, runner, workspace):
        session_id = runner.start_harness_session(workspace)
        assert session_id
        # The CLI must have created the agentic_harnesses row the
        # listener's FK guard (#419) checks for.
        rows = runner.get_metric_rows(workspace, session_id)
        assert rows == []  # no metrics yet, but the query path works


class TestWriteInnerSuite:
    def test_writes_one_test_per_spec(self, runner, workspace, tmp_path):
        suite = runner.write_inner_suite(workspace, "metrics", "silent", "metrics")
        text = (tmp_path / "inner_suite.robot").read_text()
        assert suite.endswith("inner_suite.robot")
        assert text.count("Inner Test") == 3

    def test_rejects_unknown_spec(self, runner, workspace):
        with pytest.raises(ValueError, match="unknown test spec"):
            runner.write_inner_suite(workspace, "bogus")


class TestEndToEndMetricsCapture:
    def test_metrics_rows_persisted_per_test_case(self, runner, workspace):
        """The core #431 contract: one run, N tests, metric rows per test."""
        session_id = runner.start_harness_session(workspace)
        runner.write_inner_suite(workspace, "metrics", "metrics")
        result = runner.run_inner_suite(workspace)
        assert result["rc"] == 0, result["stderr"]
        rows = runner.get_metric_rows(workspace, session_id)
        by_key: dict[str, list] = {}
        for r in rows:
            by_key.setdefault(r["metric_key"], []).append(r)
        # per-test rows: 2 tests x 3 keys
        for key in METRIC_KEYS_PER_TEST:
            assert len(by_key[key]) == 2
            for r in by_key[key]:
                assert r["metric_value"] > 0
        # per-suite efficiency rows: one each (RFC-010 S1, #258). A real robot
        # run populates result.elapsedtime, so suite_runtime_ms is > 0; the
        # cache is off in this run, so cache_hit_rate is the honest 0.0 baseline.
        assert len(by_key["suite_runtime_ms"]) == 1
        assert by_key["suite_runtime_ms"][0]["metric_value"] > 0
        assert len(by_key["cache_hit_rate"]) == 1
        assert by_key["cache_hit_rate"][0]["metric_value"] == 0.0
        assert len(rows) == 8  # 6 per-test + 2 per-suite
        for row in rows:
            assert row["session_id"] == session_id
            assert row["recorded_at"]

    def test_grader_score_row_captured(self, runner, workspace):
        session_id = runner.start_harness_session(workspace)
        runner.write_inner_suite(workspace, "metrics+score")
        result = runner.run_inner_suite(workspace)
        assert result["rc"] == 0, result["stderr"]
        scores = runner.get_metric_rows(workspace, session_id, "grader_score")
        assert len(scores) == 1
        assert scores[0]["metric_value"] == 0.75

    def test_silent_test_produces_no_rows(self, runner, workspace):
        session_id = runner.start_harness_session(workspace)
        runner.write_inner_suite(workspace, "silent", "metrics")
        result = runner.run_inner_suite(workspace)
        assert result["rc"] == 0, result["stderr"]
        rows = runner.get_metric_rows(workspace, session_id)
        per_test = [r for r in rows if r["metric_key"] in METRIC_KEYS_PER_TEST]
        assert len(per_test) == 3  # only the emitting test yields per-test rows
        # The suite itself still records its two per-suite efficiency rows (#258).
        suite_keys = {
            r["metric_key"] for r in rows if r["metric_key"] not in METRIC_KEYS_PER_TEST
        }
        assert suite_keys == {"cache_hit_rate", "suite_runtime_ms"}
        assert len(rows) == 5


class TestSkipAndLogTolerance:
    def test_db_down_run_still_passes(self, runner, workspace, tmp_path):
        """CLAUDE.md skip-and-log: an unreachable DB never fails the run."""
        session_id = runner.start_harness_session(workspace)
        runner.write_inner_suite(workspace, "metrics")
        bad_url = f"sqlite:///{tmp_path}/no/such/dir/x.db"
        result = runner.run_inner_suite(workspace, database_url=bad_url)
        assert result["rc"] == 0, result["stderr"]
        # Nothing reached the real DB either.
        assert runner.get_metric_rows(workspace, session_id) == []

    def test_no_harness_session_run_passes_with_no_rows(self, runner, workspace):
        """Without `rfc harness start` there is no sidecar: warn, no rows."""
        runner.write_inner_suite(workspace, "metrics")
        result = runner.run_inner_suite(workspace)
        assert result["rc"] == 0, result["stderr"]
        # No session means nothing may be keyed to any session.
        assert runner.get_metric_rows(workspace, "") == []
        assert runner.count_all_metric_rows(workspace) == 0
