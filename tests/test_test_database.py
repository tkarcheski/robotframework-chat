"""Tests for rfc.test_database (4-table schema).

Schema layout:
    - test_runs          (lean metrics, one row per suite execution)
    - test_results       (lean metrics, one row per test case)
    - test_run_artifacts (per-run heavy archive: output.xml gzip blob)
    - test_result_artifacts (per-result heavy archive: question /
      expected_answer / actual_answer / grading_reason / thinking_text)

Heavy fields are accessible via LEFT JOIN in the ``test_results_full``
view so Superset drill-down still works.
"""

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
    TestResultArtifact,
    TestRun,
    TestRunArtifact,
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
            ),
            TestResult(
                run_id=run_id,
                test_name="Test Two",
                test_status="FAIL",
                score=0.0,
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

    def test_output_xml_source_stored_in_artifact(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run_id = db.add_test_run(_make_run())
        db.add_test_run_artifact(
            TestRunArtifact(
                run_id=run_id,
                output_xml_source="/tmp/output.xml",
            )
        )
        artifact = db.get_test_run_artifact(run_id)
        assert artifact is not None
        assert artifact["output_xml_source"] == "/tmp/output.xml"

    def test_output_xml_gz_blob_stored_in_artifact_table(
        self, tmp_path: object
    ) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        xml_content = b"<robot>test output</robot>"
        compressed = gzip.compress(xml_content)
        run_id = db.add_test_run(_make_run())
        db.add_test_run_artifact(
            TestRunArtifact(run_id=run_id, output_xml_gz=compressed)
        )
        artifact = db.get_test_run_artifact(run_id)
        assert artifact is not None
        assert artifact["output_xml_gz"] == compressed
        assert gzip.decompress(artifact["output_xml_gz"]) == xml_content

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

    def test_update_output_xml_upserts_artifact(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run_id = db.add_test_run(_make_run())

        # Initially no artifact row
        assert db.get_test_run_artifact(run_id) is None

        # Update with compressed blob — should insert an artifact row.
        compressed = gzip.compress(b"<robot>full output</robot>")
        db.update_output_xml(run_id, compressed)

        artifact = db.get_test_run_artifact(run_id)
        assert artifact is not None
        assert artifact["output_xml_gz"] == compressed
        assert (
            gzip.decompress(artifact["output_xml_gz"]) == b"<robot>full output</robot>"
        )

        # Second call — should update the existing artifact row.
        newer = gzip.compress(b"<robot>newer</robot>")
        db.update_output_xml(run_id, newer)
        artifact = db.get_test_run_artifact(run_id)
        assert artifact is not None
        assert artifact["output_xml_gz"] == newer

    def test_update_output_xml_nonexistent_run(self, tmp_path: object) -> None:
        """update_output_xml on a missing run_id should not raise."""
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        db.update_output_xml(9999, gzip.compress(b"<robot/>"))


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
        from rfc.exceptions import MissingEnvironmentError

        with pytest.raises(MissingEnvironmentError, match="DATABASE_URL is not set"):
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
        assert run.git_commit == ""
        assert run.git_branch == ""
        assert run.hostname == ""

    def test_dropped_fields_not_on_dataclass(self) -> None:
        """Inference params and heavy XML fields are no longer on TestRun."""
        run = _make_run()
        for dropped in (
            "temperature",
            "seed",
            "top_p",
            "top_k",
            "output_xml_gz",
            "output_xml_url",
            "output_xml_source",
        ):
            assert not hasattr(run, dropped), f"TestRun should not have {dropped}"


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

    def test_lean_tag_defaults(self) -> None:
        r = TestResult(run_id=1, test_name="T", test_status="PASS")
        assert r.tags == ""
        assert r.tag_severity == ""
        assert r.tag_tier == -1
        assert r.tag_verify == ""


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
    """rfc_version lives only on test_runs (join via run_id for per-test lookups)."""

    def test_test_run_stores_rfc_version(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run = _make_run(rfc_version="1.0.2")
        db.add_test_run(run)
        runs = db.get_recent_runs(limit=1)
        assert runs[0]["rfc_version"] == "1.0.2"


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


class TestLegacyColumnDropMigrations:
    """Verify the PG migrations drop legacy columns from test_runs / test_results."""

    def test_migrations_drop_inference_param_columns_from_test_runs(self) -> None:
        for col in ("temperature", "seed", "top_p", "top_k"):
            matches = [
                s
                for s in _SQLAlchemyBackend._PG_MIGRATIONS
                if f"test_runs DROP COLUMN IF EXISTS {col}".lower() in s.lower()
            ]
            assert matches, f"Missing DROP COLUMN migration for test_runs.{col}"

    def test_migrations_drop_output_xml_columns_from_test_runs(self) -> None:
        for col in ("output_xml_gz", "output_xml_url", "output_xml_source"):
            matches = [
                s
                for s in _SQLAlchemyBackend._PG_MIGRATIONS
                if f"test_runs DROP COLUMN IF EXISTS {col}".lower() in s.lower()
            ]
            assert matches, f"Missing DROP COLUMN migration for test_runs.{col}"

    def test_migrations_drop_heavy_text_columns_from_test_results(self) -> None:
        for col in (
            "question",
            "expected_answer",
            "actual_answer",
            "grading_reason",
            "thinking_text",
            "rfc_version",
        ):
            matches = [
                s
                for s in _SQLAlchemyBackend._PG_MIGRATIONS
                if f"test_results DROP COLUMN IF EXISTS {col}".lower() in s.lower()
            ]
            assert matches, f"Missing DROP COLUMN migration for test_results.{col}"


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
    """Verify test_results_full SQL view joins all four tables."""

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

    def test_view_exposes_archive_fields_via_left_join(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run_id = db.add_test_run(_make_run())
        db.add_test_run_artifact(
            TestRunArtifact(run_id=run_id, output_xml_source="/tmp/output.xml")
        )
        db.add_test_results(
            [
                TestResult(
                    run_id=run_id,
                    test_name="Full Data Test",
                    test_status="PASS",
                    score=1.0,
                    tags="tier:1,verify:math",
                ),
            ]
        )
        result_id = db.get_result_ids_for_run(run_id)["Full Data Test"]

        db.add_test_result_artifacts(
            [
                TestResultArtifact(
                    result_id=result_id,
                    question="What is 2+2?",
                    expected_answer="4",
                    actual_answer="4",
                    grading_reason="Correct numeric answer",
                    thinking_text="2+2 is 4",
                )
            ]
        )

        with sqlite3.connect(str(tmp_path / "test.db")) as conn:  # type: ignore[operator]
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM test_results_full").fetchone()
            assert row["score"] == 1.0
            assert row["tags"] == "tier:1,verify:math"
            assert row["question"] == "What is 2+2?"
            assert row["expected_answer"] == "4"
            assert row["actual_answer"] == "4"
            assert row["grading_reason"] == "Correct numeric answer"
            assert row["thinking_text"] == "2+2 is 4"
            assert row["output_xml_source"] == "/tmp/output.xml"

    def test_view_excludes_output_xml_gz(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        compressed = gzip.compress(b"<robot/>")
        run_id = db.add_test_run(_make_run())
        db.add_test_run_artifact(
            TestRunArtifact(run_id=run_id, output_xml_gz=compressed)
        )
        db.add_test_results(
            [
                TestResult(run_id=run_id, test_name="T", test_status="PASS"),
            ]
        )
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:  # type: ignore[operator]
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM test_results_full").fetchone()
            columns = row.keys()
            assert "output_xml_gz" not in columns

    def test_view_returns_row_when_no_artifacts_present(self, tmp_path: object) -> None:
        """LEFT JOIN means results without artifacts still appear."""
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run_id = db.add_test_run(_make_run())
        db.add_test_results(
            [
                TestResult(run_id=run_id, test_name="No Extras", test_status="PASS"),
            ]
        )
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:  # type: ignore[operator]
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM test_results_full").fetchone()
            assert row["test_name"] == "No Extras"
            assert row["question"] is None
            assert row["actual_answer"] is None
            assert row["output_xml_source"] is None


class TestTestRunArtifact:
    """Verify the test_run_artifacts archive table."""

    def test_add_and_get_run_artifact(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run_id = db.add_test_run(_make_run())
        compressed = gzip.compress(b"<robot/>")
        db.add_test_run_artifact(
            TestRunArtifact(
                run_id=run_id,
                output_xml_gz=compressed,
                output_xml_source="/tmp/output.xml",
            )
        )
        artifact = db.get_test_run_artifact(run_id)
        assert artifact is not None
        assert artifact["output_xml_gz"] == compressed
        assert artifact["output_xml_source"] == "/tmp/output.xml"

    def test_run_artifact_missing_returns_none(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        assert db.get_test_run_artifact(9999) is None

    def test_run_artifact_dataclass_defaults(self) -> None:
        a = TestRunArtifact(run_id=1)
        assert a.output_xml_gz == b""
        assert a.output_xml_source == ""


class TestTestResultArtifact:
    """Verify the test_result_artifacts archive table."""

    def test_add_and_get_result_artifact(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run_id = db.add_test_run(_make_run())
        db.add_test_results(
            [TestResult(run_id=run_id, test_name="T", test_status="PASS")]
        )
        result_id = db.get_result_ids_for_run(run_id)["T"]

        db.add_test_result_artifacts(
            [
                TestResultArtifact(
                    result_id=result_id,
                    question="What is 2+2?",
                    expected_answer="4",
                    actual_answer="4",
                    grading_reason="Correct",
                    thinking_text="2+2=4",
                )
            ]
        )
        artifact = db.get_test_result_artifact(result_id)
        assert artifact is not None
        assert artifact["question"] == "What is 2+2?"
        assert artifact["expected_answer"] == "4"
        assert artifact["actual_answer"] == "4"
        assert artifact["grading_reason"] == "Correct"
        assert artifact["thinking_text"] == "2+2=4"

    def test_add_empty_result_artifacts_is_noop(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        db.add_test_result_artifacts([])

    def test_result_artifact_dataclass_defaults(self) -> None:
        a = TestResultArtifact(result_id=1)
        assert a.question == ""
        assert a.expected_answer == ""
        assert a.actual_answer == ""
        assert a.grading_reason == ""
        assert a.thinking_text == ""


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


class TestEvalCountAndThinkingTokens:
    """The only numeric LLM metrics we still keep on test_results."""

    def test_eval_count_and_thinking_tokens_stored(self, tmp_path: object) -> None:
        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[operator]
        run_id = db.add_test_run(_make_run())
        db.add_test_results(
            [
                TestResult(
                    run_id=run_id,
                    test_name="Lean Metrics Test",
                    test_status="PASS",
                    score=1.0,
                    eval_count=186,
                    thinking_tokens=7,
                ),
            ]
        )
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:  # type: ignore[operator]
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM test_results").fetchone()
            assert row["eval_count"] == 186
            assert row["thinking_tokens"] == 7

    def test_lean_metrics_default_zero(self) -> None:
        r = TestResult(run_id=1, test_name="T", test_status="PASS")
        assert r.eval_count == 0
        assert r.thinking_tokens == 0

    def test_dropped_fields_not_on_test_result_dataclass(self) -> None:
        r = TestResult(run_id=1, test_name="T", test_status="PASS")
        for dropped in (
            "question",
            "expected_answer",
            "actual_answer",
            "grading_reason",
            "thinking_text",
            "reasoning_tokens",
            "cached_tokens",
            "accepted_prediction_tokens",
            "rejected_prediction_tokens",
            "num_ctx",
            "num_predict",
            "eval_duration_ns",
            "prompt_eval_count",
            "prompt_eval_duration_ns",
            "load_duration_ns",
            "total_duration_ns",
            "tokens_per_second",
            "token_retry_count",
            "token_retry_max_tokens",
            "rfc_version",
        ):
            assert not hasattr(r, dropped), (
                f"TestResult should not have {dropped} in the lean schema"
            )
