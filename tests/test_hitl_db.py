"""Tests for the ``hitl_interactions`` table in HarnessDatabase (#384).

Mirrors tests/test_harness_db.py: behavioural tests run against SQLite
via tmp_path, parametrised over both the stdlib-sqlite3 and SQLAlchemy
backends so the schema and CRUD semantics cannot drift between them.
"""

import sqlite3

import pytest

from rfc.harness_db import HAS_SQLALCHEMY, HarnessDatabase
from rfc.harness_models import HITL_KINDS, HITL_STATUSES, HitlInteraction

NOW = "2026-07-01T00:00:00+00:00"
LATER = "2026-07-01T01:00:00+00:00"


def make_interaction(**overrides) -> HitlInteraction:
    defaults = dict(
        session_id="sess-1",
        kind="approval",
        prompt="May I roll out to production?",
        created_at=NOW,
        target_action_id="deploy:prod",
        args_digest="a" * 64,
        expires_at=LATER,
    )
    defaults.update(overrides)
    return HitlInteraction(**defaults)


@pytest.fixture(params=["file_path", "sqlite_url"])
def hitl_db(request, tmp_path):
    """Parametrised: SQLite via file_path AND via sqlite:/// URL."""
    db_file = tmp_path / "harness.db"
    if request.param == "file_path":
        return HarnessDatabase(db_path=str(db_file))
    if not HAS_SQLALCHEMY:
        pytest.skip("sqlalchemy not installed (install with: uv sync --extra superset)")
    return HarnessDatabase(database_url=f"sqlite:///{db_file}")


class TestVocabulary:
    def test_kinds_match_issue_384_mvp(self):
        assert HITL_KINDS == ("goal", "clarification", "approval", "input")

    def test_statuses_match_issue_384_mvp(self):
        assert HITL_STATUSES == ("pending", "approved", "denied", "expired")


class TestSchema:
    def test_init_creates_hitl_table(self, tmp_path):
        db_file = tmp_path / "harness.db"
        HarnessDatabase(db_path=str(db_file))
        with sqlite3.connect(str(db_file)) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "hitl_interactions" in tables

    def test_existing_database_gains_table_on_reopen(self, tmp_path):
        """Upgrade path: a pre-#384 database gets hitl_interactions added
        by the idempotent CREATE TABLE IF NOT EXISTS schema, exactly like
        dialog_recordings landed in #428."""
        db_file = tmp_path / "harness.db"
        with sqlite3.connect(str(db_file)) as conn:
            conn.execute("CREATE TABLE legacy_marker (id INTEGER PRIMARY KEY)")
        HarnessDatabase(db_path=str(db_file))
        with sqlite3.connect(str(db_file)) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert {"legacy_marker", "hitl_interactions"}.issubset(tables)


class TestCrud:
    def test_save_assigns_uuid_when_id_blank(self, hitl_db):
        row_id = hitl_db.save_interaction(make_interaction())
        assert row_id
        assert len(row_id) == 32

    def test_save_preserves_explicit_id(self, hitl_db):
        row_id = hitl_db.save_interaction(make_interaction(id="explicit-id"))
        assert row_id == "explicit-id"

    def test_save_rejects_unknown_kind(self, hitl_db):
        with pytest.raises(ValueError, match="kind"):
            hitl_db.save_interaction(make_interaction(kind="evaluation"))

    def test_save_rejects_unknown_status(self, hitl_db):
        with pytest.raises(ValueError, match="status"):
            hitl_db.save_interaction(make_interaction(status="answered"))

    def test_get_missing_returns_none(self, hitl_db):
        assert hitl_db.get_interaction("nope") is None

    def test_roundtrip_all_fields(self, hitl_db):
        original = make_interaction(id="roundtrip")
        hitl_db.save_interaction(original)
        loaded = hitl_db.get_interaction("roundtrip")
        assert loaded == original

    def test_roundtrip_blank_optionals(self, hitl_db):
        original = make_interaction(
            id="blanks",
            kind="goal",
            status="approved",
            target_action_id="",
            args_digest="",
            expires_at="",
            resolved_at=NOW,
            response="Ship the HITL MVP",
        )
        hitl_db.save_interaction(original)
        loaded = hitl_db.get_interaction("blanks")
        assert loaded == original

    def test_list_filters_by_kind_and_status(self, hitl_db):
        hitl_db.save_interaction(
            make_interaction(id="a", kind="goal", status="approved")
        )
        hitl_db.save_interaction(make_interaction(id="b", kind="approval"))
        hitl_db.save_interaction(make_interaction(id="c", kind="clarification"))
        hitl_db.save_interaction(
            make_interaction(id="other", session_id="sess-2", kind="approval")
        )
        all_rows = hitl_db.list_interactions("sess-1")
        assert [r.id for r in all_rows] == ["a", "b", "c"]
        approvals = hitl_db.list_interactions("sess-1", kind="approval")
        assert [r.id for r in approvals] == ["b"]
        pending = hitl_db.list_interactions("sess-1", status="pending")
        assert {r.id for r in pending} == {"b", "c"}

    def test_list_orders_by_created_at(self, hitl_db):
        hitl_db.save_interaction(make_interaction(id="late", created_at=LATER))
        hitl_db.save_interaction(make_interaction(id="early", created_at=NOW))
        rows = hitl_db.list_interactions("sess-1")
        assert [r.id for r in rows] == ["early", "late"]

    def test_resolve_pending_row(self, hitl_db):
        hitl_db.save_interaction(make_interaction(id="r1"))
        assert hitl_db.resolve_interaction("r1", "approved", "go ahead", LATER) is True
        loaded = hitl_db.get_interaction("r1")
        assert loaded.status == "approved"
        assert loaded.response == "go ahead"
        assert loaded.resolved_at == LATER

    def test_resolve_non_pending_row_returns_false(self, hitl_db):
        hitl_db.save_interaction(make_interaction(id="r2"))
        assert hitl_db.resolve_interaction("r2", "denied", "no", LATER) is True
        # Second transition must lose the compare-and-set: fail closed.
        assert hitl_db.resolve_interaction("r2", "approved", "yes", LATER) is False
        assert hitl_db.get_interaction("r2").status == "denied"

    def test_resolve_missing_row_returns_false(self, hitl_db):
        assert hitl_db.resolve_interaction("ghost", "approved", "", LATER) is False

    def test_resolve_rejects_pending_as_target_status(self, hitl_db):
        hitl_db.save_interaction(make_interaction(id="r3"))
        with pytest.raises(ValueError, match="status"):
            hitl_db.resolve_interaction("r3", "pending", "", LATER)

    def test_resolve_rejects_unknown_status(self, hitl_db):
        hitl_db.save_interaction(make_interaction(id="r4"))
        with pytest.raises(ValueError, match="status"):
            hitl_db.resolve_interaction("r4", "granted", "", LATER)

    def test_get_table_row_count(self, hitl_db):
        assert hitl_db.get_table_row_count("hitl_interactions") == 0
        hitl_db.save_interaction(make_interaction())
        assert hitl_db.get_table_row_count("hitl_interactions") == 1
