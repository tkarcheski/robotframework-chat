"""Tests for HarnessDatabase. Behavioural tests run against SQLite via
tmp_path. Task 3 parametrises the same tests against a sqlite:/// URL
to exercise the SQLAlchemy backend.
"""

import sqlite3

import pytest

from rfc.harness_db import HAS_SQLALCHEMY, HarnessDatabase, _SQLiteHarnessBackend
from rfc.harness_models import (
    RESERVED_METRIC_KEYS,
    AgenticHarness,
    AgenticMetric,
    AgenticPlugin,
    AgenticSkill,
)

# Pre-#217 agentic_harnesses DDL: models a DB created before scenario_id /
# battery_run_id existed, to exercise the backfill migration path.
_OLD_HARNESSES_DDL = """
CREATE TABLE agentic_harnesses (
    session_id              TEXT PRIMARY KEY,
    tool_name               TEXT NOT NULL,
    tool_version            TEXT,
    model_id                TEXT,
    rfc_version             TEXT,
    branch                  TEXT,
    started_at              TEXT NOT NULL,
    ended_at                TEXT,
    outcome                 TEXT,
    replay_of_recording_id  TEXT
);
"""

NOW = "2026-05-09T00:00:00Z"


@pytest.fixture(params=["file_path", "sqlite_url"])
def harness_db(request, tmp_path):
    """Parametrised: SQLite via file_path AND via sqlite:/// URL.

    file_path -> _SQLiteHarnessBackend.
    sqlite:/// URL -> _SQLAlchemyHarnessBackend (skipped if sqlalchemy missing).
    """
    db_file = tmp_path / "harness.db"
    if request.param == "file_path":
        return HarnessDatabase(db_path=str(db_file))
    if not HAS_SQLALCHEMY:
        pytest.skip("sqlalchemy not installed (install with: uv sync --extra superset)")
    return HarnessDatabase(database_url=f"sqlite:///{db_file}")


class TestMissingDirectory:
    """sqlite3 fallback must not invent missing DB directories (#439).

    The SQLAlchemy backend fails when the parent directory of a
    sqlite:/// URL does not exist; the stdlib fallback silently created
    it, so `rfc harness start` never hit its skip-and-log path in
    environments without sqlalchemy.
    """

    def test_sqlite_url_fallback_fails_on_missing_dir(self, tmp_path, monkeypatch):
        import rfc.harness_db as harness_db_module

        monkeypatch.setattr(harness_db_module, "HAS_SQLALCHEMY", False)
        missing = tmp_path / "no" / "such" / "dir"
        with pytest.raises(sqlite3.OperationalError):
            HarnessDatabase(database_url=f"sqlite:///{missing / 'x.db'}")
        assert not missing.exists()

    def test_explicit_db_path_still_creates_dir(self, tmp_path):
        # Legacy fast path keeps its convenience behavior.
        db_file = tmp_path / "made" / "for" / "you" / "harness.db"
        HarnessDatabase(db_path=str(db_file))
        assert db_file.exists()


class TestSchema:
    def test_init_creates_tables(self, tmp_path):
        db_file = tmp_path / "harness.db"
        HarnessDatabase(db_path=str(db_file))
        with sqlite3.connect(str(db_file)) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert {
            "agentic_harnesses",
            "agentic_plugins",
            "agentic_skills",
            "agentic_metrics",
        }.issubset(tables)

    def test_init_is_idempotent(self, tmp_path):
        db_file = tmp_path / "harness.db"
        HarnessDatabase(db_path=str(db_file))
        HarnessDatabase(db_path=str(db_file))  # must not raise

    def test_foreign_keys_enabled(self, tmp_path):
        db_file = tmp_path / "harness.db"
        HarnessDatabase(db_path=str(db_file))
        with sqlite3.connect(str(db_file)) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            # Insert into child without parent should fail FK constraint.
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO agentic_plugins (id, session_id, plugin_name, recorded_at) "
                    "VALUES (?, ?, ?, ?)",
                    ("p1", "no-such-session", "robotframework-browser", NOW),
                )


