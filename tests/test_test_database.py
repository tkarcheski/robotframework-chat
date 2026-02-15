"""Tests for rfc.test_database."""

from datetime import datetime

import pytest

from rfc.test_database import TestDatabase, TestResult, TestRun


def _make_run(**overrides):
    defaults = dict(
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
        model_name="llama3",
        model_release_date="2024-01-01",
        model_parameters="8B",
        test_suite="math",
        gitlab_commit="abc123",
        gitlab_branch="main",
        gitlab_pipeline_url="",
        runner_id="",
        runner_tags="",
        total_tests=10,
        passed=8,
        failed=2,
        skipped=0,
        duration_seconds=120.5,
    )
    defaults.update(overrides)
    return TestRun(**defaults)


class TestSQLiteBackend:
    def test_init_creates_db_file(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        TestDatabase(db_path=db_path)
        assert (tmp_path / "test.db").exists()

    def test_add_test_run(self, tmp_path):
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        run = _make_run()
        run_id = db.add_test_run(run)
        assert isinstance(run_id, int)
        assert run_id > 0

    def test_add_test_results(self, tmp_path):
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        run_id = db.add_test_run(_make_run())

        results = [
            TestResult(
                run_id=run_id,
                test_name="Test One",
                test_status="PASS",
                score=1,
                question="What is 2+2?",
                expected_answer="4",
                actual_answer="4",
                grading_reason="correct",
            ),
            TestResult(
                run_id=run_id,
                test_name="Test Two",
                test_status="FAIL",
                score=0,
                question="What is 3+3?",
                expected_answer="6",
                actual_answer="5",
                grading_reason="wrong",
            ),
        ]
        db.add_test_results(results)

    def test_get_recent_runs(self, tmp_path):
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        db.add_test_run(_make_run(model_name="model_a"))
        db.add_test_run(_make_run(model_name="model_b"))

        runs = db.get_recent_runs(limit=5)
        assert len(runs) == 2

    def test_get_recent_runs_respects_limit(self, tmp_path):
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        for i in range(5):
            db.add_test_run(_make_run(model_name=f"model_{i}"))

        runs = db.get_recent_runs(limit=2)
        assert len(runs) == 2

    def test_get_model_performance(self, tmp_path):
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        db.add_test_run(_make_run(model_name="llama3", passed=8, failed=2))

        perf = db.get_model_performance("llama3")
        assert len(perf) > 0

    def test_get_test_history(self, tmp_path):
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        run_id = db.add_test_run(_make_run())
        db.add_test_results([
            TestResult(
                run_id=run_id,
                test_name="Math Addition",
                test_status="PASS",
                score=1,
                question="What is 2+2?",
                expected_answer="4",
                actual_answer="4",
                grading_reason="correct",
            ),
        ])

        history = db.get_test_history("Math Addition")
        assert len(history) > 0

    def test_export_to_json(self, tmp_path):
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        db.add_test_run(_make_run())

        json_path = str(tmp_path / "export.json")
        db.export_to_json(json_path)
        assert (tmp_path / "export.json").exists()


class TestTestDatabase:
    def test_default_sqlite_backend(self, tmp_path):
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        assert db is not None

    def test_facade_delegates_add_test_run(self, tmp_path):
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        run_id = db.add_test_run(_make_run())
        assert run_id > 0


class TestTestRunDataclass:
    def test_required_fields(self):
        run = _make_run()
        assert run.model_name == "llama3"
        assert run.total_tests == 10

    def test_optional_fields(self):
        run = _make_run()
        assert run.rfc_version is None
        assert run.id is None


class TestTestResultDataclass:
    def test_required_fields(self):
        result = TestResult(
            run_id=1,
            test_name="Test One",
            test_status="PASS",
            score=None,
            question=None,
            expected_answer=None,
            actual_answer=None,
            grading_reason=None,
        )
        assert result.run_id == 1
        assert result.test_name == "Test One"
        assert result.score is None
