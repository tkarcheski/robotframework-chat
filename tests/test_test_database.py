"""Tests for rfc.test_database."""

import sqlite3
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from rfc.test_database import (
    HostInfo,
    KeywordResult,
    ModelInfo,
    OllamaMetrics,
    PipelineResult,
    TestDatabase,
    TestResult,
    TestRun,
    _SQLAlchemyBackend,
)


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
    def test_explicit_db_path_uses_sqlite(self, tmp_path):
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        assert db is not None

    def test_facade_delegates_add_test_run(self, tmp_path):
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        run_id = db.add_test_run(_make_run())
        assert run_id > 0

    def test_no_database_url_raises_error(self, monkeypatch):
        """TestDatabase() with no args and no DATABASE_URL must raise."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
            TestDatabase()


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


# ---------------------------------------------------------------------------
# HostInfo dataclass
# ---------------------------------------------------------------------------


def _make_host_info(**overrides: object) -> HostInfo:
    defaults = dict(
        hostname="dev1",
        os_name="Linux",
        os_version="5.15.0",
        cpu_arch="x86_64",
        cpu_count=16,
        total_ram_gb=64.0,
        gpu_info="NVIDIA RTX 4090, 24576 MiB",
    )
    defaults.update(overrides)
    return HostInfo(**defaults)  # type: ignore[arg-type]


class TestHostInfoDataclass:
    def test_required_fields(self) -> None:
        h = _make_host_info()
        assert h.hostname == "dev1"
        assert h.os_name == "Linux"
        assert h.cpu_count == 16
        assert h.total_ram_gb == 64.0

    def test_gpu_info_optional(self) -> None:
        h = _make_host_info(gpu_info=None)
        assert h.gpu_info is None

    def test_id_defaults_none(self) -> None:
        h = _make_host_info()
        assert h.id is None


class TestHostInfoDatabase:
    def test_add_host_info(self, tmp_path) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        host = _make_host_info()
        db.add_or_update_host(host)

    def test_upsert_host_info(self, tmp_path) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        host = _make_host_info(total_ram_gb=32.0)
        db.add_or_update_host(host)
        # Update RAM
        host2 = _make_host_info(total_ram_gb=64.0)
        db.add_or_update_host(host2)

        hosts = db.get_hosts()
        assert len(hosts) == 1
        assert hosts[0]["total_ram_gb"] == 64.0

    def test_get_hosts(self, tmp_path) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        db.add_or_update_host(_make_host_info(hostname="dev1"))
        db.add_or_update_host(_make_host_info(hostname="mini1"))
        hosts = db.get_hosts()
        assert len(hosts) == 2
        hostnames = {h["hostname"] for h in hosts}
        assert hostnames == {"dev1", "mini1"}

    def test_hostname_stored_on_test_run(self, tmp_path) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        run = _make_run(hostname="dev1")
        db.add_test_run(run)

        runs = db.get_recent_runs(limit=1)
        assert len(runs) == 1
        assert runs[0]["hostname"] == "dev1"


class TestSQLAlchemyMigrations:
    """Verify each PG migration runs in its own transaction."""

    @patch("rfc.test_database.text", create=True, side_effect=lambda s: s)
    @patch.object(_SQLAlchemyBackend, "__init__", lambda self, url: None)
    def test_each_migration_uses_own_transaction(self, _mock_text: MagicMock) -> None:
        """engine.begin() must be called once per migration, not once total."""
        backend = _SQLAlchemyBackend.__new__(_SQLAlchemyBackend)
        backend.engine = MagicMock()

        backend._run_migrations()

        expected_calls = len(_SQLAlchemyBackend._PG_MIGRATIONS)
        actual_calls = backend.engine.begin.call_count
        assert actual_calls == expected_calls, (
            f"engine.begin() called {actual_calls} times, "
            f"expected {expected_calls} (once per migration)"
        )

    @patch("rfc.test_database.text", create=True, side_effect=lambda s: s)
    @patch.object(_SQLAlchemyBackend, "__init__", lambda self, url: None)
    def test_later_migrations_run_after_earlier_failure(
        self, _mock_text: MagicMock
    ) -> None:
        """A failing migration must not prevent subsequent migrations."""
        backend = _SQLAlchemyBackend.__new__(_SQLAlchemyBackend)
        backend.engine = MagicMock()

        executed_sql: list[str] = []

        call_count = 0

        def fake_begin():
            nonlocal call_count
            call_count += 1
            ctx = MagicMock()
            conn = MagicMock()

            if call_count == 1:
                # First migration fails
                conn.execute.side_effect = Exception("already applied")
            else:
                conn.execute.side_effect = lambda sql: executed_sql.append(str(sql))

            ctx.__enter__.return_value = conn
            ctx.__exit__.return_value = False
            return ctx

        backend.engine.begin = fake_begin

        backend._run_migrations()

        # Even though the first migration failed, the rest should have run.
        remaining = len(_SQLAlchemyBackend._PG_MIGRATIONS) - 1
        assert len(executed_sql) == remaining, (
            f"Only {len(executed_sql)} migrations ran after first failure, "
            f"expected {remaining}"
        )

    @patch("rfc.test_database.text", create=True, side_effect=lambda s: s)
    @patch.object(_SQLAlchemyBackend, "_run_migrations")
    @patch.object(_SQLAlchemyBackend, "_define_tables")
    def test_migrations_run_when_create_all_fails(
        self,
        _mock_define: MagicMock,
        mock_migrations: MagicMock,
        _mock_text: MagicMock,
    ) -> None:
        """_run_migrations() must execute even if metadata.create_all() raises."""
        with patch("rfc.test_database.create_engine", create=True):
            with patch("rfc.test_database.MetaData", create=True) as mock_meta_cls:
                mock_meta = MagicMock()
                mock_meta.create_all.side_effect = Exception("schema conflict")
                mock_meta_cls.return_value = mock_meta

                _SQLAlchemyBackend(database_url="postgresql://fake")

        mock_migrations.assert_called_once()


# ---------------------------------------------------------------------------
# rfc_version on tables that previously lacked it
# ---------------------------------------------------------------------------


class TestRfcVersionDataclasses:
    """Verify rfc_version field exists on all dataclasses."""

    def test_test_result_rfc_version_defaults_none(self) -> None:
        r = TestResult(
            run_id=1,
            test_name="T",
            test_status="PASS",
            score=None,
            question=None,
            expected_answer=None,
            actual_answer=None,
            grading_reason=None,
        )
        assert r.rfc_version is None

    def test_test_result_rfc_version_set(self) -> None:
        r = TestResult(
            run_id=1,
            test_name="T",
            test_status="PASS",
            score=None,
            question=None,
            expected_answer=None,
            actual_answer=None,
            grading_reason=None,
            rfc_version="0.133.0",
        )
        assert r.rfc_version == "0.133.0"

    def test_keyword_result_rfc_version_defaults_none(self) -> None:
        k = KeywordResult(
            run_id=1,
            test_name="T",
            keyword_name="Ask LLM",
            library_name="rfc.keywords",
            status="PASS",
        )
        assert k.rfc_version is None

    def test_keyword_result_rfc_version_set(self) -> None:
        k = KeywordResult(
            run_id=1,
            test_name="T",
            keyword_name="Ask LLM",
            library_name="rfc.keywords",
            status="PASS",
            rfc_version="0.133.0",
        )
        assert k.rfc_version == "0.133.0"

    def test_pipeline_result_rfc_version_defaults_none(self) -> None:
        p = PipelineResult(
            pipeline_id=100,
            status="success",
            ref="main",
            sha="abc123",
            web_url="https://example.com",
        )
        assert p.rfc_version is None

    def test_pipeline_result_rfc_version_set(self) -> None:
        p = PipelineResult(
            pipeline_id=100,
            status="success",
            ref="main",
            sha="abc123",
            web_url="https://example.com",
            rfc_version="0.133.0",
        )
        assert p.rfc_version == "0.133.0"

    def test_host_info_rfc_version_defaults_none(self) -> None:
        h = _make_host_info()
        assert h.rfc_version is None

    def test_host_info_rfc_version_set(self) -> None:
        h = _make_host_info(rfc_version="0.133.0")
        assert h.rfc_version == "0.133.0"

    def test_model_info_rfc_version_defaults_none(self) -> None:
        m = ModelInfo(
            name="llama3",
            full_name="Meta Llama 3",
            organization="Meta",
            release_date="2024-01-01",
            parameters="8B",
        )
        assert m.rfc_version is None

    def test_model_info_rfc_version_set(self) -> None:
        m = ModelInfo(
            name="llama3",
            full_name="Meta Llama 3",
            organization="Meta",
            release_date="2024-01-01",
            parameters="8B",
            rfc_version="0.133.0",
        )
        assert m.rfc_version == "0.133.0"


class TestRfcVersionRoundTrip:
    """Verify rfc_version is stored and retrieved for each table."""

    def test_test_results_stores_rfc_version(self, tmp_path) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        run_id = db.add_test_run(_make_run())
        db.add_test_results(
            [
                TestResult(
                    run_id=run_id,
                    test_name="T",
                    test_status="PASS",
                    score=1,
                    question=None,
                    expected_answer=None,
                    actual_answer=None,
                    grading_reason=None,
                    rfc_version="0.133.0",
                )
            ]
        )
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT rfc_version FROM test_results").fetchone()
            assert row["rfc_version"] == "0.133.0"

    def test_keyword_results_stores_rfc_version(self, tmp_path) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        run_id = db.add_test_run(_make_run())
        db.add_keyword_results(
            [
                KeywordResult(
                    run_id=run_id,
                    test_name="T",
                    keyword_name="Ask LLM",
                    library_name="rfc.keywords",
                    status="PASS",
                    rfc_version="0.133.0",
                )
            ]
        )
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT rfc_version FROM keyword_results").fetchone()
            assert row["rfc_version"] == "0.133.0"

    def test_pipeline_results_stores_rfc_version(self, tmp_path) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        db.add_pipeline_result(
            PipelineResult(
                pipeline_id=100,
                status="success",
                ref="main",
                sha="abc123",
                web_url="https://example.com",
                rfc_version="0.133.0",
            )
        )
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT rfc_version FROM pipeline_results").fetchone()
            assert row["rfc_version"] == "0.133.0"

    def test_host_info_stores_rfc_version(self, tmp_path) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        db.add_or_update_host(_make_host_info(rfc_version="0.133.0"))
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT rfc_version FROM host_info").fetchone()
            assert row["rfc_version"] == "0.133.0"

    def test_model_stores_rfc_version(self, tmp_path) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        db.add_or_update_model(
            ModelInfo(
                name="llama3",
                full_name="Meta Llama 3",
                organization="Meta",
                release_date="2024-01-01",
                parameters="8B",
                rfc_version="0.133.0",
            )
        )
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT rfc_version FROM models").fetchone()
            assert row["rfc_version"] == "0.133.0"


class TestRfcVersionUpsertPreservesOriginal:
    """Upsert tables must preserve the original rfc_version."""

    def test_host_info_upsert_preserves_rfc_version(self, tmp_path) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        db.add_or_update_host(_make_host_info(rfc_version="0.100.0"))
        # Second upsert with newer version should NOT overwrite
        db.add_or_update_host(_make_host_info(rfc_version="0.133.0"))
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT rfc_version FROM host_info").fetchone()
            assert row["rfc_version"] == "0.100.0"

    def test_model_upsert_preserves_rfc_version(self, tmp_path) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        db.add_or_update_model(
            ModelInfo(
                name="llama3",
                full_name="Meta Llama 3",
                organization="Meta",
                release_date="2024-01-01",
                parameters="8B",
                rfc_version="0.100.0",
            )
        )
        # Second upsert with newer version should NOT overwrite
        db.add_or_update_model(
            ModelInfo(
                name="llama3",
                full_name="Meta Llama 3",
                organization="Meta",
                release_date="2024-01-01",
                parameters="8B",
                rfc_version="0.133.0",
            )
        )
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT rfc_version FROM models").fetchone()
            assert row["rfc_version"] == "0.100.0"

    def test_model_upsert_sets_rfc_version_when_null(self, tmp_path) -> None:
        """When existing record has NULL rfc_version, upsert should set it."""
        db = TestDatabase(db_path=str(tmp_path / "test.db"))
        db.add_or_update_model(
            ModelInfo(
                name="llama3",
                full_name="Meta Llama 3",
                organization="Meta",
                release_date="2024-01-01",
                parameters="8B",
            )
        )
        # Second upsert should fill in the NULL rfc_version
        db.add_or_update_model(
            ModelInfo(
                name="llama3",
                full_name="Meta Llama 3",
                organization="Meta",
                release_date="2024-01-01",
                parameters="8B",
                rfc_version="0.133.0",
            )
        )
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT rfc_version FROM models").fetchone()
            assert row["rfc_version"] == "0.133.0"