class TestHarnessLifecycle:
    def test_save_and_get(self, harness_db):
        h = AgenticHarness(
            session_id="s1",
            tool_name="claude-code",
            started_at=NOW,
            tool_version="4.7",
            model_id="claude-opus-4-7",
        )
        sid = harness_db.save_harness(h)
        assert sid == "s1"
        fetched = harness_db.get_harness("s1")
        assert fetched is not None
        assert fetched.tool_name == "claude-code"
        assert fetched.tool_version == "4.7"
        assert fetched.outcome == ""  # not None - concrete default

    def test_get_harness_returns_none_if_missing(self, harness_db):
        assert harness_db.get_harness("nope") is None

    def test_end_harness_sets_outcome_and_ended_at(self, harness_db):
        harness_db.save_harness(
            AgenticHarness(session_id="s1", tool_name="claude-code", started_at=NOW)
        )
        harness_db.end_harness("s1", outcome="success", ended_at="2026-05-09T01:00:00Z")
        fetched = harness_db.get_harness("s1")
        assert fetched is not None
        assert fetched.outcome == "success"
        assert fetched.ended_at == "2026-05-09T01:00:00Z"

    def test_end_harness_raises_if_missing(self, harness_db):
        with pytest.raises(LookupError):
            harness_db.end_harness("nope", outcome="failed", ended_at=NOW)

    def test_save_and_get_with_spine_columns(self, harness_db):
        harness_db.save_harness(
            AgenticHarness(
                session_id="s-spine",
                tool_name="opencode",
                started_at=NOW,
                scenario_id="tier4_bug_fix",
                battery_run_id="battery-7",
            )
        )
        fetched = harness_db.get_harness("s-spine")
        assert fetched is not None
        assert fetched.scenario_id == "tier4_bug_fix"
        assert fetched.battery_run_id == "battery-7"

    def test_spine_columns_default_to_empty_string(self, harness_db):
        # Old-style writer that never sets the new fields: NULL -> "" sentinel.
        harness_db.save_harness(
            AgenticHarness(session_id="s-null", tool_name="claude-code", started_at=NOW)
        )
        fetched = harness_db.get_harness("s-null")
        assert fetched is not None
        assert fetched.scenario_id == ""
        assert fetched.battery_run_id == ""


