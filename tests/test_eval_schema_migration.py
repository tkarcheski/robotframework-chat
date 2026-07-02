"""Tests for the OpenAI-Evals provenance columns on ``test_results`` (#621).

Six additive, nullable columns land via the existing idempotent ALTER-TABLE
migration idiom: ``benchmark``, ``split``, ``instance_id``, ``grader_model``,
``wall_seconds``, ``cost_usd``. ``score`` already exists and is NOT re-added.

Style mirrors ``tests/test_test_database_migration.py`` exactly.
"""

import sqlite3
from datetime import datetime

from rfc.test_database import (
    TestDatabase,
    TestResult,
    TestRun,
    _SQLAlchemyBackend,
)

_EVAL_COLUMNS = (
    "benchmark",
    "split",
    "instance_id",
    "grader_model",
    "wall_seconds",
    "cost_usd",
)

# A test_results table predating the eval-provenance columns (#621). Note it
# DOES carry cache_hit/thinking_tokens (the schema revision just before this).
_PRE_EVAL_TEST_RESULTS_DDL = """
CREATE TABLE test_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    test_name TEXT NOT NULL,
    test_status TEXT NOT NULL,
    score REAL,
    tags TEXT,
    tag_severity TEXT,
    tag_tier INTEGER,
    tag_verify TEXT,
    eval_count INTEGER,
    cache_hit INTEGER DEFAULT 0,
    thinking_tokens INTEGER
)
"""

_PRE_MIGRATION_TEST_RUNS_DDL = """
CREATE TABLE test_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    model_name TEXT NOT NULL,
    test_suite TEXT NOT NULL,
    total_tests INTEGER DEFAULT 0,
    passed INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    duration_seconds REAL,
    git_commit TEXT,
    git_branch TEXT,
    hostname TEXT,
    rfc_version TEXT
)
"""


def _basic_run() -> TestRun:
    return TestRun(
        timestamp=datetime(2026, 6, 17, 0, 0, 0),
        model_name="llama3",
        test_suite="openai-evals",
        total_tests=1,
        passed=1,
        failed=0,
        skipped=0,
        duration_seconds=1.0,
    )


class TestEvalColumnsFreshDb:
    def test_fresh_db_has_all_eval_columns(self, tmp_path):
        db_file = tmp_path / "test.db"
        TestDatabase(db_path=str(db_file))
        with sqlite3.connect(str(db_file)) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(test_results)")}
        for col in _EVAL_COLUMNS:
            assert col in cols, f"{col} missing from fresh test_results"

    def test_score_column_still_present(self, tmp_path):
        # score must NOT be dropped/re-added by this migration.
        db_file = tmp_path / "test.db"
        TestDatabase(db_path=str(db_file))
        with sqlite3.connect(str(db_file)) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(test_results)")}
        assert "score" in cols


class TestEvalColumnsUpgrade:
    def test_columns_added_to_pre_migration_db(self, tmp_path):
        db_file = tmp_path / "test.db"
        with sqlite3.connect(str(db_file)) as conn:
            conn.execute(_PRE_MIGRATION_TEST_RUNS_DDL)
            conn.execute(_PRE_EVAL_TEST_RESULTS_DDL)
            conn.execute(
                "INSERT INTO test_runs (timestamp, model_name, test_suite) "
                "VALUES (?, ?, ?)",
                ("2026-01-01T00:00:00", "llama3", "swebench"),
            )
            conn.execute(
                "INSERT INTO test_results (run_id, test_name, test_status, score) "
                "VALUES (?, ?, ?, ?)",
                (1, "legacy", "PASS", 1.0),
            )
        TestDatabase(db_path=str(db_file))
        with sqlite3.connect(str(db_file)) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(test_results)")}
        for col in _EVAL_COLUMNS:
            assert col in cols, f"{col} not added on upgrade"

    def test_legacy_rows_backfilled_with_swebench_benchmark(self, tmp_path):
        # Existing swebench rows should report benchmark='swebench' after
        # migration so they remain attributable in the unified results view.
        db_file = tmp_path / "test.db"
        with sqlite3.connect(str(db_file)) as conn:
            conn.execute(_PRE_MIGRATION_TEST_RUNS_DDL)
            conn.execute(_PRE_EVAL_TEST_RESULTS_DDL)
            conn.execute(
                "INSERT INTO test_runs (timestamp, model_name, test_suite) "
                "VALUES (?, ?, ?)",
                ("2026-01-01T00:00:00", "llama3", "swebench"),
            )
            conn.execute(
                "INSERT INTO test_results (run_id, test_name, test_status) "
                "VALUES (?, ?, ?)",
                (1, "old", "PASS"),
            )
        TestDatabase(db_path=str(db_file))
        with sqlite3.connect(str(db_file)) as conn:
            row = conn.execute(
                "SELECT benchmark FROM test_results WHERE test_name = 'old'"
            ).fetchone()
        assert row[0] == "swebench"

    def test_migration_is_idempotent(self, tmp_path):
        db_file = tmp_path / "test.db"
        TestDatabase(db_path=str(db_file))
        TestDatabase(db_path=str(db_file))  # second open must not error
        TestDatabase(db_path=str(db_file))


