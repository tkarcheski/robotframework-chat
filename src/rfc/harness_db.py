"""HarnessDatabase: schema spine for the Agentic Stack Tracker.

Mirrors the shape of src/rfc/test_database.py. SQLite is always
available; SQLAlchemy is gated behind HAS_SQLALCHEMY (set by the
import guard) so callers can use HarnessDatabase against a SQLite
file even if the superset extra is not installed.
"""

from __future__ import annotations

import abc
import dataclasses
import logging
import os
import sqlite3
import uuid
from typing import Any, Optional, Sequence

from .harness_models import (
    HITL_KINDS,
    HITL_STATUSES,
    AgenticDecision,
    AgenticHarness,
    AgenticMetric,
    AgenticPlugin,
    AgenticSkill,
    DialogRecording,
    DialogTurn,
    HitlInteraction,
)

logger = logging.getLogger(__name__)

try:
    import sqlalchemy as _sqlalchemy_check  # type: ignore[import-not-found]  # noqa: F401

    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS agentic_harnesses (
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
CREATE INDEX IF NOT EXISTS idx_harnesses_tool ON agentic_harnesses(tool_name);

CREATE TABLE IF NOT EXISTS agentic_plugins (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    plugin_name     TEXT NOT NULL,
    semver          TEXT,
    source          TEXT,
    recorded_at     TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES agentic_harnesses(session_id) ON DELETE CASCADE,
    UNIQUE (session_id, plugin_name)
);
CREATE INDEX IF NOT EXISTS idx_plugins_session ON agentic_plugins(session_id);

CREATE TABLE IF NOT EXISTS agentic_skills (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    skill_path      TEXT NOT NULL,
    git_sha         TEXT,
    skill_name      TEXT,
    recorded_at     TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES agentic_harnesses(session_id) ON DELETE CASCADE,
    UNIQUE (session_id, skill_path)
);
CREATE INDEX IF NOT EXISTS idx_skills_session ON agentic_skills(session_id);

CREATE TABLE IF NOT EXISTS agentic_metrics (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    test_run_id     INTEGER,
    test_result_id  INTEGER,
    metric_key      TEXT NOT NULL,
    metric_value    REAL,
    recorded_at     TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES agentic_harnesses(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_metrics_session ON agentic_metrics(session_id);
CREATE INDEX IF NOT EXISTS idx_metrics_key     ON agentic_metrics(metric_key);
CREATE INDEX IF NOT EXISTS idx_metrics_run     ON agentic_metrics(test_run_id);

CREATE TABLE IF NOT EXISTS agentic_decisions (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    test_name       TEXT,
    hook_event      TEXT NOT NULL,
    prompt_model    TEXT NOT NULL,
    prompt_text     TEXT NOT NULL,
    response_text   TEXT,
    proposed_action TEXT,
    applied         INTEGER NOT NULL,
    tokens_used     INTEGER,
    recorded_at     TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES agentic_harnesses(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_decisions_session ON agentic_decisions(session_id);
CREATE INDEX IF NOT EXISTS idx_decisions_action  ON agentic_decisions(proposed_action);

CREATE TABLE IF NOT EXISTS dialog_recordings (
    id              TEXT PRIMARY KEY,
    session_id      TEXT,
    source_type     TEXT NOT NULL,
    tool_name       TEXT,
    tool_version    TEXT,
    model_id        TEXT,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    metadata_json   TEXT,
    FOREIGN KEY (session_id) REFERENCES agentic_harnesses(session_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS dialog_turns (
    id                  TEXT PRIMARY KEY,
    recording_id        TEXT NOT NULL,
    turn_number         INTEGER NOT NULL,
    role                TEXT NOT NULL,
    content             TEXT,
    tool_calls_json     TEXT,
    tool_results_json   TEXT,
    timestamp           TEXT NOT NULL,
    prompt_tokens       INTEGER,
    completion_tokens   INTEGER,
    latency_ms          REAL,
    FOREIGN KEY (recording_id) REFERENCES dialog_recordings(id) ON DELETE CASCADE,
    UNIQUE (recording_id, turn_number)
);
CREATE INDEX IF NOT EXISTS idx_dialog_turns_recording ON dialog_turns(recording_id);

-- Human-in-the-Loop interactions (#384). session_id joins
-- agentic_harnesses.session_id but is deliberately not an FK: sessions
-- may be bracketed in a different DATABASE_URL (see save_recording's
-- dangling-session note) and losing a pending approval record to an FK
-- reject would be worse than a loose join — the fail-closed gate in
-- rfc.hitl_gate is the safety mechanism, not referential integrity.
CREATE TABLE IF NOT EXISTS hitl_interactions (
    id               TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL,
    kind             TEXT NOT NULL,
    prompt           TEXT NOT NULL,
    response         TEXT,
    target_action_id TEXT,
    args_digest      TEXT,
    status           TEXT NOT NULL DEFAULT 'pending',
    created_at       TEXT NOT NULL,
    resolved_at      TEXT,
    expires_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_hitl_session ON hitl_interactions(session_id);
CREATE INDEX IF NOT EXISTS idx_hitl_action  ON hitl_interactions(target_action_id);
"""

# Backfill columns onto agentic_harnesses created before the column existed. Each
# ALTER runs after the CREATE-IF-NOT-EXISTS above: on a fresh DB the column already
# exists and SQLite raises "duplicate column name" (caught as idempotent); on an
# older DB the column is added, leaving existing rows NULL. Nullable, so old
# writers keep working unchanged. Per-statement + independently idempotent, so a
# half-migrated DB (some columns already present) backfills only the missing ones.
# #217 added scenario_id/battery_run_id; #242 (RFC-008 A3) added the provenance set;
# #277 added repeat_idx (INTEGER, the one non-text column) for S4 pairing.
_SQLITE_MIGRATIONS: list[str] = [
    "ALTER TABLE agentic_harnesses ADD COLUMN scenario_id TEXT",
    "ALTER TABLE agentic_harnesses ADD COLUMN battery_run_id TEXT",
    "ALTER TABLE agentic_harnesses ADD COLUMN model_digest TEXT",
    "ALTER TABLE agentic_harnesses ADD COLUMN prompt_id TEXT",
    "ALTER TABLE agentic_harnesses ADD COLUMN prompt_hash TEXT",
    "ALTER TABLE agentic_harnesses ADD COLUMN grader_version TEXT",
    "ALTER TABLE agentic_harnesses ADD COLUMN params_json TEXT",
    "ALTER TABLE agentic_harnesses ADD COLUMN repeat_idx INTEGER",
]

# Canonical body of the ``agentic_sessions_full`` view (issue #353).
#
# Denormalizes ``agentic_harnesses`` and pre-pivots the EAV rows in
# ``agentic_metrics`` (tokens_in / tokens_out / latency_ms / grader_score, plus
# the RFC-010 S1 efficiency pair cache_hit_rate / suite_runtime_ms — #258) into
# one row per harness session. cache_hit_rate is AVG'd (mean per-run rate) and
# suite_runtime_ms is SUM'd (total wall time across the session's suites). The
# Superset bootstrap
# (superset/bootstrap_dashboards.py) embeds a copy of this SQL in its DDL;
# a drift-guard test in tests/test_bootstrap_dashboards.py keeps the two
# in sync. Written in the portable subset shared by PostgreSQL and SQLite.
AGENTIC_SESSIONS_FULL_VIEW_BODY: str = """\
SELECT
    h.session_id,
    h.tool_name,
    h.tool_version,
    h.model_id,
    h.rfc_version,
    h.branch,
    h.started_at,
    CAST(h.started_at AS TIMESTAMP) AS started_ts,
    h.ended_at,
    h.outcome,
    h.replay_of_recording_id,
    SUM(CASE WHEN m.metric_key = 'tokens_in' THEN m.metric_value END)
        AS tokens_in,
    SUM(CASE WHEN m.metric_key = 'tokens_out' THEN m.metric_value END)
        AS tokens_out,
    AVG(CASE WHEN m.metric_key = 'latency_ms' THEN m.metric_value END)
        AS avg_latency_ms,
    AVG(CASE WHEN m.metric_key = 'grader_score' THEN m.metric_value END)
        AS avg_grader_score,
    AVG(CASE WHEN m.metric_key = 'cache_hit_rate' THEN m.metric_value END)
        AS cache_hit_rate,
    SUM(CASE WHEN m.metric_key = 'suite_runtime_ms' THEN m.metric_value END)
        AS suite_runtime_ms
FROM agentic_harnesses h
LEFT JOIN agentic_metrics m ON m.session_id = h.session_id
GROUP BY h.session_id, h.tool_name, h.tool_version, h.model_id,
         h.rfc_version, h.branch, h.started_at, h.ended_at, h.outcome,
         h.replay_of_recording_id"""


# Canonical body of the ``harness_scoreboard`` view (RFC-007 S5 / issue #221).
#
# The owner's headline product: SEEING which harness is better. One row per
# comparison cell ``(tool_name, model_id, scenario_id)`` over the battery runs on
# the spine — sibling to ``AGENTIC_SESSIONS_FULL_VIEW_BODY``, same portable
# SQLite/Postgres subset, same drift-guard pattern (a copy is embedded in
# superset/bootstrap_dashboards.py::_AGENTIC_TABLE_DDL and kept in sync by a test
# in tests/test_bootstrap_dashboards.py).
#
# Pivots the RFC-007 reserved metric keys into per-cell aggregates:
#   * ``pass_rate``   = AVG(task_success)  — task_success is 0/1, so its mean over
#                       the cell's runs is the pass rate; ``pass_count`` is the SUM.
#   * economy         = AVG(churn_ratio), AVG(process_violations)
#   * efficiency      = AVG(tokens_in / tokens_out / latency_ms) plus the RFC-010
#                       S1 pair AVG(cache_hit_rate / suite_runtime_ms) (#258)
# Each aggregate is a mean over the runs in the cell (comparison runs write one
# metric row per key per session), NULL-skipping like ``agentic_sessions_full``.
#
# HONEST TIER SEPARATION (RFC-007 section 5, the #273 lesson). Tier-A ("fixed
# local model", head-to-head comparable) and Tier-B ("native model", descriptive
# only) numbers must NEVER share a comparison cell. The view carries a ``tier``
# column consumers MUST respect. It is a **name approximation, not a
# verification**: the spine persists no tier, so the view derives it from a
# tool_name allowlist (opencode/codex -> A; every other name, incl.
# claude-code's native frontier model, -> B). The unknown-name default is
# fail-closed, but the allowlist **fails open on a name** — a misconfigured
# opencode/codex run that did not actually resolve to the pinned local model
# would still be labelled Tier A here (#350). The genuine invariant ("did the
# model resolve local?") is enforced only at write time by the
# VerifiedLocalModel gate in ComparisonRow.__post_init__ and is NOT mirrored by
# this CASE. Per the #350 ruling, the fix is a persisted tier/verified_local
# spine column this view reads fail-closed; the #220 significance-overlay JOIN
# is gated on that column landing. ``cell_label`` bakes the tier letter into the
# harness axis label so a Tier-B cell is structurally distinct on the heatmap
# and can never overlay a Tier-A one.
#
# Scoped to battery/comparison runs only (``scenario_id`` present) — ad-hoc
# harness sessions (no scenario) are not a scoreboard cell.
#
# SEAM for #220 (RFC-007 S4, McNemar gate, feat/220-mcnemar-gate): this view
# deliberately computes NO significance. The "is the difference real?" overlay —
# per-pair p-value + delta, so a not-significant cell renders *tied* and never a
# faint-green *better* — is #220's output; the dashboard LEFT JOINs it onto this
# view once that lands AND the #350 persisted-tier column unifies the row
# population (see above). Statistics live in harness_comparison.py, not here.
HARNESS_SCOREBOARD_VIEW_BODY: str = """\
SELECT
    h.tool_name,
    h.model_id,
    h.scenario_id,
    CASE WHEN h.tool_name IN ('opencode', 'codex') THEN 'A' ELSE 'B' END
        AS tier,
    '[' || CASE WHEN h.tool_name IN ('opencode', 'codex') THEN 'A' ELSE 'B' END
        || '] ' || h.tool_name || ' @ ' || COALESCE(h.model_id, '')
        AS cell_label,
    COUNT(DISTINCT h.session_id) AS run_count,
    SUM(CASE WHEN m.metric_key = 'task_success' THEN m.metric_value END)
        AS pass_count,
    AVG(CASE WHEN m.metric_key = 'task_success' THEN m.metric_value END)
        AS pass_rate,
    AVG(CASE WHEN m.metric_key = 'churn_ratio' THEN m.metric_value END)
        AS avg_churn_ratio,
    AVG(CASE WHEN m.metric_key = 'process_violations' THEN m.metric_value END)
        AS avg_process_violations,
    AVG(CASE WHEN m.metric_key = 'tokens_in' THEN m.metric_value END)
        AS avg_tokens_in,
    AVG(CASE WHEN m.metric_key = 'tokens_out' THEN m.metric_value END)
        AS avg_tokens_out,
    AVG(CASE WHEN m.metric_key = 'latency_ms' THEN m.metric_value END)
        AS avg_latency_ms,
    AVG(CASE WHEN m.metric_key = 'cache_hit_rate' THEN m.metric_value END)
        AS avg_cache_hit_rate,
    AVG(CASE WHEN m.metric_key = 'suite_runtime_ms' THEN m.metric_value END)
        AS avg_suite_runtime_ms
FROM agentic_harnesses h
LEFT JOIN agentic_metrics m ON m.session_id = h.session_id
WHERE h.scenario_id IS NOT NULL AND h.scenario_id <> ''
GROUP BY h.tool_name, h.model_id, h.scenario_id"""


# Row marshallers: map a positional row to its dataclass. Positional indexing
# works for both sqlite3 tuples and SQLAlchemy Row objects, so one helper serves
# both backends; column order matches each backend's SELECT / Table definition.


def _harness_from_row(row: Sequence[Any]) -> AgenticHarness:
    return AgenticHarness(
        session_id=row[0],
        tool_name=row[1],
        tool_version=row[2] or "",
        model_id=row[3] or "",
        rfc_version=row[4] or "",
        branch=row[5] or "",
        started_at=row[6],
        ended_at=row[7] or "",
        outcome=row[8] or "",
        replay_of_recording_id=row[9] or "",
        scenario_id=row[10] or "",
        battery_run_id=row[11] or "",
        model_digest=row[12] or "",
        prompt_id=row[13] or "",
        prompt_hash=row[14] or "",
        grader_version=row[15] or "",
        params_json=row[16] or "",
        # #277: INTEGER column, so the int-id sentinel convention (NULL -> -1),
        # NOT the "" text one. A stored 0 must round-trip as 0, so this is an
        # explicit is-None check, never `row[17] or -1` (which would map 0 -> -1).
        repeat_idx=int(row[17]) if row[17] is not None else -1,
    )


def _plugin_from_row(row: Sequence[Any]) -> AgenticPlugin:
    return AgenticPlugin(
        session_id=row[1],
        plugin_name=row[2],
        recorded_at=row[5],
        semver=row[3] or "",
        source=row[4] or "",
        id=row[0],
    )


def _skill_from_row(row: Sequence[Any]) -> AgenticSkill:
    return AgenticSkill(
        session_id=row[1],
        skill_path=row[2],
        recorded_at=row[5],
        git_sha=row[3] or "",
        skill_name=row[4] or "",
        id=row[0],
    )


def _metric_from_row(row: Sequence[Any]) -> AgenticMetric:
    return AgenticMetric(
        session_id=row[1],
        metric_key=row[4],
        recorded_at=row[6],
        metric_value=float(row[5]) if row[5] is not None else 0.0,
        test_run_id=row[2] if row[2] is not None else -1,
        test_result_id=row[3] if row[3] is not None else -1,
        id=row[0],
    )


def _decision_from_row(row: Sequence[Any]) -> AgenticDecision:
    return AgenticDecision(
        session_id=row[1],
        hook_event=row[3],
        prompt_model=row[4],
        prompt_text=row[5],
        recorded_at=row[10],
        test_name=row[2] or "",
        response_text=row[6] or "",
        proposed_action=row[7] or "",
        applied=int(row[8]),
        tokens_used=int(row[9]) if row[9] is not None else -1,
        id=row[0],
    )


def _recording_from_row(row: Sequence[Any]) -> DialogRecording:
    return DialogRecording(
        id=row[0],
        session_id=row[1] or "",
        source_type=row[2],
        tool_name=row[3] or "",
        tool_version=row[4] or "",
        model_id=row[5] or "",
        started_at=row[6],
        ended_at=row[7] or "",
        metadata_json=row[8] or "",
    )


def _turn_from_row(row: Sequence[Any]) -> DialogTurn:
    return DialogTurn(
        recording_id=row[1],
        turn_number=int(row[2]),
        role=row[3],
        content=row[4] or "",
        tool_calls_json=row[5] or "",
        tool_results_json=row[6] or "",
        timestamp=row[7],
        prompt_tokens=int(row[8]) if row[8] is not None else -1,
        completion_tokens=int(row[9]) if row[9] is not None else -1,
        latency_ms=float(row[10]) if row[10] is not None else -1.0,
        id=row[0],
    )


_HITL_COLUMNS = (
    "id, session_id, kind, prompt, response, target_action_id, "
    "args_digest, status, created_at, resolved_at, expires_at"
)


def _hitl_from_row(row: Sequence[Any]) -> HitlInteraction:
    return HitlInteraction(
        id=row[0],
        session_id=row[1],
        kind=row[2],
        prompt=row[3],
        response=row[4] or "",
        target_action_id=row[5] or "",
        args_digest=row[6] or "",
        status=row[7],
        created_at=row[8],
        resolved_at=row[9] or "",
        expires_at=row[10] or "",
    )


# ---------------------------------------------------------------------------
# Backend ABC
# ---------------------------------------------------------------------------


class _HarnessBackend(abc.ABC):
    """Abstract interface shared by SQLite and SQLAlchemy backends."""

    @abc.abstractmethod
    def save_harness(self, harness: AgenticHarness) -> str: ...

    @abc.abstractmethod
    def end_harness(self, session_id: str, outcome: str, ended_at: str) -> None: ...

    @abc.abstractmethod
    def get_harness(self, session_id: str) -> Optional[AgenticHarness]: ...

    @abc.abstractmethod
    def save_plugins(self, plugins: list[AgenticPlugin]) -> list[str]: ...

    @abc.abstractmethod
    def save_skills(self, skills: list[AgenticSkill]) -> list[str]: ...

    @abc.abstractmethod
    def get_plugins(self, session_id: str) -> list[AgenticPlugin]: ...

    @abc.abstractmethod
    def get_skills(self, session_id: str) -> list[AgenticSkill]: ...

    @abc.abstractmethod
    def save_metric(self, metric: AgenticMetric) -> str: ...

    @abc.abstractmethod
    def save_metrics(self, metrics: list[AgenticMetric]) -> list[str]: ...

    @abc.abstractmethod
    def get_metrics(
        self, session_id: str, *, metric_key: str = ""
    ) -> list[AgenticMetric]: ...

    @abc.abstractmethod
    def save_decision(self, decision: AgenticDecision) -> str: ...

    @abc.abstractmethod
    def save_decisions(self, decisions: list[AgenticDecision]) -> list[str]: ...

    @abc.abstractmethod
    def get_decisions(
        self, session_id: str, *, proposed_action: str = ""
    ) -> list[AgenticDecision]: ...

    @abc.abstractmethod
    def save_recording(self, recording: DialogRecording) -> str: ...

    @abc.abstractmethod
    def end_recording(self, recording_id: str, ended_at: str) -> None: ...

    @abc.abstractmethod
    def get_recording(self, recording_id: str) -> Optional[DialogRecording]: ...

    @abc.abstractmethod
    def save_turns(self, turns: list[DialogTurn]) -> list[str]: ...

    @abc.abstractmethod
    def get_turns(self, recording_id: str) -> list[DialogTurn]: ...

    @abc.abstractmethod
    def save_interaction(self, interaction: HitlInteraction) -> str: ...

    @abc.abstractmethod
    def get_interaction(self, interaction_id: str) -> Optional[HitlInteraction]: ...

    @abc.abstractmethod
    def resolve_interaction(
        self, interaction_id: str, status: str, response: str, resolved_at: str
    ) -> bool:
        """Compare-and-set a pending row to a terminal status.

        Returns True when the row transitioned; False when it was missing
        or no longer pending (callers treat False as fail-closed).
        """
        ...

    @abc.abstractmethod
    def list_interactions(
        self, session_id: str, *, kind: str = "", status: str = ""
    ) -> list[HitlInteraction]: ...

    @abc.abstractmethod
    def get_version(self) -> str: ...

    @abc.abstractmethod
    def get_table_row_count(self, table_name: str) -> int: ...


# ---------------------------------------------------------------------------
# SQLite backend
# ---------------------------------------------------------------------------


class _SQLiteHarnessBackend(_HarnessBackend):
    """SQLite backend using the stdlib sqlite3 module."""

    def __init__(self, db_path: str, *, create_missing_dir: bool = True) -> None:
        self.db_path = db_path
        if create_missing_dir:
            os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(_SQLITE_SCHEMA)
            for sql in _SQLITE_MIGRATIONS:
                try:
                    conn.execute(sql)
                except sqlite3.OperationalError:
                    pass  # idempotent: column already present, etc.

    def save_harness(self, harness: AgenticHarness) -> str:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """
                INSERT INTO agentic_harnesses
                (session_id, tool_name, tool_version, model_id, rfc_version,
                 branch, started_at, ended_at, outcome, replay_of_recording_id,
                 scenario_id, battery_run_id, model_digest, prompt_id, prompt_hash,
                 grader_version, params_json, repeat_idx)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    harness.session_id,
                    harness.tool_name,
                    harness.tool_version or None,
                    harness.model_id or None,
                    harness.rfc_version or None,
                    harness.branch or None,
                    harness.started_at,
                    harness.ended_at or None,
                    harness.outcome or None,
                    harness.replay_of_recording_id or None,
                    harness.scenario_id or None,
                    harness.battery_run_id or None,
                    harness.model_digest or None,
                    harness.prompt_id or None,
                    harness.prompt_hash or None,
                    harness.grader_version or None,
                    harness.params_json or None,
                    # #277: is->=0 guard, not `or None` -- repeat 0 must persist as 0.
                    harness.repeat_idx if harness.repeat_idx >= 0 else None,
                ),
            )
        return harness.session_id

    def end_harness(self, session_id: str, outcome: str, ended_at: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE agentic_harnesses SET outcome = ?, ended_at = ? WHERE session_id = ?",
                (outcome, ended_at, session_id),
            )
            if cursor.rowcount == 0:
                raise LookupError(f"no harness with session_id={session_id!r}")

    def get_harness(self, session_id: str) -> Optional[AgenticHarness]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT session_id, tool_name, tool_version, model_id, rfc_version,
                       branch, started_at, ended_at, outcome, replay_of_recording_id,
                       scenario_id, battery_run_id, model_digest, prompt_id,
                       prompt_hash, grader_version, params_json, repeat_idx
                FROM agentic_harnesses WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return _harness_from_row(row)

    def save_plugins(self, plugins: list[AgenticPlugin]) -> list[str]:
        ids: list[str] = []
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            for p in plugins:
                row_id = p.id or uuid.uuid4().hex
                conn.execute(
                    """
                    INSERT OR REPLACE INTO agentic_plugins
                    (id, session_id, plugin_name, semver, source, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row_id,
                        p.session_id,
                        p.plugin_name,
                        p.semver or None,
                        p.source or None,
                        p.recorded_at,
                    ),
                )
                ids.append(row_id)
        return ids

    def save_skills(self, skills: list[AgenticSkill]) -> list[str]:
        ids: list[str] = []
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            for s in skills:
                row_id = s.id or uuid.uuid4().hex
                conn.execute(
                    """
                    INSERT OR REPLACE INTO agentic_skills
                    (id, session_id, skill_path, git_sha, skill_name, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row_id,
                        s.session_id,
                        s.skill_path,
                        s.git_sha or None,
                        s.skill_name or None,
                        s.recorded_at,
                    ),
                )
                ids.append(row_id)
        return ids

    def get_plugins(self, session_id: str) -> list[AgenticPlugin]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, session_id, plugin_name, semver, source, recorded_at "
                "FROM agentic_plugins WHERE session_id = ? ORDER BY plugin_name",
                (session_id,),
            ).fetchall()
        return [_plugin_from_row(r) for r in rows]

    def get_skills(self, session_id: str) -> list[AgenticSkill]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, session_id, skill_path, git_sha, skill_name, recorded_at "
                "FROM agentic_skills WHERE session_id = ? ORDER BY skill_path",
                (session_id,),
            ).fetchall()
        return [_skill_from_row(r) for r in rows]

    def save_metric(self, metric: AgenticMetric) -> str:
        return self.save_metrics([metric])[0]

    def save_metrics(self, metrics: list[AgenticMetric]) -> list[str]:
        ids: list[str] = []
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            for m in metrics:
                row_id = m.id or uuid.uuid4().hex
                conn.execute(
                    """
                    INSERT INTO agentic_metrics
                    (id, session_id, test_run_id, test_result_id,
                     metric_key, metric_value, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row_id,
                        m.session_id,
                        m.test_run_id if m.test_run_id != -1 else None,
                        m.test_result_id if m.test_result_id != -1 else None,
                        m.metric_key,
                        m.metric_value,
                        m.recorded_at,
                    ),
                )
                ids.append(row_id)
        return ids

    def get_metrics(
        self, session_id: str, *, metric_key: str = ""
    ) -> list[AgenticMetric]:
        sql = (
            "SELECT id, session_id, test_run_id, test_result_id, "
            "metric_key, metric_value, recorded_at "
            "FROM agentic_metrics WHERE session_id = ? "
        )
        params: tuple = (session_id,)
        if metric_key:
            sql += "AND metric_key = ? "
            params = params + (metric_key,)
        sql += "ORDER BY recorded_at, id"
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_metric_from_row(r) for r in rows]

    def save_decision(self, decision: AgenticDecision) -> str:
        return self.save_decisions([decision])[0]

    def save_decisions(self, decisions: list[AgenticDecision]) -> list[str]:
        ids: list[str] = []
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            for d in decisions:
                row_id = d.id or uuid.uuid4().hex
                conn.execute(
                    """
                    INSERT INTO agentic_decisions
                    (id, session_id, test_name, hook_event, prompt_model,
                     prompt_text, response_text, proposed_action, applied,
                     tokens_used, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row_id,
                        d.session_id,
                        d.test_name or None,
                        d.hook_event,
                        d.prompt_model,
                        d.prompt_text,
                        d.response_text or None,
                        d.proposed_action or None,
                        d.applied,
                        d.tokens_used if d.tokens_used >= 0 else None,
                        d.recorded_at,
                    ),
                )
                ids.append(row_id)
        return ids

    def get_decisions(
        self, session_id: str, *, proposed_action: str = ""
    ) -> list[AgenticDecision]:
        sql = (
            "SELECT id, session_id, test_name, hook_event, prompt_model, "
            "prompt_text, response_text, proposed_action, applied, "
            "tokens_used, recorded_at "
            "FROM agentic_decisions WHERE session_id = ? "
        )
        params: tuple = (session_id,)
        if proposed_action:
            sql += "AND proposed_action = ? "
            params = params + (proposed_action,)
        sql += "ORDER BY recorded_at, id"
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_decision_from_row(r) for r in rows]

    def save_recording(self, recording: DialogRecording) -> str:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """
                INSERT INTO dialog_recordings
                (id, session_id, source_type, tool_name, tool_version,
                 model_id, started_at, ended_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    recording.id,
                    recording.session_id or None,
                    recording.source_type,
                    recording.tool_name or None,
                    recording.tool_version or None,
                    recording.model_id or None,
                    recording.started_at,
                    recording.ended_at or None,
                    recording.metadata_json or None,
                ),
            )
        return recording.id

    def end_recording(self, recording_id: str, ended_at: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE dialog_recordings SET ended_at = ? WHERE id = ?",
                (ended_at, recording_id),
            )
            if cursor.rowcount == 0:
                raise LookupError(f"no recording with id={recording_id!r}")

    def get_recording(self, recording_id: str) -> Optional[DialogRecording]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT id, session_id, source_type, tool_name, tool_version,
                       model_id, started_at, ended_at, metadata_json
                FROM dialog_recordings WHERE id = ?
                """,
                (recording_id,),
            ).fetchone()
        if row is None:
            return None
        return _recording_from_row(row)

    def save_turns(self, turns: list[DialogTurn]) -> list[str]:
        ids: list[str] = []
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            for t in turns:
                row_id = t.id or uuid.uuid4().hex
                conn.execute(
                    """
                    INSERT OR REPLACE INTO dialog_turns
                    (id, recording_id, turn_number, role, content,
                     tool_calls_json, tool_results_json, timestamp,
                     prompt_tokens, completion_tokens, latency_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row_id,
                        t.recording_id,
                        t.turn_number,
                        t.role,
                        t.content or None,
                        t.tool_calls_json or None,
                        t.tool_results_json or None,
                        t.timestamp,
                        t.prompt_tokens if t.prompt_tokens >= 0 else None,
                        t.completion_tokens if t.completion_tokens >= 0 else None,
                        t.latency_ms if t.latency_ms >= 0 else None,
                    ),
                )
                ids.append(row_id)
        return ids

    def get_turns(self, recording_id: str) -> list[DialogTurn]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, recording_id, turn_number, role, content,
                       tool_calls_json, tool_results_json, timestamp,
                       prompt_tokens, completion_tokens, latency_ms
                FROM dialog_turns WHERE recording_id = ? ORDER BY turn_number
                """,
                (recording_id,),
            ).fetchall()
        return [_turn_from_row(r) for r in rows]

    def save_interaction(self, interaction: HitlInteraction) -> str:
        row_id = interaction.id or uuid.uuid4().hex
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                f"""
                INSERT INTO hitl_interactions ({_HITL_COLUMNS})
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,  # noqa: S608 — column list is a module constant
                (
                    row_id,
                    interaction.session_id,
                    interaction.kind,
                    interaction.prompt,
                    interaction.response or None,
                    interaction.target_action_id or None,
                    interaction.args_digest or None,
                    interaction.status,
                    interaction.created_at,
                    interaction.resolved_at or None,
                    interaction.expires_at or None,
                ),
            )
        return row_id

    def get_interaction(self, interaction_id: str) -> Optional[HitlInteraction]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                f"SELECT {_HITL_COLUMNS} FROM hitl_interactions WHERE id = ?",  # noqa: S608
                (interaction_id,),
            ).fetchone()
        if row is None:
            return None
        return _hitl_from_row(row)

    def resolve_interaction(
        self, interaction_id: str, status: str, response: str, resolved_at: str
    ) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE hitl_interactions "
                "SET status = ?, response = ?, resolved_at = ? "
                "WHERE id = ? AND status = 'pending'",
                (status, response or None, resolved_at, interaction_id),
            )
            return cursor.rowcount > 0

    def list_interactions(
        self, session_id: str, *, kind: str = "", status: str = ""
    ) -> list[HitlInteraction]:
        sql = (
            f"SELECT {_HITL_COLUMNS} FROM hitl_interactions "  # noqa: S608
            "WHERE session_id = ? "
        )
        params: tuple = (session_id,)
        if kind:
            sql += "AND kind = ? "
            params = params + (kind,)
        if status:
            sql += "AND status = ? "
            params = params + (status,)
        sql += "ORDER BY created_at, id"
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_hitl_from_row(r) for r in rows]

    def get_version(self) -> str:
        with sqlite3.connect(self.db_path) as conn:
            return str(conn.execute("SELECT sqlite_version()").fetchone()[0])

    def get_table_row_count(self, table_name: str) -> int:
        # Table name allow-listed to prevent SQL injection via the parameter.
        if table_name not in {
            "agentic_harnesses",
            "agentic_plugins",
            "agentic_skills",
            "agentic_metrics",
            "agentic_decisions",
            "dialog_recordings",
            "dialog_turns",
            "hitl_interactions",
        }:
            raise ValueError(f"unknown harness table: {table_name}")
        with sqlite3.connect(self.db_path) as conn:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])


# ---------------------------------------------------------------------------
# SQLAlchemy backend
# ---------------------------------------------------------------------------


class _SQLAlchemyHarnessBackend(_HarnessBackend):
    """SQLAlchemy backend supporting both PostgreSQL and sqlite:/// URLs.

    Imports SQLAlchemy types lazily inside the constructor so that this
    module can be imported in environments without the superset extra.
    Tests exercise this backend via sqlite:/// URLs (HarnessDatabase
    routes those through SQLAlchemy when available); production callers
    using postgresql:// URLs land here too.
    """

    # See _SQLITE_MIGRATIONS: the same backfill for the SQLAlchemy backend
    # (Postgres in production, sqlite:/// in tests). Plain ADD COLUMN (no
    # dialect-specific IF NOT EXISTS) keeps the statement portable; _run_migrations
    # runs each in its own transaction and treats "already exists" as idempotent.
    _PG_MIGRATIONS: list[str] = [
        "ALTER TABLE agentic_harnesses ADD COLUMN scenario_id VARCHAR",
        "ALTER TABLE agentic_harnesses ADD COLUMN battery_run_id VARCHAR",
        "ALTER TABLE agentic_harnesses ADD COLUMN model_digest VARCHAR",
        "ALTER TABLE agentic_harnesses ADD COLUMN prompt_id VARCHAR",
        "ALTER TABLE agentic_harnesses ADD COLUMN prompt_hash VARCHAR",
        "ALTER TABLE agentic_harnesses ADD COLUMN grader_version VARCHAR",
        "ALTER TABLE agentic_harnesses ADD COLUMN params_json VARCHAR",
        # #277: INTEGER, matching the SQLite migration and the Table column below.
        "ALTER TABLE agentic_harnesses ADD COLUMN repeat_idx INTEGER",
    ]

    def __init__(self, database_url: str) -> None:
        if not HAS_SQLALCHEMY:
            raise RuntimeError(
                "SQLAlchemy is required for the SQLAlchemy backend. "
                "Install with: uv sync --extra superset"
            )
        from sqlalchemy import (  # type: ignore[import-not-found]
            Column,
            Float,
            ForeignKey,
            Index,
            Integer,
            MetaData,
            String,
            Table,
            UniqueConstraint,
            create_engine,
            event,
            func,
            select,
            text,
        )

        # Stash the imports as instance attrs so other methods can reuse them
        # without re-importing.
        self._text = text
        self._func = func
        self._select = select
        self._database_url = database_url
        self.engine = create_engine(database_url)
        self.metadata = MetaData()
        self._harnesses = Table(
            "agentic_harnesses",
            self.metadata,
            Column("session_id", String, primary_key=True),
            Column("tool_name", String, nullable=False),
            Column("tool_version", String),
            Column("model_id", String),
            Column("rfc_version", String),
            Column("branch", String),
            Column("started_at", String, nullable=False),
            Column("ended_at", String),
            Column("outcome", String),
            Column("replay_of_recording_id", String),
            Column("scenario_id", String),
            Column("battery_run_id", String),
            # RFC-008 A3 (#242) runtime provenance. Column order must match the
            # SQLite SELECT and _harness_from_row's positional indices (12–16),
            # since the SQLAlchemy .select() returns columns in table order.
            Column("model_digest", String),
            Column("prompt_id", String),
            Column("prompt_hash", String),
            Column("grader_version", String),
            Column("params_json", String),
            # #277: repeat_idx at positional index 17 (after the #242 set), the
            # one Integer column. Sequenced after #242's columns so both sets
            # coexist and the SQLite SELECT / _harness_from_row indices agree.
            Column("repeat_idx", Integer),
        )
        self._plugins = Table(
            "agentic_plugins",
            self.metadata,
            Column("id", String, primary_key=True),
            Column(
                "session_id",
                String,
                ForeignKey("agentic_harnesses.session_id", ondelete="CASCADE"),
                nullable=False,
            ),
            Column("plugin_name", String, nullable=False),
            Column("semver", String),
            Column("source", String),
            Column("recorded_at", String, nullable=False),
            UniqueConstraint(
                "session_id", "plugin_name", name="uq_plugins_session_name"
            ),
        )
        self._skills = Table(
            "agentic_skills",
            self.metadata,
            Column("id", String, primary_key=True),
            Column(
                "session_id",
                String,
                ForeignKey("agentic_harnesses.session_id", ondelete="CASCADE"),
                nullable=False,
            ),
            Column("skill_path", String, nullable=False),
            Column("git_sha", String),
            Column("skill_name", String),
            Column("recorded_at", String, nullable=False),
            UniqueConstraint("session_id", "skill_path", name="uq_skills_session_path"),
        )
        self._metrics = Table(
            "agentic_metrics",
            self.metadata,
            Column("id", String, primary_key=True),
            Column(
                "session_id",
                String,
                ForeignKey("agentic_harnesses.session_id", ondelete="CASCADE"),
                nullable=False,
            ),
            Column("test_run_id", Integer),
            Column("test_result_id", Integer),
            Column("metric_key", String, nullable=False),
            Column("metric_value", Float),
            Column("recorded_at", String, nullable=False),
        )
        self._decisions = Table(
            "agentic_decisions",
            self.metadata,
            Column("id", String, primary_key=True),
            Column(
                "session_id",
                String,
                ForeignKey("agentic_harnesses.session_id", ondelete="CASCADE"),
                nullable=False,
            ),
            Column("test_name", String),
            Column("hook_event", String, nullable=False),
            Column("prompt_model", String, nullable=False),
            Column("prompt_text", String, nullable=False),
            Column("response_text", String),
            Column("proposed_action", String),
            Column("applied", Integer, nullable=False),
            Column("tokens_used", Integer),
            Column("recorded_at", String, nullable=False),
            Index("idx_decisions_session", "session_id"),
            Index("idx_decisions_action", "proposed_action"),
        )
        self._recordings = Table(
            "dialog_recordings",
            self.metadata,
            Column("id", String, primary_key=True),
            Column(
                "session_id",
                String,
                ForeignKey("agentic_harnesses.session_id", ondelete="SET NULL"),
            ),
            Column("source_type", String, nullable=False),
            Column("tool_name", String),
            Column("tool_version", String),
            Column("model_id", String),
            Column("started_at", String, nullable=False),
            Column("ended_at", String),
            Column("metadata_json", String),
        )
        self._turns = Table(
            "dialog_turns",
            self.metadata,
            Column("id", String, primary_key=True),
            Column(
                "recording_id",
                String,
                ForeignKey("dialog_recordings.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            Column("turn_number", Integer, nullable=False),
            Column("role", String, nullable=False),
            Column("content", String),
            Column("tool_calls_json", String),
            Column("tool_results_json", String),
            Column("timestamp", String, nullable=False),
            Column("prompt_tokens", Integer),
            Column("completion_tokens", Integer),
            Column("latency_ms", Float),
            UniqueConstraint(
                "recording_id", "turn_number", name="uq_turns_recording_number"
            ),
        )
        # No FK to agentic_harnesses — see the comment on the SQLite schema.
        self._hitl = Table(
            "hitl_interactions",
            self.metadata,
            Column("id", String, primary_key=True),
            Column("session_id", String, nullable=False),
            Column("kind", String, nullable=False),
            Column("prompt", String, nullable=False),
            Column("response", String),
            Column("target_action_id", String),
            Column("args_digest", String),
            Column("status", String, nullable=False),
            Column("created_at", String, nullable=False),
            Column("resolved_at", String),
            Column("expires_at", String),
            Index("idx_hitl_session", "session_id"),
            Index("idx_hitl_action", "target_action_id"),
        )
        # SQLite ignores FK constraints unless PRAGMA foreign_keys=ON is set
        # on every connection. Postgres enforces FKs unconditionally.
        if self.engine.dialect.name == "sqlite":

            @event.listens_for(self.engine, "connect")
            def _enable_sqlite_fk(dbapi_connection, _connection_record):  # type: ignore[no-untyped-def]
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        try:
            self.metadata.create_all(self.engine)
        except Exception:
            logger.warning("create_all() failed; running migrations anyway")
        self._run_migrations()

    def _run_migrations(self) -> None:
        # Each migration runs in its OWN transaction: on PostgreSQL a failed
        # statement (e.g. ADD COLUMN of a column that already exists on a fresh
        # DB) aborts the whole transaction, so batching them would poison every
        # later statement. Per-statement transactions keep each idempotent add
        # independent across both the PostgreSQL and sqlite:/// backends.
        for sql in self._PG_MIGRATIONS:
            try:
                with self.engine.begin() as conn:
                    conn.execute(self._text(sql))
            except Exception as exc:  # idempotent: column exists, etc.
                logger.debug("migration skipped: %s (%s)", sql, exc)

    # CRUD ---------------------------------------------------------------------

    def save_harness(self, harness: AgenticHarness) -> str:
        with self.engine.begin() as conn:
            conn.execute(
                self._harnesses.insert(),
                {
                    "session_id": harness.session_id,
                    "tool_name": harness.tool_name,
                    "tool_version": harness.tool_version or None,
                    "model_id": harness.model_id or None,
                    "rfc_version": harness.rfc_version or None,
                    "branch": harness.branch or None,
                    "started_at": harness.started_at,
                    "ended_at": harness.ended_at or None,
                    "outcome": harness.outcome or None,
                    "replay_of_recording_id": harness.replay_of_recording_id or None,
                    "scenario_id": harness.scenario_id or None,
                    "battery_run_id": harness.battery_run_id or None,
                    "model_digest": harness.model_digest or None,
                    "prompt_id": harness.prompt_id or None,
                    "prompt_hash": harness.prompt_hash or None,
                    "grader_version": harness.grader_version or None,
                    "params_json": harness.params_json or None,
                    # #277: is->=0 guard, not `or None` -- repeat 0 must persist as 0.
                    "repeat_idx": harness.repeat_idx
                    if harness.repeat_idx >= 0
                    else None,
                },
            )
        return harness.session_id

    def end_harness(self, session_id: str, outcome: str, ended_at: str) -> None:
        with self.engine.begin() as conn:
            result = conn.execute(
                self._harnesses.update()
                .where(self._harnesses.c.session_id == session_id)
                .values(outcome=outcome, ended_at=ended_at)
            )
            if result.rowcount == 0:
                raise LookupError(f"no harness with session_id={session_id!r}")

    def get_harness(self, session_id: str) -> Optional[AgenticHarness]:
        with self.engine.connect() as conn:
            row = conn.execute(
                self._harnesses.select().where(
                    self._harnesses.c.session_id == session_id
                )
            ).fetchone()
        if row is None:
            return None
        return _harness_from_row(row)

    def save_plugins(self, plugins: list[AgenticPlugin]) -> list[str]:
        ids: list[str] = []
        # SQLAlchemy doesn't expose INSERT OR REPLACE portably; emulate with
        # delete-then-insert per row keyed on the UNIQUE pair.
        with self.engine.begin() as conn:
            for p in plugins:
                row_id = p.id or uuid.uuid4().hex
                conn.execute(
                    self._plugins.delete().where(
                        (self._plugins.c.session_id == p.session_id)
                        & (self._plugins.c.plugin_name == p.plugin_name)
                    )
                )
                conn.execute(
                    self._plugins.insert(),
                    {
                        "id": row_id,
                        "session_id": p.session_id,
                        "plugin_name": p.plugin_name,
                        "semver": p.semver or None,
                        "source": p.source or None,
                        "recorded_at": p.recorded_at,
                    },
                )
                ids.append(row_id)
        return ids

    def save_skills(self, skills: list[AgenticSkill]) -> list[str]:
        ids: list[str] = []
        with self.engine.begin() as conn:
            for s in skills:
                row_id = s.id or uuid.uuid4().hex
                conn.execute(
                    self._skills.delete().where(
                        (self._skills.c.session_id == s.session_id)
                        & (self._skills.c.skill_path == s.skill_path)
                    )
                )
                conn.execute(
                    self._skills.insert(),
                    {
                        "id": row_id,
                        "session_id": s.session_id,
                        "skill_path": s.skill_path,
                        "git_sha": s.git_sha or None,
                        "skill_name": s.skill_name or None,
                        "recorded_at": s.recorded_at,
                    },
                )
                ids.append(row_id)
        return ids

    def get_plugins(self, session_id: str) -> list[AgenticPlugin]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                self._plugins.select()
                .where(self._plugins.c.session_id == session_id)
                .order_by(self._plugins.c.plugin_name)
            ).fetchall()
        return [_plugin_from_row(r) for r in rows]

    def get_skills(self, session_id: str) -> list[AgenticSkill]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                self._skills.select()
                .where(self._skills.c.session_id == session_id)
                .order_by(self._skills.c.skill_path)
            ).fetchall()
        return [_skill_from_row(r) for r in rows]

    def save_metric(self, metric: AgenticMetric) -> str:
        return self.save_metrics([metric])[0]

    def save_metrics(self, metrics: list[AgenticMetric]) -> list[str]:
        ids: list[str] = []
        with self.engine.begin() as conn:
            for m in metrics:
                row_id = m.id or uuid.uuid4().hex
                conn.execute(
                    self._metrics.insert(),
                    {
                        "id": row_id,
                        "session_id": m.session_id,
                        "test_run_id": m.test_run_id if m.test_run_id != -1 else None,
                        "test_result_id": (
                            m.test_result_id if m.test_result_id != -1 else None
                        ),
                        "metric_key": m.metric_key,
                        "metric_value": m.metric_value,
                        "recorded_at": m.recorded_at,
                    },
                )
                ids.append(row_id)
        return ids

    def get_metrics(
        self, session_id: str, *, metric_key: str = ""
    ) -> list[AgenticMetric]:
        stmt = self._metrics.select().where(self._metrics.c.session_id == session_id)
        if metric_key:
            stmt = stmt.where(self._metrics.c.metric_key == metric_key)
        stmt = stmt.order_by(self._metrics.c.recorded_at, self._metrics.c.id)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return [_metric_from_row(r) for r in rows]

    def save_decision(self, decision: AgenticDecision) -> str:
        return self.save_decisions([decision])[0]

    def save_decisions(self, decisions: list[AgenticDecision]) -> list[str]:
        ids: list[str] = []
        with self.engine.begin() as conn:
            for d in decisions:
                row_id = d.id or uuid.uuid4().hex
                conn.execute(
                    self._decisions.insert(),
                    {
                        "id": row_id,
                        "session_id": d.session_id,
                        "test_name": d.test_name or None,
                        "hook_event": d.hook_event,
                        "prompt_model": d.prompt_model,
                        "prompt_text": d.prompt_text,
                        "response_text": d.response_text or None,
                        "proposed_action": d.proposed_action or None,
                        "applied": d.applied,
                        "tokens_used": d.tokens_used if d.tokens_used >= 0 else None,
                        "recorded_at": d.recorded_at,
                    },
                )
                ids.append(row_id)
        return ids

    def get_decisions(
        self, session_id: str, *, proposed_action: str = ""
    ) -> list[AgenticDecision]:
        cols = self._decisions.c
        stmt = self._select(
            cols.id,
            cols.session_id,
            cols.test_name,
            cols.hook_event,
            cols.prompt_model,
            cols.prompt_text,
            cols.response_text,
            cols.proposed_action,
            cols.applied,
            cols.tokens_used,
            cols.recorded_at,
        ).where(cols.session_id == session_id)
        if proposed_action:
            stmt = stmt.where(cols.proposed_action == proposed_action)
        stmt = stmt.order_by(cols.recorded_at, cols.id)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return [_decision_from_row(r) for r in rows]

    def save_recording(self, recording: DialogRecording) -> str:
        with self.engine.begin() as conn:
            conn.execute(
                self._recordings.insert(),
                {
                    "id": recording.id,
                    "session_id": recording.session_id or None,
                    "source_type": recording.source_type,
                    "tool_name": recording.tool_name or None,
                    "tool_version": recording.tool_version or None,
                    "model_id": recording.model_id or None,
                    "started_at": recording.started_at,
                    "ended_at": recording.ended_at or None,
                    "metadata_json": recording.metadata_json or None,
                },
            )
        return recording.id

    def end_recording(self, recording_id: str, ended_at: str) -> None:
        with self.engine.begin() as conn:
            result = conn.execute(
                self._recordings.update()
                .where(self._recordings.c.id == recording_id)
                .values(ended_at=ended_at)
            )
            if result.rowcount == 0:
                raise LookupError(f"no recording with id={recording_id!r}")

    def get_recording(self, recording_id: str) -> Optional[DialogRecording]:
        cols = self._recordings.c
        stmt = self._select(
            cols.id,
            cols.session_id,
            cols.source_type,
            cols.tool_name,
            cols.tool_version,
            cols.model_id,
            cols.started_at,
            cols.ended_at,
            cols.metadata_json,
        ).where(cols.id == recording_id)
        with self.engine.connect() as conn:
            row = conn.execute(stmt).fetchone()
        if row is None:
            return None
        return _recording_from_row(row)

    def save_turns(self, turns: list[DialogTurn]) -> list[str]:
        ids: list[str] = []
        with self.engine.begin() as conn:
            for t in turns:
                row_id = t.id or uuid.uuid4().hex
                conn.execute(
                    self._turns.delete().where(
                        (self._turns.c.recording_id == t.recording_id)
                        & (self._turns.c.turn_number == t.turn_number)
                    )
                )
                conn.execute(
                    self._turns.insert(),
                    {
                        "id": row_id,
                        "recording_id": t.recording_id,
                        "turn_number": t.turn_number,
                        "role": t.role,
                        "content": t.content or None,
                        "tool_calls_json": t.tool_calls_json or None,
                        "tool_results_json": t.tool_results_json or None,
                        "timestamp": t.timestamp,
                        "prompt_tokens": t.prompt_tokens
                        if t.prompt_tokens >= 0
                        else None,
                        "completion_tokens": (
                            t.completion_tokens if t.completion_tokens >= 0 else None
                        ),
                        "latency_ms": t.latency_ms if t.latency_ms >= 0 else None,
                    },
                )
                ids.append(row_id)
        return ids

    def get_turns(self, recording_id: str) -> list[DialogTurn]:
        cols = self._turns.c
        stmt = (
            self._select(
                cols.id,
                cols.recording_id,
                cols.turn_number,
                cols.role,
                cols.content,
                cols.tool_calls_json,
                cols.tool_results_json,
                cols.timestamp,
                cols.prompt_tokens,
                cols.completion_tokens,
                cols.latency_ms,
            )
            .where(cols.recording_id == recording_id)
            .order_by(cols.turn_number)
        )
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return [_turn_from_row(r) for r in rows]

    def save_interaction(self, interaction: HitlInteraction) -> str:
        row_id = interaction.id or uuid.uuid4().hex
        with self.engine.begin() as conn:
            conn.execute(
                self._hitl.insert(),
                {
                    "id": row_id,
                    "session_id": interaction.session_id,
                    "kind": interaction.kind,
                    "prompt": interaction.prompt,
                    "response": interaction.response or None,
                    "target_action_id": interaction.target_action_id or None,
                    "args_digest": interaction.args_digest or None,
                    "status": interaction.status,
                    "created_at": interaction.created_at,
                    "resolved_at": interaction.resolved_at or None,
                    "expires_at": interaction.expires_at or None,
                },
            )
        return row_id

    def get_interaction(self, interaction_id: str) -> Optional[HitlInteraction]:
        cols = self._hitl.c
        stmt = self._select(
            cols.id,
            cols.session_id,
            cols.kind,
            cols.prompt,
            cols.response,
            cols.target_action_id,
            cols.args_digest,
            cols.status,
            cols.created_at,
            cols.resolved_at,
            cols.expires_at,
        ).where(cols.id == interaction_id)
        with self.engine.connect() as conn:
            row = conn.execute(stmt).fetchone()
        if row is None:
            return None
        return _hitl_from_row(row)

    def resolve_interaction(
        self, interaction_id: str, status: str, response: str, resolved_at: str
    ) -> bool:
        with self.engine.begin() as conn:
            result = conn.execute(
                self._hitl.update()
                .where(
                    (self._hitl.c.id == interaction_id)
                    & (self._hitl.c.status == "pending")
                )
                .values(
                    status=status,
                    response=response or None,
                    resolved_at=resolved_at,
                )
            )
            return bool(result.rowcount)

    def list_interactions(
        self, session_id: str, *, kind: str = "", status: str = ""
    ) -> list[HitlInteraction]:
        cols = self._hitl.c
        stmt = self._select(
            cols.id,
            cols.session_id,
            cols.kind,
            cols.prompt,
            cols.response,
            cols.target_action_id,
            cols.args_digest,
            cols.status,
            cols.created_at,
            cols.resolved_at,
            cols.expires_at,
        ).where(cols.session_id == session_id)
        if kind:
            stmt = stmt.where(cols.kind == kind)
        if status:
            stmt = stmt.where(cols.status == status)
        stmt = stmt.order_by(cols.created_at, cols.id)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return [_hitl_from_row(r) for r in rows]

    def get_version(self) -> str:
        return self.engine.dialect.name

    def get_table_row_count(self, table_name: str) -> int:
        table_map = {
            "agentic_harnesses": self._harnesses,
            "agentic_plugins": self._plugins,
            "agentic_skills": self._skills,
            "agentic_metrics": self._metrics,
            "agentic_decisions": self._decisions,
            "dialog_recordings": self._recordings,
            "dialog_turns": self._turns,
            "hitl_interactions": self._hitl,
        }
        if table_name not in table_map:
            raise ValueError(f"unknown harness table: {table_name}")
        with self.engine.connect() as conn:
            return int(
                conn.execute(
                    self._select(self._func.count()).select_from(table_map[table_name])
                ).scalar()
                or 0
            )


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------


class HarnessDatabase:
    """Public facade. Selects backend at construction time.

    Mirrors src/rfc/test_database.py::TestDatabase calling convention:
    pass either ``db_path=`` (SQLite file) or ``database_url=``
    (sqlite:/// or postgresql://).
    """

    def __init__(
        self,
        *,
        db_path: Optional[str] = None,
        database_url: Optional[str] = None,
    ) -> None:
        if db_path:
            # File path always uses the native sqlite3 backend (legacy fast path).
            self._backend: _HarnessBackend = _SQLiteHarnessBackend(db_path)
        elif database_url:
            # Deliberate divergence from TestDatabase: HarnessDatabase routes
            # ALL database URLs (including sqlite:///) through SQLAlchemy when
            # available, so the test suite can exercise the SQLAlchemy code
            # path against an in-tmpdir SQLite file without needing a live
            # Postgres. Falls back to native sqlite3 only when SQLAlchemy is
            # missing AND the URL is sqlite:///.
            if HAS_SQLALCHEMY:
                self._backend = _SQLAlchemyHarnessBackend(database_url)
            elif database_url.startswith("sqlite:///"):
                sqlite_path = database_url.replace("sqlite:///", "")
                # Match SQLAlchemy semantics: a URL pointing into a missing
                # directory is unreachable, not an invitation to mkdir (#439).
                self._backend = _SQLiteHarnessBackend(
                    sqlite_path, create_missing_dir=False
                )
            else:
                raise RuntimeError(
                    "SQLAlchemy is required for non-sqlite database URLs. "
                    "Install with: uv sync --extra superset"
                )
        else:
            env_url = os.environ.get("DATABASE_URL")
            if env_url:
                self.__init__(database_url=env_url)  # type: ignore[misc]
            else:
                raise RuntimeError(
                    "HarnessDatabase requires db_path=, database_url=, or DATABASE_URL env var."
                )

    # Delegating facade methods --------------------------------------------------

    def save_harness(self, harness: AgenticHarness) -> str:
        return self._backend.save_harness(harness)

    def end_harness(self, session_id: str, outcome: str, ended_at: str) -> None:
        self._backend.end_harness(session_id, outcome, ended_at)

    def get_harness(self, session_id: str) -> Optional[AgenticHarness]:
        return self._backend.get_harness(session_id)

    def save_plugins(self, plugins: list[AgenticPlugin]) -> list[str]:
        return self._backend.save_plugins(plugins)

    def save_skills(self, skills: list[AgenticSkill]) -> list[str]:
        return self._backend.save_skills(skills)

    def get_plugins(self, session_id: str) -> list[AgenticPlugin]:
        return self._backend.get_plugins(session_id)

    def get_skills(self, session_id: str) -> list[AgenticSkill]:
        return self._backend.get_skills(session_id)

    def save_metric(self, metric: AgenticMetric) -> str:
        return self._backend.save_metric(metric)

    def save_metrics(self, metrics: list[AgenticMetric]) -> list[str]:
        return self._backend.save_metrics(metrics)

    def get_metrics(
        self, session_id: str, *, metric_key: str = ""
    ) -> list[AgenticMetric]:
        return self._backend.get_metrics(session_id, metric_key=metric_key)

    def save_decision(self, decision: AgenticDecision) -> str:
        return self._backend.save_decision(decision)

    def save_decisions(self, decisions: list[AgenticDecision]) -> list[str]:
        return self._backend.save_decisions(decisions)

    def get_decisions(
        self, session_id: str, *, proposed_action: str = ""
    ) -> list[AgenticDecision]:
        return self._backend.get_decisions(session_id, proposed_action=proposed_action)

    def save_recording(self, recording: DialogRecording) -> str:
        """Persist a recording, dropping a dangling ``session_id``.

        With an isolated DIALOG_DATABASE_URL the parent agentic_harnesses
        row lives in the main DB, so the FK target is absent here. Keep
        the recording (skip-and-log per CLAUDE.md) rather than letting
        the FK reject it and lose the dialog.
        """
        if recording.session_id and self.get_harness(recording.session_id) is None:
            logger.warning(
                "save_recording: session_id %r has no agentic_harnesses row "
                "in this database (isolated dialog DB?); saving recording %s "
                "without a session link.",
                recording.session_id,
                recording.id,
            )
            recording = dataclasses.replace(recording, session_id="")
        return self._backend.save_recording(recording)

    def end_recording(self, recording_id: str, ended_at: str) -> None:
        self._backend.end_recording(recording_id, ended_at)

    def get_recording(self, recording_id: str) -> Optional[DialogRecording]:
        return self._backend.get_recording(recording_id)

    def save_turns(self, turns: list[DialogTurn]) -> list[str]:
        return self._backend.save_turns(turns)

    def get_turns(self, recording_id: str) -> list[DialogTurn]:
        return self._backend.get_turns(recording_id)

    def save_interaction(self, interaction: HitlInteraction) -> str:
        """Persist an HITL interaction (#384), validating the vocabulary.

        The kind/status enums are enforced here (single choke point for
        both backends) so a typo like ``kind='evaluation'`` cannot mint a
        row the approval gate would have to reason about.
        """
        if interaction.kind not in HITL_KINDS:
            raise ValueError(
                f"unknown HITL kind {interaction.kind!r}; expected one of {HITL_KINDS}"
            )
        if interaction.status not in HITL_STATUSES:
            raise ValueError(
                f"unknown HITL status {interaction.status!r}; "
                f"expected one of {HITL_STATUSES}"
            )
        return self._backend.save_interaction(interaction)

    def get_interaction(self, interaction_id: str) -> Optional[HitlInteraction]:
        return self._backend.get_interaction(interaction_id)

    def resolve_interaction(
        self, interaction_id: str, status: str, response: str, resolved_at: str
    ) -> bool:
        """Compare-and-set a pending interaction to a terminal status.

        Returns True when the row transitioned, False when it was missing
        or already resolved/expired — callers must treat False as
        fail-closed, never as success.
        """
        terminal = ("approved", "denied", "expired")
        if status not in terminal:
            raise ValueError(
                f"cannot resolve to status {status!r}; expected one of {terminal}"
            )
        return self._backend.resolve_interaction(
            interaction_id, status, response, resolved_at
        )

    def list_interactions(
        self, session_id: str, *, kind: str = "", status: str = ""
    ) -> list[HitlInteraction]:
        return self._backend.list_interactions(session_id, kind=kind, status=status)

    def get_version(self) -> str:
        return self._backend.get_version()

    def get_table_row_count(self, table_name: str) -> int:
        return self._backend.get_table_row_count(table_name)
