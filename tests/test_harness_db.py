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

# Pre-#242 agentic_harnesses DDL: has the #217 spine columns but NOT the
# RFC-008 A3 runtime-provenance columns, to exercise the A3 backfill migration
# on a DB created after #217 but before #242.
_PRE_A3_HARNESSES_DDL = """
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
    replay_of_recording_id  TEXT,
    scenario_id             TEXT,
    battery_run_id          TEXT
);
"""

# The #242 provenance column set, named once for the migration assertions.
_A3_PROVENANCE_COLUMNS = {
    "model_digest",
    "prompt_id",
    "prompt_hash",
    "grader_version",
    "params_json",
}

# Pre-#277 agentic_harnesses DDL: a DB carrying the #217 spine columns AND the
# #242 provenance set, but not yet repeat_idx — to exercise the #277 backfill.
_PRE_277_HARNESSES_DDL = """
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
    replay_of_recording_id  TEXT,
    scenario_id             TEXT,
    battery_run_id          TEXT,
    model_digest            TEXT,
    prompt_id               TEXT,
    prompt_hash             TEXT,
    grader_version          TEXT,
    params_json             TEXT
);
"""

# Out-of-order / partial migration history (test-design, #277): a DB that already
# carries repeat_idx (physically BEFORE the provenance set) but is MISSING two of
# #292's provenance columns (model_digest, prompt_id). Exercises that the
# per-statement backfill adds only the missing columns AND that reads stay
# index-aligned despite the non-canonical physical column order -- because both
# backends read by explicit column list / Table order, never SELECT *.
_OUT_OF_ORDER_HARNESSES_DDL = """
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
    replay_of_recording_id  TEXT,
    scenario_id             TEXT,
    battery_run_id          TEXT,
    repeat_idx              INTEGER,
    prompt_hash             TEXT,
    grader_version          TEXT,
    params_json             TEXT
);
"""