class TestEvalColumnsRoundTrip:
    def test_round_trip_persists_eval_fields(self, tmp_path):
        db_file = tmp_path / "test.db"
        db = TestDatabase(db_path=str(db_file))
        run_id = db.add_test_run(_basic_run())
        db.add_test_results(
            [
                TestResult(
                    run_id=run_id,
                    test_name="t1",
                    test_status="PASS",
                    score=1.0,
                    benchmark="gdpval",
                    split="test",
                    instance_id="gdpval__case-7",
                    grader_model="gpt-4o-mini",
                    wall_seconds=12.5,
                    cost_usd=0.0042,
                )
            ]
        )
        with sqlite3.connect(str(db_file)) as conn:
            row = conn.execute(
                "SELECT benchmark, split, instance_id, grader_model, "
                "wall_seconds, cost_usd FROM test_results WHERE test_name='t1'"
            ).fetchone()
        assert row[0] == "gdpval"
        assert row[1] == "test"
        assert row[2] == "gdpval__case-7"
        assert row[3] == "gpt-4o-mini"
        assert abs(row[4] - 12.5) < 1e-9
        assert abs(row[5] - 0.0042) < 1e-9

    def test_defaults_when_unset(self, tmp_path):
        db_file = tmp_path / "test.db"
        db = TestDatabase(db_path=str(db_file))
        run_id = db.add_test_run(_basic_run())
        db.add_test_results(
            [TestResult(run_id=run_id, test_name="bare", test_status="PASS")]
        )
        with sqlite3.connect(str(db_file)) as conn:
            row = conn.execute(
                "SELECT benchmark, instance_id, cost_usd FROM test_results "
                "WHERE test_name='bare'"
            ).fetchone()
        # Unset eval provenance is empty/NULL, never garbage.
        assert row[0] in ("", None)
        assert row[1] in ("", None)
        assert row[2] in (None, 0.0)


class TestEvalColumnsView:
    def test_view_exposes_eval_columns(self, tmp_path):
        db_file = tmp_path / "test.db"
        db = TestDatabase(db_path=str(db_file))
        run_id = db.add_test_run(_basic_run())
        db.add_test_results(
            [
                TestResult(
                    run_id=run_id,
                    test_name="t1",
                    test_status="PASS",
                    benchmark="swebench",
                    instance_id="x__1",
                    grader_model="judge-model",
                )
            ]
        )
        with sqlite3.connect(str(db_file)) as conn:
            row = conn.execute(
                "SELECT benchmark, instance_id, grader_model "
                "FROM test_results_full WHERE test_name='t1'"
            ).fetchone()
        assert row[0] == "swebench"
        assert row[1] == "x__1"
        assert row[2] == "judge-model"


class TestEvalColumnsDataclass:
    def test_dataclass_defaults(self):
        r = TestResult(run_id=1, test_name="t", test_status="PASS")
        assert r.benchmark == ""
        assert r.split == ""
        assert r.instance_id == ""
        assert r.grader_model == ""
        assert r.wall_seconds == 0.0
        assert r.cost_usd == 0.0


class TestEvalColumnsPgOrdering:
    def test_pg_migrations_add_each_eval_column_before_view(self):
        # Every eval ADD COLUMN must precede the CREATE VIEW that selects it,
        # mirroring the cache_hit/hostname ordering guarantees.
        migrations = _SQLAlchemyBackend._PG_MIGRATIONS
        view_idx = next(
            i
            for i, sql in enumerate(migrations)
            if "CREATE VIEW test_results_full" in sql
        )
        for col in _EVAL_COLUMNS:
            add_idx = next(
                i
                for i, sql in enumerate(migrations)
                if f"ADD COLUMN IF NOT EXISTS {col}" in sql
            )
            assert add_idx < view_idx, f"{col} added after the view"

    def test_pg_backfill_runs_after_add(self):
        # The swebench backfill UPDATE must come after benchmark is added.
        migrations = _SQLAlchemyBackend._PG_MIGRATIONS
        add_idx = next(
            i
            for i, sql in enumerate(migrations)
            if "ADD COLUMN IF NOT EXISTS benchmark" in sql
        )
        backfill_idx = next(
            (
                i
                for i, sql in enumerate(migrations)
                if "UPDATE test_results" in sql and "benchmark" in sql
            ),
            None,
        )
        assert backfill_idx is not None, "no PG benchmark backfill migration found"
        assert add_idx < backfill_idx