class TestSnapshots:
    @pytest.fixture(autouse=True)
    def _seed_session(self, harness_db):
        # All snapshot tests need a parent harness row for FK validity.
        harness_db.save_harness(
            AgenticHarness(session_id="s1", tool_name="claude-code", started_at=NOW)
        )

    def test_save_plugins_assigns_uuid_when_id_blank(self, harness_db):
        ids = harness_db.save_plugins(
            [
                AgenticPlugin(
                    session_id="s1",
                    plugin_name="robotframework-browser",
                    recorded_at=NOW,
                ),
                AgenticPlugin(
                    session_id="s1", plugin_name="anthropic", recorded_at=NOW
                ),
            ]
        )
        assert all(len(i) == 32 for i in ids)  # uuid4().hex
        assert ids[0] != ids[1]

    def test_save_plugins_preserves_explicit_id(self, harness_db):
        ids = harness_db.save_plugins(
            [
                AgenticPlugin(
                    session_id="s1",
                    plugin_name="robotframework-browser",
                    recorded_at=NOW,
                    id="explicit-id-1",
                ),
            ]
        )
        assert ids == ["explicit-id-1"]

    def test_save_plugins_idempotent_on_session_plus_name(self, harness_db):
        # Insert twice with same (session_id, plugin_name) -> second wins via OR REPLACE.
        harness_db.save_plugins(
            [
                AgenticPlugin(
                    session_id="s1",
                    plugin_name="anthropic",
                    recorded_at=NOW,
                    semver="0.40.0",
                )
            ]
        )
        harness_db.save_plugins(
            [
                AgenticPlugin(
                    session_id="s1",
                    plugin_name="anthropic",
                    recorded_at=NOW,
                    semver="0.41.0",
                )
            ]
        )
        plugins = harness_db.get_plugins("s1")
        assert len(plugins) == 1
        assert plugins[0].semver == "0.41.0"

    def test_get_plugins_empty(self, harness_db):
        assert harness_db.get_plugins("s1") == []

    def test_save_skills_returns_ids_in_input_order(self, harness_db):
        ids = harness_db.save_skills(
            [
                AgenticSkill(
                    session_id="s1",
                    skill_path="robot/20__tier2/safety/safety.resource",
                    recorded_at=NOW,
                ),
                AgenticSkill(
                    session_id="s1",
                    skill_path="robot/20__tier2/math/math.resource",
                    recorded_at=NOW,
                ),
                AgenticSkill(
                    session_id="s1",
                    skill_path="robot/40__tier4/docker/bash/bash.resource",
                    recorded_at=NOW,
                ),
            ]
        )
        assert len(ids) == 3
        # Re-fetch by id to verify positional alignment.
        skills = harness_db.get_skills("s1")
        skills_by_path = {s.skill_path: s.id for s in skills}
        assert skills_by_path["robot/20__tier2/safety/safety.resource"] == ids[0]
        assert skills_by_path["robot/20__tier2/math/math.resource"] == ids[1]
        assert skills_by_path["robot/40__tier4/docker/bash/bash.resource"] == ids[2]


class TestMetrics:
    @pytest.fixture(autouse=True)
    def _seed_session(self, harness_db):
        harness_db.save_harness(
            AgenticHarness(session_id="s1", tool_name="claude-code", started_at=NOW)
        )

    def test_save_metric_session_only(self, harness_db):
        mid = harness_db.save_metric(
            AgenticMetric(
                session_id="s1",
                metric_key="tokens_in",
                recorded_at=NOW,
                metric_value=1234.0,
            )
        )
        assert len(mid) == 32  # uuid4().hex
        metrics = harness_db.get_metrics("s1")
        assert len(metrics) == 1
        assert metrics[0].metric_key == "tokens_in"
        assert metrics[0].metric_value == 1234.0
        assert metrics[0].test_run_id == -1  # NULL -> sentinel
        assert metrics[0].test_result_id == -1

    def test_save_metric_with_test_run_id(self, harness_db):
        harness_db.save_metric(
            AgenticMetric(
                session_id="s1",
                metric_key="latency_ms",
                recorded_at=NOW,
                metric_value=42.5,
                test_run_id=7,
            )
        )
        m = harness_db.get_metrics("s1")[0]
        assert m.test_run_id == 7
        assert m.test_result_id == -1

    def test_save_metrics_bulk_returns_ids_in_order(self, harness_db):
        ids = harness_db.save_metrics(
            [
                AgenticMetric(
                    session_id="s1",
                    metric_key="tokens_in",
                    recorded_at=NOW,
                    metric_value=100.0,
                ),
                AgenticMetric(
                    session_id="s1",
                    metric_key="tokens_out",
                    recorded_at=NOW,
                    metric_value=50.0,
                ),
            ]
        )
        assert len(ids) == 2
        assert ids[0] != ids[1]

    def test_get_metrics_filtered_by_key(self, harness_db):
        harness_db.save_metrics(
            [
                AgenticMetric(
                    session_id="s1",
                    metric_key="tokens_in",
                    recorded_at=NOW,
                    metric_value=100.0,
                ),
                AgenticMetric(
                    session_id="s1",
                    metric_key="tokens_out",
                    recorded_at=NOW,
                    metric_value=50.0,
                ),
                AgenticMetric(
                    session_id="s1",
                    metric_key="tokens_in",
                    recorded_at=NOW,
                    metric_value=200.0,
                ),
            ]
        )
        in_only = harness_db.get_metrics("s1", metric_key="tokens_in")
        assert len(in_only) == 2
        assert {m.metric_value for m in in_only} == {100.0, 200.0}

    def test_reserved_metric_keys_round_trip(self, harness_db):
        # Every reserved key is a valid agentic_metrics.metric_key and reads back.
        harness_db.save_metrics(
            [
                AgenticMetric(
                    session_id="s1", metric_key=key, recorded_at=NOW, metric_value=1.0
                )
                for key in RESERVED_METRIC_KEYS
            ]
        )
        stored = {m.metric_key for m in harness_db.get_metrics("s1")}
        assert stored == set(RESERVED_METRIC_KEYS)


