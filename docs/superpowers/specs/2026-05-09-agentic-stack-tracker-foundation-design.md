# Agentic Stack Tracker — Foundation (Issue #350) Design

**Scope:** GitHub issue [#350](https://github.com/tkarcheski/robotframework-chat/issues/350) only — the schema spine for the Agentic Stack Tracker. CLI (#351), Robot listener (#352), and Superset dashboard (#353) are out of scope and tracked separately.

**Status:** Design approved 2026-05-09 by tyler.karcheski. Ready for implementation plan.

## 1. Schema

`session_id` is the join key across all agentic_* tables and (via a nullable column) `test_runs`. It is also the primary key of the parent `agentic_harnesses` table — the spec deliberately collapses the issue's separate `id`/`session_id` pair into a single column because session_id *is* the row identity in this domain. Per-test linkage on metrics is captured via two nullable FK-shaped columns; we omit hard FK constraints on those columns so SQLite-only environments still accept metrics whose `test_runs` row lives only in Postgres.

### 1.1 New tables

```sql
-- One row per Claude-Code / Codex / OpenCode session. session_id is the spine.
CREATE TABLE IF NOT EXISTS agentic_harnesses (
    session_id              TEXT PRIMARY KEY,
    tool_name               TEXT NOT NULL,        -- 'claude-code' | 'codex' | 'opencode'
    tool_version            TEXT,
    model_id                TEXT,
    rfc_version             TEXT,
    branch                  TEXT,
    started_at              TEXT NOT NULL,        -- UTC ISO-8601
    ended_at                TEXT,
    outcome                 TEXT,                 -- 'success' | 'partial' | 'failed' | NULL while running
    replay_of_recording_id  TEXT                  -- nullable; points at dialog_recordings.id (Phase 2)
);
CREATE INDEX IF NOT EXISTS idx_harnesses_tool ON agentic_harnesses(tool_name);

-- Plugin snapshot at session start. UNIQUE guards against double-snapshot bugs.
CREATE TABLE IF NOT EXISTS agentic_plugins (
    id              TEXT PRIMARY KEY,             -- uuid4().hex assigned by backend
    session_id      TEXT NOT NULL,
    plugin_name     TEXT NOT NULL,
    semver          TEXT,
    source          TEXT,                         -- 'pyproject' | 'pip' | 'manual'
    recorded_at     TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES agentic_harnesses(session_id) ON DELETE CASCADE,
    UNIQUE (session_id, plugin_name)
);
CREATE INDEX IF NOT EXISTS idx_plugins_session ON agentic_plugins(session_id);

-- Skill (Robot .resource) snapshot with git SHA.
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

-- EAV metric stream. test_run_id and test_result_id nullable — session-level
-- and per-test metrics share the table. No FK on test_run_id / test_result_id
-- because the test_runs row may live only in Postgres while the metric is
-- written into a SQLite mirror; we want both backends to accept independently.
CREATE TABLE IF NOT EXISTS agentic_metrics (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    test_run_id     INTEGER,
    test_result_id  INTEGER,
    metric_key      TEXT NOT NULL,                -- 'tokens_in' | 'tokens_out' | 'latency_ms' | 'grader_score' | …
    metric_value    REAL,
    recorded_at     TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES agentic_harnesses(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_metrics_session ON agentic_metrics(session_id);
CREATE INDEX IF NOT EXISTS idx_metrics_key     ON agentic_metrics(metric_key);
CREATE INDEX IF NOT EXISTS idx_metrics_run     ON agentic_metrics(test_run_id);
```

### 1.2 Modification to existing `test_runs`

```sql
-- SQLite (appended to test_database.py::_SQLiteBackend._SQLITE_MIGRATIONS)
ALTER TABLE test_runs ADD COLUMN session_id TEXT;

-- Postgres (appended to test_database.py::_SQLAlchemyBackend._PG_MIGRATIONS)
ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS session_id TEXT;
```

### 1.3 Modification to `TEST_RESULTS_FULL_VIEW_BODY`

Add `r.session_id,` after the existing `r.rfc_version,` line. The view is rebuilt at every backend init via the existing `DROP VIEW IF EXISTS … CREATE VIEW …` cycle, so no extra migration step is needed.

## 2. Module architecture

### 2.1 New files

**`src/rfc/harness_models.py`** — pure dataclasses, no DB imports. Honours CLAUDE.md's "no `Optional` for DB dataclass fields" rule by giving every field a concrete default (empty string or `-1` sentinel for `int` IDs).

```python
@dataclass
class AgenticHarness:
    session_id: str
    tool_name: str
    started_at: str
    tool_version: str = ""
    model_id: str = ""
    rfc_version: str = ""
    branch: str = ""
    ended_at: str = ""
    outcome: str = ""
    replay_of_recording_id: str = ""

@dataclass
class AgenticPlugin:
    session_id: str
    plugin_name: str
    recorded_at: str
    semver: str = ""
    source: str = ""
    id: str = ""                   # backend assigns uuid4().hex when blank

@dataclass
class AgenticSkill:
    session_id: str
    skill_path: str
    recorded_at: str
    git_sha: str = ""
    skill_name: str = ""
    id: str = ""

@dataclass
class AgenticMetric:
    session_id: str
    metric_key: str
    recorded_at: str
    metric_value: float = 0.0
    test_run_id: int = -1          # -1 sentinel matches TestRun.id convention
    test_result_id: int = -1
    id: str = ""
```

**`src/rfc/harness_db.py`** — mirrors the shape of `test_database.py`:

- module level: `HAS_SQLALCHEMY` import guard, `_SQLITE_SCHEMA` constant, `_SQLITE_MIGRATIONS` (empty list — placeholder for future column adds), `_PG_MIGRATIONS` (empty)
- `class _HarnessBackend(abc.ABC)` — abstract CRUD interface
- `class _SQLiteHarnessBackend(_HarnessBackend)` — `sqlite3` implementation, `PRAGMA foreign_keys = ON`
- `class _SQLAlchemyHarnessBackend(_HarnessBackend)` — Postgres implementation
- `class HarnessDatabase` — public facade; selects backend from URL prefix (`postgresql://` → SQLAlchemy, else SQLite), matching `TestDatabase`'s convention

### 2.2 Modified file

**`src/rfc/test_database.py`** — six small additions:

1. Add `session_id TEXT` to the `test_runs` CREATE TABLE in `_SQLiteBackend.SCHEMA` (fresh SQLite DBs get the column at CREATE time).
2. Append `ALTER TABLE test_runs ADD COLUMN session_id TEXT` to `_SQLITE_MIGRATIONS` (upgrade path for pre-existing DBs).
3. Append `ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS session_id TEXT` to `_PG_MIGRATIONS`.
4. Add `r.session_id,` to `TEST_RESULTS_FULL_VIEW_BODY`.
5. Add `Column("session_id", String, nullable=True)` to the `test_runs` `Table()` in `_SQLAlchemyBackend._define_tables`.
6. Add `session_id: str = ""` to the `TestRun` dataclass.

### 2.3 New Makefile target (separate chore commit)

```makefile
robot-agentic-coding: ## Run agentic coding behaviour tests
	$(ROBOT) -d results/$(VERSION)/agentic_coding $(LISTENER) $(ARGS) robot/agentic_coding/

# update existing line
robot-agent: robot-agentic-injection robot-agentic-coding ## Master agent test suite
```

## 3. Public API surface (`HarnessDatabase`)

```python
class HarnessDatabase:
    def __init__(self, db_path_or_url: str) -> None: ...

    # Harness lifecycle
    def save_harness(self, harness: AgenticHarness) -> str: ...
    def end_harness(self, session_id: str, outcome: str, ended_at: str) -> None: ...
    def get_harness(self, session_id: str) -> AgenticHarness | None: ...
    def list_harnesses(self, *, tool_name: str = "", limit: int = 50) -> list[AgenticHarness]: ...

    # Snapshots (append-once at session start; INSERT OR REPLACE on UNIQUE keys)
    def save_plugins(self, plugins: list[AgenticPlugin]) -> list[str]: ...
    def save_skills(self, skills: list[AgenticSkill]) -> list[str]: ...
    def get_plugins(self, session_id: str) -> list[AgenticPlugin]: ...
    def get_skills(self, session_id: str) -> list[AgenticSkill]: ...

    # Metrics (high-volume; per-test or session-level)
    def save_metric(self, metric: AgenticMetric) -> str: ...
    def save_metrics(self, metrics: list[AgenticMetric]) -> list[str]: ...
    def get_metrics(self, session_id: str, *, metric_key: str = "") -> list[AgenticMetric]: ...

    # Introspection
    def get_version(self) -> str: ...
    def get_table_row_count(self, table_name: str) -> int: ...
```

**Conventions:**

- Caller controls `session_id` and any `id` they care about. Blank `id` → backend assigns `uuid.uuid4().hex` and writes it back to the dataclass. Bulk methods return ids in input order (positional alignment).
- `end_harness` raises if the row is missing — silent no-op would mask CLI bugs.
- `get_*` returning `None` / empty list is a normal query outcome; not a stored field, not an `Optional` violation.

**Deliberately out of scope:** no `delete_harness` (sessions are append-only history); no update methods other than `end_harness` (snapshots and metrics are immutable); no joined fetchers (callers compose; joined views live in `superset/bootstrap_dashboards.py` for Issue #353).

## 4. Migration strategy

Both backends embed idempotent DDL in `__init__`, matching `test_database.py`. No Alembic.

- **SQLite:** `CREATE TABLE IF NOT EXISTS …`, `CREATE INDEX IF NOT EXISTS …` in `SCHEMA`. ALTERs in `_MIGRATIONS` wrapped in `try/except sqlite3.OperationalError: pass` (handles duplicate-column on re-init).
- **Postgres:** `metadata.create_all()` for tables, then `ALTER TABLE … IF NOT EXISTS …` / `ALTER TABLE … IF EXISTS …` for migrations.
- The view is dropped + recreated on every init via `DROP VIEW IF EXISTS test_results_full; CREATE VIEW test_results_full AS …` so updates to `TEST_RESULTS_FULL_VIEW_BODY` propagate without a separate migration.

The `test_database.py` modification is itself a migration (adds `session_id` to `test_runs`). It must be safe to run on:

1. A fresh database — column appears at CREATE time on both backends (SQLite via the updated `SCHEMA` constant, Postgres via the `Table()` declaration).
2. A pre-existing database — column added via the appended ALTER (swallowing duplicate-column on SQLite re-run, native idempotency on Postgres).
3. A database that has already been migrated — no-op.

## 5. Testing plan

### 5.1 `tests/test_harness_models.py` (~30 lines)

Two tests: dataclass defaults are concrete (no `None`), and `AgenticMetric` defaults match the `-1` sentinel convention.

### 5.2 `tests/test_harness_db.py` (~250 lines, parametrized over both backends)

Mirrors the existing `tests/test_test_database.py` pattern. Behavioral tests run against SQLite via `tmp_path`; the SQLAlchemy backend is exercised through a `sqlite:///{path}` URL (so SQLAlchemy's CRUD, table definitions, and migration list are all covered without needing a live Postgres). Postgres-specific DDL (e.g., `IF NOT EXISTS`, `CASCADE`) is tested via mocks in a `TestSQLAlchemyMigrations` class — same approach as `test_test_database.py:335+`.

```python
@pytest.fixture(params=["file_path", "sqlite_url"])
def harness_db(request, tmp_path):
    db_file = tmp_path / "harness.db"
    if request.param == "file_path":
        yield HarnessDatabase(str(db_file))                    # → _SQLiteHarnessBackend
    else:
        if not HAS_SQLALCHEMY:
            pytest.skip("sqlalchemy not installed")
        yield HarnessDatabase(f"sqlite:///{db_file}")          # → _SQLAlchemyHarnessBackend
```

Test classes:

- `TestHarnessLifecycle` — save/get, `end_harness` outcome update, `end_harness` raises if missing, `get_harness` returns `None` if missing, `list_harnesses` reverse-chronological + tool filter.
- `TestSnapshots` — `save_plugins` assigns UUID when blank, preserves explicit id, INSERT OR REPLACE on `(session_id, plugin_name)`; `save_skills` returns ids in input order.
- `TestMetrics` — session-only metric (test_run_id stays NULL), metric with test_run_id, bulk insert, filter by `metric_key`.
- `TestCascades` — direct SQL delete on `agentic_harnesses` cascades to children under `PRAGMA foreign_keys = ON`.
- `TestSchema` — `__init__` is idempotent (call twice, no raise); `get_table_row_count` returns expected counts.

### 5.3 `tests/test_test_database_migration.py` (~80 lines)

Three tests:

- `test_session_id_added_to_existing_db` — build pre-migration `test_runs` schema by hand, insert a row, re-init `TestDatabase`, confirm column added and row preserved.
- `test_migration_is_idempotent` — call `TestDatabase(path)` twice on a fresh DB, no exception.
- `test_view_exposes_session_id` — insert a `TestRun` with `session_id`, query `test_results_full`, assert column appears in the result.

### 5.4 Per-commit verification suite

Run after each of the 5 commits in the build sequence:

```bash
uv run pytest                      # gates new tests + existing suite
pre-commit run --all-files
make code-quality-check            # ruff + mypy
make robot-dryrun                  # confirms no Robot test broken
make robot-agentic-coding          # the suite explicitly called out
```

The Postgres path needs `DATABASE_URL` set; absent that, the parametrized fixture skip-and-logs (per CLAUDE.md "skip-and-log over hard failure for optional / external dependencies"). SQLite path always runs.

## 6. Build sequence (5 commits)

Atomic commits, each with passing tests + the verification suite green at every step.

| # | Type | Subject | Files |
|---|------|---------|-------|
| 0 | `chore` | add robot-agentic-coding make target, include in robot-agent | `Makefile` |
| 1 | `feat` | add agentic harness dataclasses | `src/rfc/harness_models.py`, `tests/test_harness_models.py` |
| 2 | `feat` | add HarnessDatabase SQLite backend | `src/rfc/harness_db.py`, `tests/test_harness_db.py` |
| 3 | `feat` | add HarnessDatabase SQLAlchemy backend | `src/rfc/harness_db.py`, `tests/test_harness_db.py` (parametrized) |
| 4 | `feat` | add session_id to test_runs and test_results_full view | `src/rfc/test_database.py`, `tests/test_test_database_migration.py` |

Plus a final `chore: bump version to X.Y.Z+1` per CLAUDE.md PR workflow (defaults to patch).

## 7. Open questions and follow-ups

None blocking implementation. Items deliberately deferred to later issues:

- **CLI** that generates `session_id` and writes the harness row → Issue #351.
- **Robot listener** that consumes `RFC_DATA:llm_metrics:<json>` and writes `agentic_metrics` rows → Issue #352.
- **Superset dashboard** "Agentic Stack Tracker" with the joined view `agentic_sessions_full` → Issue #353.
- **Dialog tables and replay engine** → Phase 2 issues #354–#356.
- **Generative listener** → Phase 3 issues #358–#361.

The foundation is intentionally unable to do anything observable on its own; that's the point. Everything downstream gets a clean schema spine to attach to.
