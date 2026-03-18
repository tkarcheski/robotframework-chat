"""Tests for rfc.test_database (2-table schema)."""

import gzip
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rfc.test_database import (
    Model,
    TestDatabase,
    TestResult,
    TestRun,
    _SQLAlchemyBackend,
)


def _make_run(**overrides: object) -> TestRun:
    defaults = dict(
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
        model_name="llama3",
        test_suite="math",
        total_tests=10,
        passed=8,
        failed=2,
        skipped=0,
        duration_seconds=120.5,
    )
    defaults.update(overrides)
    return TestRun(**defaults)  # type: ignore[arg-type]


class TestSQLiteBackend:
    def test_init_creates_db_file(self, tmp_path: object) -> None:
        db_path = str(tmp_path / "test.db")  # type: ignore[operator]
        TestDatabase(db_path=db_path)
        assert (tmp_path / "test.db").exists()  # type: ignore[operator]

    def test_add_test_run(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run = _make_run()
        run_id = db.add_test_run(run)
        assert isinstance(run_id, int)
        assert run_id > 0

    def test_add_test_results(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run_id = db.add_test_run(_make_run())

        results = [
            TestResult(
                run_id=run_id,
                test_name="Test One",
                test_status="PASS",
                score=1.0,
                question="What is 2+2?",
                expected_answer="4",
                actual_answer="4",
                grading_reason="correct",
            ),
            TestResult(
                run_id=run_id,
                test_name="Test Two",
                test_status="FAIL",
                score=0.0,
                question="What is 3+3?",
                expected_answer="6",
                actual_answer="5",
                grading_reason="wrong",
            ),
        ]
        db.add_test_results(results)

    def test_get_recent_runs(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        db.add_test_run(_make_run(model_name="model_a"))
        db.add_test_run(_make_run(model_name="model_b"))

        runs = db.get_recent_runs(limit=5)
        assert len(runs) == 2

    def test_get_recent_runs_respects_limit(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        for i in range(5):
            db.add_test_run(_make_run(model_name=f"model_{i}"))

        runs = db.get_recent_runs(limit=2)
        assert len(runs) == 2

    def test_output_xml_url_stored(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run = _make_run(output_xml_url="https://results.example.com/output.xml")
        db.add_test_run(run)
        runs = db.get_recent_runs(limit=1)
        assert runs[0]["output_xml_url"] == "https://results.example.com/output.xml"

    def test_output_xml_url_defaults_to_empty(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        db.add_test_run(_make_run())
        runs = db.get_recent_runs(limit=1)
        assert runs[0]["output_xml_url"] == ""

    def test_output_xml_gz_blob_stored(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        xml_content = b"<robot>test output</robot>"
        compressed = gzip.compress(xml_content)
        run = _make_run(output_xml_gz=compressed)
        db.add_test_run(run)
        runs = db.get_recent_runs(limit=1)
        assert runs[0]["output_xml_gz"] == compressed
        assert gzip.decompress(runs[0]["output_xml_gz"]) == xml_content

    def test_get_test_history(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run_id = db.add_test_run(_make_run())
        db.add_test_results(
            [
                TestResult(
                    run_id=run_id,
                    test_name="Math Addition",
                    test_status="PASS",
                    score=1.0,
                    question="What is 2+2?",
                    expected_answer="4",
                    actual_answer="4",
                    grading_reason="correct",
                ),
            ]
        )

        history = db.get_test_history("Math Addition")
        assert len(history) > 0

    def test_export_to_json(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        db.add_test_run(_make_run())

        json_path = str(tmp_path / "export.json")  # type: ignore[operator]
        db.export_to_json(json_path)
        assert (tmp_path / "export.json").exists()  # type: ignore[operator]

    def test_hostname_stored_on_test_run(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run = _make_run(hostname="dev1")
        db.add_test_run(run)

        runs = db.get_recent_runs(limit=1)
        assert len(runs) == 1
        assert runs[0]["hostname"] == "dev1"


class TestTestDatabase:
    def test_explicit_db_path_uses_sqlite(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        assert db is not None

    def test_facade_delegates_add_test_run(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run_id = db.add_test_run(_make_run())
        assert run_id > 0

    def test_no_database_url_raises_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TestDatabase() with no args and no DATABASE_URL must raise."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
            TestDatabase()

    def test_sqlite_url_creates_sqlite_backend(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        db = TestDatabase(database_url=f"sqlite:///{db_path}")
        run_id = db.add_test_run(_make_run())
        assert run_id > 0


class TestTestRunDataclass:
    def test_required_fields(self) -> None:
        run = _make_run()
        assert run.model_name == "llama3"
        assert run.total_tests == 10

    def test_default_fields(self) -> None:
        run = _make_run()
        assert run.rfc_version == ""
        assert run.id == -1
        assert run.output_xml_gz == b""
        assert run.output_xml_url == ""


class TestTestResultDataclass:
    def test_required_fields(self) -> None:
        result = TestResult(
            run_id=1,
            test_name="Test One",
            test_status="PASS",
        )
        assert result.run_id == 1
        assert result.test_name == "Test One"
        assert result.score == -1.0
        assert isinstance(result.score, float)

    def test_rfc_version_defaults_empty(self) -> None:
        r = TestResult(run_id=1, test_name="T", test_status="PASS")
        assert r.rfc_version == ""

    def test_rfc_version_set(self) -> None:
        r = TestResult(
            run_id=1,
            test_name="T",
            test_status="PASS",
            rfc_version="1.0.2",
        )
        assert r.rfc_version == "1.0.2"


class TestFloatScoreRoundTrip:
    """Verify float scores are stored and retrieved correctly."""

    def test_partial_score_stored(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run_id = db.add_test_run(_make_run())
        db.add_test_results(
            [
                TestResult(
                    run_id=run_id,
                    test_name="Partial Score Test",
                    test_status="PASS",
                    score=0.75,
                ),
            ]
        )
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:  # type: ignore[operator]
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT score FROM test_results").fetchone()
            assert row["score"] == 0.75

    def test_zero_score_stored(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run_id = db.add_test_run(_make_run())
        db.add_test_results(
            [
                TestResult(
                    run_id=run_id,
                    test_name="Zero Score Test",
                    test_status="FAIL",
                    score=0.0,
                ),
            ]
        )
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:  # type: ignore[operator]
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT score FROM test_results").fetchone()
            assert row["score"] == 0.0

    def test_sentinel_score_stored(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run_id = db.add_test_run(_make_run())
        db.add_test_results(
            [
                TestResult(
                    run_id=run_id,
                    test_name="Unscored Test",
                    test_status="PASS",
                ),
            ]
        )
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:  # type: ignore[operator]
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT score FROM test_results").fetchone()
            assert row["score"] == -1.0


class TestRfcVersionRoundTrip:
    """Verify rfc_version is stored and retrieved for each table."""

    def test_test_run_stores_rfc_version(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run = _make_run(rfc_version="1.0.2")
        db.add_test_run(run)
        runs = db.get_recent_runs(limit=1)
        assert runs[0]["rfc_version"] == "1.0.2"

    def test_test_results_stores_rfc_version(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run_id = db.add_test_run(_make_run())
        db.add_test_results(
            [
                TestResult(
                    run_id=run_id,
                    test_name="T",
                    test_status="PASS",
                    rfc_version="1.0.2",
                )
            ]
        )
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:  # type: ignore[operator]
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT rfc_version FROM test_results").fetchone()
            assert row["rfc_version"] == "1.0.2"


class TestSQLAlchemyMigrations:
    """Verify PG migrations run in their own transaction."""

    @patch("rfc.test_database.text", create=True, side_effect=lambda s: s)
    @patch.object(_SQLAlchemyBackend, "__init__", lambda self, url: None)
    def test_each_migration_uses_own_transaction(self, _mock_text: MagicMock) -> None:
        backend = _SQLAlchemyBackend.__new__(_SQLAlchemyBackend)
        backend.engine = MagicMock()

        backend._run_migrations()

        expected_calls = len(_SQLAlchemyBackend._PG_MIGRATIONS)
        actual_calls = backend.engine.begin.call_count
        assert actual_calls == expected_calls

    @patch("rfc.test_database.text", create=True, side_effect=lambda s: s)
    @patch.object(_SQLAlchemyBackend, "__init__", lambda self, url: None)
    def test_later_migrations_run_after_earlier_failure(
        self, _mock_text: MagicMock
    ) -> None:
        backend = _SQLAlchemyBackend.__new__(_SQLAlchemyBackend)
        backend.engine = MagicMock()

        executed_sql: list[str] = []
        call_count = 0

        def fake_begin() -> MagicMock:
            nonlocal call_count
            call_count += 1
            ctx = MagicMock()
            conn = MagicMock()

            if call_count == 1:
                conn.execute.side_effect = Exception("already applied")
            else:
                conn.execute.side_effect = lambda sql: executed_sql.append(str(sql))

            ctx.__enter__.return_value = conn
            ctx.__exit__.return_value = False
            return ctx

        backend.engine.begin = fake_begin

        backend._run_migrations()

        remaining = len(_SQLAlchemyBackend._PG_MIGRATIONS) - 1
        assert len(executed_sql) == remaining


class TestOutputXmlColumnMigrations:
    """Verify migrations add output_xml_url and output_xml_gz columns."""

    def test_migrations_include_output_xml_url_alter(self) -> None:
        """Ensure ALTER TABLE for output_xml_url is in PG migrations."""
        alter_sqls = [
            s
            for s in _SQLAlchemyBackend._PG_MIGRATIONS
            if "output_xml_url" in s and "ALTER" in s.upper()
        ]
        assert len(alter_sqls) == 1, (
            "Expected exactly one ALTER TABLE migration for output_xml_url"
        )

    def test_migrations_include_output_xml_gz_alter(self) -> None:
        """Ensure ALTER TABLE for output_xml_gz is in PG migrations."""
        alter_sqls = [
            s
            for s in _SQLAlchemyBackend._PG_MIGRATIONS
            if "output_xml_gz" in s and "ALTER" in s.upper()
        ]
        assert len(alter_sqls) == 1, (
            "Expected exactly one ALTER TABLE migration for output_xml_gz"
        )


class TestTableRowCount:
    def test_get_table_row_count(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        db.add_test_run(_make_run())
        count = db.get_table_row_count("test_runs")
        assert count == 1

    def test_empty_table(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        count = db.get_table_row_count("test_runs")
        assert count == 0


class TestEmptyResults:
    def test_add_empty_results_is_noop(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        db.add_test_results([])


class TestTagsColumn:
    """Verify tags are stored and retrieved in test_results."""

    def test_tags_stored_on_test_result(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run_id = db.add_test_run(_make_run())
        db.add_test_results(
            [
                TestResult(
                    run_id=run_id,
                    test_name="Tagged Test",
                    test_status="PASS",
                    score=1.0,
                    tags="tier:1,verify:math,score:1",
                ),
            ]
        )
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:  # type: ignore[operator]
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT tags FROM test_results").fetchone()
            assert row["tags"] == "tier:1,verify:math,score:1"

    def test_tags_defaults_to_empty(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run_id = db.add_test_run(_make_run())
        db.add_test_results(
            [
                TestResult(
                    run_id=run_id,
                    test_name="No Tags",
                    test_status="PASS",
                ),
            ]
        )
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:  # type: ignore[operator]
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT tags FROM test_results").fetchone()
            assert row["tags"] == ""


class TestResultsFullView:
    """Verify test_results_full SQL view joins both tables."""

    def test_view_returns_joined_data(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run_id = db.add_test_run(_make_run(model_name="qwen3", hostname="dev1"))
        db.add_test_results(
            [
                TestResult(
                    run_id=run_id,
                    test_name="Math Addition",
                    test_status="PASS",
                    score=1.0,
                    tags="tier:1,verify:math",
                ),
            ]
        )
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:  # type: ignore[operator]
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM test_results_full").fetchone()
            # test_results columns
            assert row["test_name"] == "Math Addition"
            assert row["test_status"] == "PASS"
            assert row["score"] == 1.0
            assert row["tags"] == "tier:1,verify:math"
            # test_runs columns (joined)
            assert row["model_name"] == "qwen3"
            assert row["hostname"] == "dev1"
            assert row["test_suite"] == "math"

    def test_view_includes_all_expected_columns(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run_id = db.add_test_run(
            _make_run(
                output_xml_url="https://example.com/output.xml",
                output_xml_source="/tmp/output.xml",
            )
        )
        db.add_test_results(
            [
                TestResult(
                    run_id=run_id,
                    test_name="Full Data Test",
                    test_status="PASS",
                    score=1.0,
                    tags="tier:1,verify:math",
                    expected_answer="4",
                    actual_answer="4",
                    grading_reason="Correct numeric answer",
                ),
            ]
        )
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:  # type: ignore[operator]
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM test_results_full").fetchone()
            assert row["score"] == 1.0
            assert row["tags"] == "tier:1,verify:math"
            assert row["expected_answer"] == "4"
            assert row["grading_reason"] == "Correct numeric answer"
            assert row["output_xml_url"] == "https://example.com/output.xml"
            assert row["output_xml_source"] == "/tmp/output.xml"

    def test_view_excludes_output_xml_gz(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        compressed = gzip.compress(b"<robot/>")
        run_id = db.add_test_run(_make_run(output_xml_gz=compressed))
        db.add_test_results(
            [
                TestResult(
                    run_id=run_id,
                    test_name="T",
                    test_status="PASS",
                ),
            ]
        )
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:  # type: ignore[operator]
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM test_results_full").fetchone()
            columns = row.keys()
            assert "output_xml_gz" not in columns


class TestNewRunColumns:
    """Verify new inference parameter columns on test_runs."""

    def test_temperature_seed_top_p_top_k_stored(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run = _make_run(temperature=0.7, seed=42, top_p=0.9, top_k=40)
        db.add_test_run(run)
        runs = db.get_recent_runs(limit=1)
        assert runs[0]["temperature"] == 0.7
        assert runs[0]["seed"] == 42
        assert runs[0]["top_p"] == 0.9
        assert runs[0]["top_k"] == 40

    def test_new_run_columns_default_zero(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        db.add_test_run(_make_run())
        runs = db.get_recent_runs(limit=1)
        assert runs[0]["temperature"] == 0.0
        assert runs[0]["seed"] == 0


class TestNewResultColumns:
    """Verify thinking, context, and performance metric columns."""

    def test_thinking_columns_stored(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run_id = db.add_test_run(_make_run())
        db.add_test_results(
            [
                TestResult(
                    run_id=run_id,
                    test_name="Thinking Test",
                    test_status="PASS",
                    thinking_text="I need to reason about this",
                    thinking_tokens=7,
                    num_ctx=4096,
                    num_predict=256,
                ),
            ]
        )
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:  # type: ignore[operator]
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM test_results").fetchone()
            assert row["thinking_text"] == "I need to reason about this"
            assert row["thinking_tokens"] == 7
            assert row["num_ctx"] == 4096
            assert row["num_predict"] == 256

    def test_performance_metrics_stored(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run_id = db.add_test_run(_make_run())
        db.add_test_results(
            [
                TestResult(
                    run_id=run_id,
                    test_name="Perf Test",
                    test_status="PASS",
                    eval_count=186,
                    eval_duration_ns=16907870673,
                    prompt_eval_count=73,
                    prompt_eval_duration_ns=489998464,
                    load_duration_ns=108889428,
                    total_duration_ns=17607688368,
                    tokens_per_second=11.0,
                ),
            ]
        )
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:  # type: ignore[operator]
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM test_results").fetchone()
            assert row["eval_count"] == 186
            assert row["eval_duration_ns"] == 16907870673
            assert row["tokens_per_second"] == 11.0


class TestModelsTable:
    """Verify models table CRUD."""

    def test_upsert_model(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        model = Model(
            name="llama3:8b",
            sha256_digest="abc123",
            size_gb=4.7,
            quantization="Q4_K_M",
            architecture="llama",
            context_length=8192,
            family="llama",
            parameter_count="8B",
        )
        db.upsert_model(model)

        with sqlite3.connect(str(tmp_path / "test.db")) as conn:  # type: ignore[operator]
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM models WHERE name = ?", ("llama3:8b",)
            ).fetchone()
            assert row["name"] == "llama3:8b"
            assert row["quantization"] == "Q4_K_M"
            assert row["context_length"] == 8192

    def test_upsert_model_updates(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        db.upsert_model(Model(name="llama3:8b", context_length=4096))
        db.upsert_model(Model(name="llama3:8b", context_length=8192))

        with sqlite3.connect(str(tmp_path / "test.db")) as conn:  # type: ignore[operator]
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM models WHERE name = ?", ("llama3:8b",)
            ).fetchone()
            assert row["context_length"] == 8192

    def test_model_table_row_count(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        assert db.get_table_row_count("models") == 0
        db.upsert_model(Model(name="model1"))
        db.upsert_model(Model(name="model2"))
        assert db.get_table_row_count("models") == 2


class TestViewIncludesNewColumns:
    """Verify test_results_full view includes new columns."""

    def test_view_has_thinking_and_metrics(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run_id = db.add_test_run(_make_run(temperature=0.5, seed=42))
        db.add_test_results(
            [
                TestResult(
                    run_id=run_id,
                    test_name="Full View Test",
                    test_status="PASS",
                    thinking_text="reasoning",
                    thinking_tokens=1,
                    tokens_per_second=15.0,
                ),
            ]
        )
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:  # type: ignore[operator]
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM test_results_full").fetchone()
            assert row["thinking_text"] == "reasoning"
            assert row["tokens_per_second"] == 15.0
            assert row["temperature"] == 0.5
            assert row["seed"] == 42
