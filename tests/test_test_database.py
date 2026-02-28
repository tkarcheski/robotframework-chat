"""Tests for rfc.test_database."""

from datetime import datetime

from rfc.test_database import OllamaMetrics, TestDatabase, TestResult, TestRun


def _make_run(**overrides):
    defaults = dict(
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
        model_name="llama3",
        model_release_date="2024-01-01",
        model_parameters="8B",
        test_suite="math",
        git_commit="abc123",
        git_branch="main",
        pipeline_url="",
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
        db.add_test_results(
            [
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
            ]
        )

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


def _make_metrics(**overrides):
    defaults = dict(
        run_id=1,
        test_name="Math Test",
        model_name="llama3",
        prompt_text="What is 2+2?",
        total_duration_ns=17607688368,
        load_duration_ns=108889428,
        prompt_eval_count=73,
        prompt_eval_duration_ns=489998464,
        prompt_eval_rate=148.98,
        eval_count=186,
        eval_duration_ns=16907870673,
        eval_rate=11.00,
        rfc_version="0.2.0",
    )
    defaults.update(overrides)
    return OllamaMetrics(**defaults)


class TestOllamaMetricsDataclass:
    def test_required_fields(self):
        m = _make_metrics()
        assert m.run_id == 1
        assert m.test_name == "Math Test"
        assert m.model_name == "llama3"
        assert m.total_duration_ns == 17607688368
        assert m.eval_rate == 11.00
        assert m.rfc_version == "0.2.0"

    def test_optional_fields_default_none(self):
        m = _make_metrics()
        assert m.timestamp is None
        assert m.id is None

    def test_nullable_metrics(self):
        m = _make_metrics(
            total_duration_ns=None,
            load_duration_ns=None,
            prompt_eval_count=None,
            prompt_eval_duration_ns=None,
            prompt_eval_rate=None,
            eval_count=None,
            eval_duration_ns=None,
            eval_rate=None,
        )
        assert m.total_duration_ns is None
        assert m.eval_rate is None


class TestOllamaMetricsDatabase:
    def test_add_ollama_metrics(self, tmp_path):
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        run_id = db.add_test_run(_make_run())
        metrics = [_make_metrics(run_id=run_id)]
        db.add_ollama_metrics(metrics)

    def test_add_empty_ollama_metrics(self, tmp_path):
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        db.add_ollama_metrics([])

    def test_get_ollama_metrics(self, tmp_path):
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        run_id = db.add_test_run(_make_run())
        db.add_ollama_metrics([_make_metrics(run_id=run_id)])

        rows = db.get_ollama_metrics(limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert row["model_name"] == "llama3"
        assert row["total_duration_ns"] == 17607688368
        assert row["eval_rate"] == 11.00
        assert row["rfc_version"] == "0.2.0"
        assert row["prompt_text"] == "What is 2+2?"

    def test_get_ollama_metrics_respects_limit(self, tmp_path):
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        run_id = db.add_test_run(_make_run())
        for i in range(5):
            db.add_ollama_metrics([_make_metrics(run_id=run_id, test_name=f"Test {i}")])

        rows = db.get_ollama_metrics(limit=2)
        assert len(rows) == 2

    def test_multiple_metrics_per_run(self, tmp_path):
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        run_id = db.add_test_run(_make_run())
        db.add_ollama_metrics(
            [
                _make_metrics(run_id=run_id, test_name="Test A", eval_rate=11.0),
                _make_metrics(run_id=run_id, test_name="Test B", eval_rate=15.5),
            ]
        )

        rows = db.get_ollama_metrics(limit=10)
        assert len(rows) == 2