class TestCascades:
    def test_delete_harness_cascades_to_children(self, harness_db, tmp_path):
        harness_db.save_harness(
            AgenticHarness(session_id="s1", tool_name="claude-code", started_at=NOW)
        )
        harness_db.save_plugins(
            [AgenticPlugin(session_id="s1", plugin_name="anthropic", recorded_at=NOW)]
        )
        harness_db.save_skills(
            [
                AgenticSkill(
                    session_id="s1",
                    skill_path="robot/20__tier2/safety/safety.resource",
                    recorded_at=NOW,
                )
            ]
        )
        harness_db.save_metric(
            AgenticMetric(
                session_id="s1",
                metric_key="tokens_in",
                recorded_at=NOW,
                metric_value=100.0,
            )
        )
        # Delete via direct SQL (no public delete API). Both backends route
        # through their own DB primitives so the FK + cascade is exercised
        # under the same enforcement rules the public API uses.
        backend = harness_db._backend  # type: ignore[attr-defined]
        if isinstance(backend, _SQLiteHarnessBackend):
            with sqlite3.connect(backend.db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute(
                    "DELETE FROM agentic_harnesses WHERE session_id = ?", ("s1",)
                )
        else:
            with backend.engine.begin() as conn:
                conn.execute(
                    backend._harnesses.delete().where(
                        backend._harnesses.c.session_id == "s1"
                    )
                )
        assert harness_db.get_plugins("s1") == []
        assert harness_db.get_skills("s1") == []
        assert harness_db.get_metrics("s1") == []

    def test_orphan_child_insert_rejected(self, harness_db):
        """Inserting a plugin/skill/metric for an unknown session_id must fail."""
        with pytest.raises(Exception):
            harness_db.save_plugins(
                [
                    AgenticPlugin(
                        session_id="no-such-session",
                        plugin_name="anthropic",
                        recorded_at=NOW,
                    )
                ]
            )
        with pytest.raises(Exception):
            harness_db.save_skills(
                [
                    AgenticSkill(
                        session_id="no-such-session",
                        skill_path="robot/20__tier2/safety/safety.resource",
                        recorded_at=NOW,
                    )
                ]
            )
        with pytest.raises(Exception):
            harness_db.save_metric(
                AgenticMetric(
                    session_id="no-such-session",
                    metric_key="tokens_in",
                    recorded_at=NOW,
                    metric_value=100.0,
                )
            )


class TestIntrospection:
    def test_get_version_returns_something(self, harness_db):
        v = harness_db.get_version()
        # SQLite backend returns sqlite version (e.g., '3.45.1');
        # SQLAlchemy backend returns dialect name (e.g., 'sqlite' or
        # 'postgresql'). Both backends must return a non-empty string.
        assert v

    def test_get_table_row_count(self, harness_db):
        assert harness_db.get_table_row_count("agentic_harnesses") == 0
        harness_db.save_harness(
            AgenticHarness(session_id="s1", tool_name="claude-code", started_at=NOW)
        )
        assert harness_db.get_table_row_count("agentic_harnesses") == 1

    def test_get_table_row_count_rejects_unknown_table(self, harness_db):
        with pytest.raises(ValueError):
            harness_db.get_table_row_count("test_runs")  # not a harness table


class TestSpineColumnMigration:
    """#217: scenario_id/battery_run_id backfilled onto a pre-#217 DB."""

    def _seed_old_db(self, db_file) -> None:
        with sqlite3.connect(str(db_file)) as conn:
            conn.executescript(_OLD_HARNESSES_DDL)
            conn.execute(
                "INSERT INTO agentic_harnesses "
                "(session_id, tool_name, started_at) VALUES (?, ?, ?)",
                ("old-row", "claude-code", NOW),
            )

    def test_columns_absent_before_migration(self, tmp_path):
        # Guard: the fixture really models a pre-#217 schema.
        db_file = tmp_path / "old.db"
        self._seed_old_db(db_file)
        with sqlite3.connect(str(db_file)) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(agentic_harnesses)")}
        assert "scenario_id" not in cols
        assert "battery_run_id" not in cols

    def test_sqlite_native_migration_adds_columns(self, tmp_path):
        db_file = tmp_path / "old.db"
        self._seed_old_db(db_file)
        db = HarnessDatabase(db_path=str(db_file))
        with sqlite3.connect(str(db_file)) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(agentic_harnesses)")}
        assert {"scenario_id", "battery_run_id"}.issubset(cols)
        # Pre-existing row is intact and reads the new fields as "" (NULL).
        old = db.get_harness("old-row")
        assert old is not None
        assert old.tool_name == "claude-code"
        assert old.scenario_id == ""
        assert old.battery_run_id == ""
        # A new row round-trips the new fields on the upgraded DB.
        db.save_harness(
            AgenticHarness(
                session_id="new-row",
                tool_name="opencode",
                started_at=NOW,
                scenario_id="tier4_regression_guard",
                battery_run_id="battery-9",
            )
        )
        new = db.get_harness("new-row")
        assert new is not None
        assert new.scenario_id == "tier4_regression_guard"
        assert new.battery_run_id == "battery-9"

    def test_sqlite_native_migration_is_idempotent(self, tmp_path):
        db_file = tmp_path / "old.db"
        self._seed_old_db(db_file)
        HarnessDatabase(db_path=str(db_file))
        HarnessDatabase(db_path=str(db_file))  # second open must not raise

    @pytest.mark.skipif(
        not HAS_SQLALCHEMY,
        reason="sqlalchemy not installed (uv sync --extra superset)",
    )
    def test_sqlalchemy_migration_adds_columns(self, tmp_path):
        db_file = tmp_path / "old.db"
        self._seed_old_db(db_file)
        # SQLAlchemy backend over an existing pre-#217 sqlite file: create_all
        # leaves the existing table alone, so _run_migrations must ALTER-add.
        db = HarnessDatabase(database_url=f"sqlite:///{db_file}")
        old = db.get_harness("old-row")
        assert old is not None
        assert old.scenario_id == ""
        assert old.battery_run_id == ""
        db.save_harness(
            AgenticHarness(
                session_id="new-row",
                tool_name="opencode",
                started_at=NOW,
                scenario_id="tier4_bug_fix",
                battery_run_id="battery-1",
            )
        )
        new = db.get_harness("new-row")
        assert new is not None
        assert new.scenario_id == "tier4_bug_fix"
        assert new.battery_run_id == "battery-1"

    @pytest.mark.skipif(
        not HAS_SQLALCHEMY,
        reason="sqlalchemy not installed (uv sync --extra superset)",
    )
    def test_sqlalchemy_migration_is_idempotent(self, tmp_path):
        db_file = tmp_path / "old.db"
        self._seed_old_db(db_file)
        HarnessDatabase(database_url=f"sqlite:///{db_file}")
        HarnessDatabase(database_url=f"sqlite:///{db_file}")  # must not raise
