"""Tests for rfc.test_database (2-table schema)."""

import gzip
import sqlite3
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from rfc.test_database import (
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

    def test_output_xml_url_defaults_to_none(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        db.add_test_run(_make_run())
        runs = db.get_recent_runs(limit=1)
        assert runs[0]["output_xml_url"] is None

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

    def test_no_database_url_raises_error(self, monkeypatch: object) -> None:
        """TestDatabase() with no args and no DATABASE_URL must raise."""
        monkeypatch.delenv("DATABASE_URL", raising=False)  # type: ignore[union-attr]
        with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
            TestDatabase()

    def test_sqlite_url_creates_sqlite_backend(self, tmp_path: object) -> None:
        db_path = str(tmp_path / "test.db")  # type: ignore[operator]
        db = TestDatabase(database_url=f"sqlite:///{db_path}")
        run_id = db.add_test_run(_make_run())
        assert run_id > 0


class TestTestRunDataclass:
    def test_required_fields(self) -> None:
        run = _make_run()
        assert run.model_name == "llama3"
        assert run.total_tests == 10

    def test_optional_fields(self) -> None:
        run = _make_run()
        assert run.rfc_version is None
        assert run.id is None
        assert run.output_xml_gz is None
        assert run.output_xml_url is None


class TestTestResultDataclass:
    def test_required_fields(self) -> None:
        result = TestResult(
            run_id=1,
            test_name="Test One",
            test_status="PASS",
        )
        assert result.run_id == 1
        assert result.test_name == "Test One"
        assert result.score is None

    def test_rfc_version_defaults_none(self) -> None:
        r = TestResult(run_id=1, test_name="T", test_status="PASS")
        assert r.rfc_version is None

    def test_rfc_version_set(self) -> None:
        r = TestResult(
            run_id=1,
            test_name="T",
            test_status="PASS",
            rfc_version="1.0.2",
        )
        assert r.rfc_version == "1.0.2"


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