# Pre-#350 agentic_harnesses DDL: the full #217 + #242 + #277 column set, but not
# yet verified_local — to exercise the #350 backfill (the persisted tier verdict)
# on a DB created after #277 but before #350.
_PRE_350_HARNESSES_DDL = """
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
    replay_of_recording_id  TEXT,
    scenario_id             TEXT,
    battery_run_id          TEXT,
    model_digest            TEXT,
    prompt_id               TEXT,
    prompt_hash             TEXT,
    grader_version          TEXT,
    params_json             TEXT,
    repeat_idx              INTEGER
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

    def test_save_and_get_with_provenance_columns(self, harness_db):
        # RFC-008 A3 (#242): the runtime-provenance coordinate round-trips.
        harness_db.save_harness(
            AgenticHarness(
                session_id="s-prov",
                tool_name="replay",
                started_at=NOW,
                model_digest="sha256:abc123",
                prompt_id="grader.default_judge",
                prompt_hash="deadbeef",
                grader_version="judge-3",
                params_json='{"seed": 7, "temperature": 0.0}',
            )
        )
        fetched = harness_db.get_harness("s-prov")
        assert fetched is not None
        assert fetched.model_digest == "sha256:abc123"
        assert fetched.prompt_id == "grader.default_judge"
        assert fetched.prompt_hash == "deadbeef"
        assert fetched.grader_version == "judge-3"
        assert fetched.params_json == '{"seed": 7, "temperature": 0.0}'

    def test_provenance_columns_default_to_empty_string(self, harness_db):
        # An existing writer that never sets the A3 fields: NULL -> "" sentinel,
        # so old writers are unchanged (backward-compatible, columns nullable).
        harness_db.save_harness(
            AgenticHarness(
                session_id="s-prov-null", tool_name="claude-code", started_at=NOW
            )
        )
        fetched = harness_db.get_harness("s-prov-null")
        assert fetched is not None
        assert fetched.model_digest == ""
        assert fetched.prompt_id == ""
        assert fetched.prompt_hash == ""
        assert fetched.grader_version == ""
        assert fetched.params_json == ""

    def test_save_and_get_with_repeat_idx(self, harness_db):
        # #277: repeat_idx round-trips on the spine so S4 pairs on the stored key.
        harness_db.save_harness(
            AgenticHarness(
                session_id="s-rep",
                tool_name="opencode",
                started_at=NOW,
                scenario_id="tier4_bug_fix",
                battery_run_id="battery-7",
                repeat_idx=3,
            )
        )
        fetched = harness_db.get_harness("s-rep")
        assert fetched is not None
        assert fetched.repeat_idx == 3

    def test_repeat_idx_zero_persists_as_zero(self, harness_db):
        # The falsy-zero guard: repeat 0 is a real index, NOT "unset". It must
        # round-trip as 0 (a `harness.repeat_idx or None` write would corrupt it
        # to NULL -> -1 and silently drop the first repeat from every pairing).
        harness_db.save_harness(
            AgenticHarness(
                session_id="s-rep0",
                tool_name="opencode",
                started_at=NOW,
                repeat_idx=0,
            )
        )
        fetched = harness_db.get_harness("s-rep0")
        assert fetched is not None
        assert fetched.repeat_idx == 0

    def test_repeat_idx_defaults_to_sentinel(self, harness_db):
        # A non-battery writer that never sets repeat_idx: NULL -> -1 sentinel,
        # so those rows are distinguishable from a genuine repeat 0.
        harness_db.save_harness(
            AgenticHarness(session_id="s-rep-null", tool_name="replay", started_at=NOW)
        )
        fetched = harness_db.get_harness("s-rep-null")
        assert fetched is not None
        assert fetched.repeat_idx == -1

    def test_save_and_get_with_verified_local(self, harness_db):
        # #350: the persisted local-resolution verdict (1 == Tier A) round-trips
        # on the spine so the scoreboard view reads the token's verdict at read
        # time, not a tool_name name-coincidence.
        harness_db.save_harness(
            AgenticHarness(
                session_id="s-vl",
                tool_name="opencode",
                started_at=NOW,
                scenario_id="tier4_bug_fix",
                battery_run_id="battery-7",
                verified_local=1,
            )
        )
        fetched = harness_db.get_harness("s-vl")
        assert fetched is not None
        assert fetched.verified_local == 1

    def test_verified_local_zero_persists_as_zero(self, harness_db):
        # The falsy-zero guard: 0 is a real verdict (Tier B / no token), NOT
        # "unset". It must round-trip as 0 (a `harness.verified_local or None`
        # write would corrupt it to NULL -> -1, and a NULL reads fail-closed to
        # Tier B in the view anyway — but the stored 0 is the AFFIRMATIVE Tier-B
        # verdict, distinct from an unclassified legacy row).
        harness_db.save_harness(
            AgenticHarness(
                session_id="s-vl0",
                tool_name="claude-code",
                started_at=NOW,
                verified_local=0,
            )
        )
        fetched = harness_db.get_harness("s-vl0")
        assert fetched is not None
        assert fetched.verified_local == 0

    def test_verified_local_defaults_to_sentinel(self, harness_db):
        # A non-comparison writer that never sets verified_local: NULL -> -1
        # sentinel, distinguishable from an affirmative Tier-B 0, and read
        # fail-closed to Tier B by the scoreboard view.
        harness_db.save_harness(
            AgenticHarness(session_id="s-vl-null", tool_name="replay", started_at=NOW)
        )
        fetched = harness_db.get_harness("s-vl-null")
        assert fetched is not None
        assert fetched.verified_local == -1


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


class TestProvenanceColumnMigration:
    """#242 (RFC-008 A3): provenance columns backfilled onto a pre-#242 DB.

    Mirrors TestSpineColumnMigration (#217) exactly — the established backfill
    pattern — across a fresh, a migrated, and a half-migrated DB on both backends.
    """

    def _seed_pre_a3_db(self, db_file) -> None:
        with sqlite3.connect(str(db_file)) as conn:
            conn.executescript(_PRE_A3_HARNESSES_DDL)
            conn.execute(
                "INSERT INTO agentic_harnesses "
                "(session_id, tool_name, started_at, scenario_id) VALUES (?, ?, ?, ?)",
                ("pre-a3-row", "opencode", NOW, "tier4_bug_fix"),
            )

    def test_columns_absent_before_migration(self, tmp_path):
        # Guard: the fixture really models a pre-#242 schema (has #217 cols, not A3).
        db_file = tmp_path / "prea3.db"
        self._seed_pre_a3_db(db_file)
        with sqlite3.connect(str(db_file)) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(agentic_harnesses)")}
        assert {"scenario_id", "battery_run_id"}.issubset(cols)  # #217 present
        assert _A3_PROVENANCE_COLUMNS.isdisjoint(cols)  # A3 absent

    def test_sqlite_native_migration_adds_columns(self, tmp_path):
        db_file = tmp_path / "prea3.db"
        self._seed_pre_a3_db(db_file)
        db = HarnessDatabase(db_path=str(db_file))
        with sqlite3.connect(str(db_file)) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(agentic_harnesses)")}
        assert _A3_PROVENANCE_COLUMNS.issubset(cols)
        # Pre-existing row intact: #217 column preserved, new fields read as "".
        old = db.get_harness("pre-a3-row")
        assert old is not None
        assert old.scenario_id == "tier4_bug_fix"
        assert old.model_digest == ""
        assert old.prompt_hash == ""
        assert old.params_json == ""
        # A new row round-trips the provenance coordinate on the upgraded DB.
        db.save_harness(
            AgenticHarness(
                session_id="new-a3",
                tool_name="replay",
                started_at=NOW,
                model_digest="dg",
                prompt_id="grader.default_judge",
                prompt_hash="hh",
                grader_version="1",
                params_json='{"seed": 3}',
            )
        )
        new = db.get_harness("new-a3")
        assert new is not None
        assert new.model_digest == "dg"
        assert new.prompt_hash == "hh"
        assert new.params_json == '{"seed": 3}'

    def test_sqlite_native_migration_is_idempotent(self, tmp_path):
        db_file = tmp_path / "prea3.db"
        self._seed_pre_a3_db(db_file)
        HarnessDatabase(db_path=str(db_file))
        HarnessDatabase(db_path=str(db_file))  # second open must not raise

    def test_half_migrated_db_backfills_only_missing_columns(self, tmp_path):
        """#225 precedent: a DB with SOME A3 columns already present adds only the
        rest. Per-statement idempotent migrations, not all-or-nothing — the two
        pre-added ALTERs raise 'duplicate column' (caught) and the other three land.
        """
        db_file = tmp_path / "half.db"
        self._seed_pre_a3_db(db_file)
        with sqlite3.connect(str(db_file)) as conn:
            conn.execute("ALTER TABLE agentic_harnesses ADD COLUMN model_digest TEXT")
            conn.execute("ALTER TABLE agentic_harnesses ADD COLUMN prompt_id TEXT")
        db = HarnessDatabase(db_path=str(db_file))  # must not raise on the dup ALTERs
        with sqlite3.connect(str(db_file)) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(agentic_harnesses)")}
        assert _A3_PROVENANCE_COLUMNS.issubset(cols)
        db.save_harness(
            AgenticHarness(
                session_id="half-new",
                tool_name="replay",
                started_at=NOW,
                model_digest="dg2",
                prompt_hash="hh2",
                grader_version="1",
                params_json="{}",
            )
        )
        new = db.get_harness("half-new")
        assert new is not None
        assert new.model_digest == "dg2"
        assert new.prompt_hash == "hh2"
        assert new.grader_version == "1"

    @pytest.mark.skipif(
        not HAS_SQLALCHEMY,
        reason="sqlalchemy not installed (uv sync --extra superset)",
    )
    def test_sqlalchemy_migration_adds_columns(self, tmp_path):
        db_file = tmp_path / "prea3.db"
        self._seed_pre_a3_db(db_file)
        # create_all leaves the existing pre-#242 table alone, so _run_migrations
        # must ALTER-add the provenance columns.
        db = HarnessDatabase(database_url=f"sqlite:///{db_file}")
        old = db.get_harness("pre-a3-row")
        assert old is not None
        assert old.scenario_id == "tier4_bug_fix"
        assert old.model_digest == ""
        db.save_harness(
            AgenticHarness(
                session_id="new-a3",
                tool_name="replay",
                started_at=NOW,
                prompt_id="grader.default_judge",
                prompt_hash="hh",
                params_json='{"top_p": 0.9}',
            )
        )
        new = db.get_harness("new-a3")
        assert new is not None
        assert new.prompt_id == "grader.default_judge"
        assert new.prompt_hash == "hh"
        assert new.params_json == '{"top_p": 0.9}'

    @pytest.mark.skipif(
        not HAS_SQLALCHEMY,
        reason="sqlalchemy not installed (uv sync --extra superset)",
    )
    def test_sqlalchemy_migration_is_idempotent(self, tmp_path):
        db_file = tmp_path / "prea3.db"
        self._seed_pre_a3_db(db_file)
        HarnessDatabase(database_url=f"sqlite:///{db_file}")
        HarnessDatabase(database_url=f"sqlite:///{db_file}")  # must not raise


class TestRepeatIdxColumnMigration:
    """#277: repeat_idx backfilled onto a pre-#277 DB (has #217 + #242 columns).

    Mirrors TestSpineColumnMigration (#217) / TestProvenanceColumnMigration (#242):
    the established additive backfill across a fresh, a migrated, and a
    half-migrated DB on both backends. Sequenced AFTER the #242 provenance set so
    the positional index (17) never collides with theirs (12–16).
    """

    def _seed_pre_277_db(self, db_file) -> None:
        with sqlite3.connect(str(db_file)) as conn:
            conn.executescript(_PRE_277_HARNESSES_DDL)
            conn.execute(
                "INSERT INTO agentic_harnesses "
                "(session_id, tool_name, started_at, scenario_id) VALUES (?, ?, ?, ?)",
                ("pre-277-row", "opencode", NOW, "tier4_bug_fix"),
            )

    def test_column_absent_before_migration(self, tmp_path):
        # Guard: the fixture really models a pre-#277 schema (A3 present, not #277).
        db_file = tmp_path / "pre277.db"
        self._seed_pre_277_db(db_file)
        with sqlite3.connect(str(db_file)) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(agentic_harnesses)")}
        assert _A3_PROVENANCE_COLUMNS.issubset(cols)  # #242 present
        assert "repeat_idx" not in cols  # #277 absent

    def test_sqlite_native_migration_adds_column(self, tmp_path):
        db_file = tmp_path / "pre277.db"
        self._seed_pre_277_db(db_file)
        db = HarnessDatabase(db_path=str(db_file))
        with sqlite3.connect(str(db_file)) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(agentic_harnesses)")}
        assert "repeat_idx" in cols
        # Pre-existing row intact: reads repeat_idx as the -1 sentinel (NULL).
        old = db.get_harness("pre-277-row")
        assert old is not None
        assert old.scenario_id == "tier4_bug_fix"
        assert old.repeat_idx == -1
        # A new row round-trips repeat_idx on the upgraded DB, incl. the 0 index.
        db.save_harness(
            AgenticHarness(
                session_id="new-277",
                tool_name="opencode",
                started_at=NOW,
                scenario_id="tier4_regression_guard",
                battery_run_id="battery-9",
                repeat_idx=0,
            )
        )
        new = db.get_harness("new-277")
        assert new is not None
        assert new.repeat_idx == 0

    def test_sqlite_native_migration_is_idempotent(self, tmp_path):
        db_file = tmp_path / "pre277.db"
        self._seed_pre_277_db(db_file)
        HarnessDatabase(db_path=str(db_file))
        HarnessDatabase(db_path=str(db_file))  # second open must not raise

    @pytest.mark.skipif(
        not HAS_SQLALCHEMY,
        reason="sqlalchemy not installed (uv sync --extra superset)",
    )
    def test_sqlalchemy_migration_adds_column(self, tmp_path):
        db_file = tmp_path / "pre277.db"
        self._seed_pre_277_db(db_file)
        # create_all leaves the existing pre-#277 table alone, so _run_migrations
        # must ALTER-add repeat_idx.
        db = HarnessDatabase(database_url=f"sqlite:///{db_file}")
        old = db.get_harness("pre-277-row")
        assert old is not None
        assert old.repeat_idx == -1
        db.save_harness(
            AgenticHarness(
                session_id="new-277",
                tool_name="opencode",
                started_at=NOW,
                scenario_id="tier4_bug_fix",
                battery_run_id="battery-1",
                repeat_idx=4,
            )
        )
        new = db.get_harness("new-277")
        assert new is not None
        assert new.repeat_idx == 4

    @pytest.mark.skipif(
        not HAS_SQLALCHEMY,
        reason="sqlalchemy not installed (uv sync --extra superset)",
    )
    def test_sqlalchemy_migration_is_idempotent(self, tmp_path):
        db_file = tmp_path / "pre277.db"
        self._seed_pre_277_db(db_file)
        HarnessDatabase(database_url=f"sqlite:///{db_file}")
        HarnessDatabase(database_url=f"sqlite:///{db_file}")  # must not raise

    def _seed_out_of_order_db(self, db_file) -> None:
        with sqlite3.connect(str(db_file)) as conn:
            conn.executescript(_OUT_OF_ORDER_HARNESSES_DDL)
            conn.execute(
                "INSERT INTO agentic_harnesses "
                "(session_id, tool_name, started_at, scenario_id, repeat_idx) "
                "VALUES (?, ?, ?, ?, ?)",
                ("ooo-row", "opencode", NOW, "tier4_bug_fix", 2),
            )

    @pytest.mark.parametrize("use_url", [False, True])
    def test_out_of_order_history_backfills_and_reads_aligned(self, tmp_path, use_url):
        # test-design (#277): a DB with repeat_idx present (physically out of
        # canonical order) but missing two provenance columns. The per-statement
        # backfill must add ONLY the missing provenance columns (skipping the
        # already-present repeat_idx), and every read must stay index-aligned
        # despite the non-canonical physical order -- on BOTH backends.
        if use_url and not HAS_SQLALCHEMY:
            pytest.skip("sqlalchemy not installed")
        db_file = tmp_path / "ooo.db"
        self._seed_out_of_order_db(db_file)
        db = (
            HarnessDatabase(database_url=f"sqlite:///{db_file}")
            if use_url
            else HarnessDatabase(db_path=str(db_file))
        )
        with sqlite3.connect(str(db_file)) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(agentic_harnesses)")}
        assert _A3_PROVENANCE_COLUMNS.issubset(cols)  # missing provenance backfilled
        assert "repeat_idx" in cols
        # Pre-existing out-of-order row survived, and its stored repeat_idx (2) and
        # scenario_id read back correctly even though repeat_idx sits at a
        # non-canonical physical position -- explicit-column reads are immune.
        old = db.get_harness("ooo-row")
        assert old is not None
        assert old.scenario_id == "tier4_bug_fix"
        assert old.repeat_idx == 2
        # A fresh row round-trips a DISTINCT repeat_idx alongside provenance
        # sentinels: if any column read were misaligned, one of these would be wrong.
        db.save_harness(
            AgenticHarness(
                session_id="ooo-new",
                tool_name="opencode",
                started_at=NOW,
                scenario_id="tier4_regression_guard",
                battery_run_id="batt-ooo",
                repeat_idx=0,
                model_digest="DG_SENTINEL",
                prompt_id="PID_SENTINEL",
                params_json="PJ_SENTINEL",
            )
        )
        new = db.get_harness("ooo-new")
        assert new is not None
        assert new.repeat_idx == 0  # a genuine 0, not corrupted to the -1 sentinel
        assert new.model_digest == "DG_SENTINEL"
        assert new.prompt_id == "PID_SENTINEL"
        assert new.params_json == "PJ_SENTINEL"


class TestVerifiedLocalColumnMigration:
    """#350: verified_local backfilled onto a pre-#350 DB (has #217+#242+#277).

    Mirrors TestSpineColumnMigration (#217) / TestProvenanceColumnMigration (#242)
    / TestRepeatIdxColumnMigration (#277): the established additive backfill across
    a fresh, a migrated, and an idempotent re-open on both backends. Sequenced
    AFTER repeat_idx so the positional index (18) never collides. No data rewrite:
    existing rows keep NULL (read fail-closed to Tier B).
    """

    def _seed_pre_350_db(self, db_file) -> None:
        with sqlite3.connect(str(db_file)) as conn:
            conn.executescript(_PRE_350_HARNESSES_DDL)
            conn.execute(
                "INSERT INTO agentic_harnesses "
                "(session_id, tool_name, started_at, scenario_id, repeat_idx) "
                "VALUES (?, ?, ?, ?, ?)",
                ("pre-350-row", "opencode", NOW, "tier4_bug_fix", 0),
            )

    def test_column_absent_before_migration(self, tmp_path):
        # Guard: the fixture really models a pre-#350 schema (#277 present, not #350).
        db_file = tmp_path / "pre350.db"
        self._seed_pre_350_db(db_file)
        with sqlite3.connect(str(db_file)) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(agentic_harnesses)")}
        assert "repeat_idx" in cols  # #277 present
        assert "verified_local" not in cols  # #350 absent

    def test_sqlite_native_migration_adds_column(self, tmp_path):
        db_file = tmp_path / "pre350.db"
        self._seed_pre_350_db(db_file)
        db = HarnessDatabase(db_path=str(db_file))
        with sqlite3.connect(str(db_file)) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(agentic_harnesses)")}
        assert "verified_local" in cols
        # Pre-existing row intact and NEVER rewritten: reads the -1 sentinel (NULL),
        # which the scoreboard view treats fail-closed as Tier B.
        old = db.get_harness("pre-350-row")
        assert old is not None
        assert old.scenario_id == "tier4_bug_fix"
        assert old.verified_local == -1
        # A new row round-trips the verdict on the upgraded DB, incl. the 0 (Tier B).
        db.save_harness(
            AgenticHarness(
                session_id="new-350-a",
                tool_name="opencode",
                started_at=NOW,
                scenario_id="tier4_regression_guard",
                battery_run_id="battery-9",
                verified_local=1,
            )
        )
        db.save_harness(
            AgenticHarness(
                session_id="new-350-b",
                tool_name="claude-code",
                started_at=NOW,
                scenario_id="tier4_regression_guard",
                battery_run_id="battery-9",
                verified_local=0,
            )
        )
        assert db.get_harness("new-350-a").verified_local == 1
        assert db.get_harness("new-350-b").verified_local == 0

    def test_sqlite_native_migration_is_idempotent(self, tmp_path):
        db_file = tmp_path / "pre350.db"
        self._seed_pre_350_db(db_file)
        HarnessDatabase(db_path=str(db_file))
        HarnessDatabase(db_path=str(db_file))  # second open must not raise

    @pytest.mark.skipif(
        not HAS_SQLALCHEMY,
        reason="sqlalchemy not installed (uv sync --extra superset)",
    )
    def test_sqlalchemy_migration_adds_column(self, tmp_path):
        db_file = tmp_path / "pre350.db"
        self._seed_pre_350_db(db_file)
        # create_all leaves the existing pre-#350 table alone, so _run_migrations
        # must ALTER-add verified_local.
        db = HarnessDatabase(database_url=f"sqlite:///{db_file}")
        old = db.get_harness("pre-350-row")
        assert old is not None
        assert old.verified_local == -1
        db.save_harness(
            AgenticHarness(
                session_id="new-350",
                tool_name="opencode",
                started_at=NOW,
                scenario_id="tier4_bug_fix",
                battery_run_id="battery-1",
                verified_local=1,
            )
        )
        new = db.get_harness("new-350")
        assert new is not None
        assert new.verified_local == 1

    @pytest.mark.skipif(
        not HAS_SQLALCHEMY,
        reason="sqlalchemy not installed (uv sync --extra superset)",
    )
    def test_sqlalchemy_migration_is_idempotent(self, tmp_path):
        db_file = tmp_path / "pre350.db"
        self._seed_pre_350_db(db_file)
        HarnessDatabase(database_url=f"sqlite:///{db_file}")
        HarnessDatabase(database_url=f"sqlite:///{db_file}")  # must not raise
