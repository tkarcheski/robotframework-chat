"""Adversarial verification of RFC-008 A3 runtime provenance (test-design, #242).

These tests are the test-design sign-off for PR #292. They do NOT re-cover the
engineer's happy-path A3 tests; they attack the load-bearing honesty claims:

1. the bound acceptance criterion under *hostile* RFC_GRADER_PROMPT overrides
   (unreadable / directory / empty / content-equal-to-registered), pinning that
   the recorded hash is always the hash of the text the grader ACTUALLY runs;
2. ``params_json`` records the provider's real sampling regime and OMITS unset
   optionals (no fabricated defaults);
3. the 12-16 index alignment is held *structurally* across the SQLite physical
   column order, the SQLAlchemy Table order, and the positional row marshaller,
   so a future mid-order column insertion that silently swaps two provenance
   columns fails here;
4. migration hostility beyond the engineer's single half-migrated subset, plus
   old-reader/new-DB rollback tolerance.
"""

import json
import sqlite3

import pytest

from rfc.dialog_grader import DialogGrader
from rfc.dialog_replay import replay_prompt_mode
from rfc.grader import (
    GRADER_PROMPT_ID,
    GRADER_VERSION,
    _GRADER_PROMPT_PATH,
    _load_grader_prompt_body,
    resolved_grader_provenance,
)
from rfc.harness_db import HAS_SQLALCHEMY, HarnessDatabase
from rfc.harness_models import AgenticHarness, DialogRecording, DialogTurn
from rfc.prompt_registry import sha256_hex

NOW = "2026-07-13T00:00:00Z"

# The one canonical column order the three A3 representations must all agree on:
# the SQLite CREATE TABLE / SELECT, the SQLAlchemy Table, and _harness_from_row's
# positional indices. The provenance set occupies indices 12-16; #277's repeat_idx
# is appended at index 17, after the provenance set, so it never collides with it.
_CANONICAL_HARNESS_COLUMNS = [
    "session_id",
    "tool_name",
    "tool_version",
    "model_id",
    "rfc_version",
    "branch",
    "started_at",
    "ended_at",
    "outcome",
    "replay_of_recording_id",
    "scenario_id",
    "battery_run_id",
    "model_digest",
    "prompt_id",
    "prompt_hash",
    "grader_version",
    "params_json",
    "repeat_idx",
]
_PROVENANCE_COLUMNS = _CANONICAL_HARNESS_COLUMNS[12:17]

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


# --------------------------------------------------------------------------- #
# Local hermetic doubles (fixtures don't cross test files).
# --------------------------------------------------------------------------- #
class FakeProvider:
    """Minimal LLMProvider double: fixed replies + declared sampling attributes."""

    def __init__(self, model="fake-target"):
        self.model = model
        self.temperature = 0.0
        self.max_tokens = 256
        self.seed = None
        self.top_p = None
        self.top_k = None
        self.num_ctx = None
        self.last_metrics = None
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        self.last_metrics = {"prompt_eval_count": 11, "eval_count": 7}
        return f"fresh answer #{len(self.prompts)}"


class FakeGraderProvider(FakeProvider):
    def __init__(self):
        super().__init__(model="fake-grader")

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps({"score": 0.9, "reason": "fixed"})


@pytest.fixture()
def db(tmp_path):
    return HarnessDatabase(database_url=f"sqlite:///{tmp_path / 'h.db'}")


def _seed_recording(db, recording_id="rec-src"):
    db.save_recording(
        DialogRecording(
            id=recording_id,
            source_type="imported",
            started_at=NOW,
            tool_name="claude-code",
            model_id="original-model",
        )
    )
    db.save_turns(
        [
            DialogTurn(
                recording_id=recording_id,
                turn_number=1,
                role="user",
                timestamp=NOW,
                content="question 1",
            ),
            DialogTurn(
                recording_id=recording_id,
                turn_number=2,
                role="assistant",
                timestamp=NOW,
                content="original answer 1",
            ),
        ]
    )
    return recording_id


def _registered_hash() -> str:
    return sha256_hex(_GRADER_PROMPT_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# 1. The bound criterion under adversarial overrides.
# --------------------------------------------------------------------------- #
class TestOverrideAdversarialProvenance:
    """The seam and the grader run the SAME resolution ladder, so the recorded
    hash must always equal the hash of the text that ACTUALLY runs — under every
    hostile override the criterion (issue #242) does not enumerate."""

    def test_unreadable_override_records_the_text_that_actually_runs(
        self, tmp_path, monkeypatch
    ):
        # Override points at a nonexistent file: FileNotFoundError (an OSError) ->
        # the ladder falls through to the registered file. The row must record the
        # REGISTERED hash (what ran), never a fabricated hash of the missing path.
        monkeypatch.setenv("RFC_GRADER_PROMPT", str(tmp_path / "does-not-exist.txt"))
        pid, phash, gver = resolved_grader_provenance()
        # Honesty invariant: recorded hash == hash of the body the grader will load.
        assert phash == sha256_hex(_load_grader_prompt_body())
        assert phash == _registered_hash()
        assert pid == GRADER_PROMPT_ID
        assert gver == GRADER_VERSION

    def test_directory_override_falls_back_and_stays_honest(
        self, tmp_path, monkeypatch
    ):
        # A directory path raises IsADirectoryError (also an OSError) -> registered.
        monkeypatch.setenv("RFC_GRADER_PROMPT", str(tmp_path))
        _pid, phash, _gver = resolved_grader_provenance()
        assert phash == sha256_hex(_load_grader_prompt_body())
        assert phash == _registered_hash()

    def test_empty_env_value_is_treated_as_no_override(self, monkeypatch):
        # RFC_GRADER_PROMPT="" is falsy -> not even a candidate; registered wins.
        monkeypatch.setenv("RFC_GRADER_PROMPT", "")
        _pid, phash, _gver = resolved_grader_provenance()
        assert phash == _registered_hash()

    def test_empty_override_file_hashes_the_empty_text_that_runs(
        self, tmp_path, monkeypatch
    ):
        # A 0-byte override IS readable -> the resolved body is "" and the grader
        # would run empty. The row honestly records sha256("") — not the registered
        # coordinate, because the empty text is genuinely what ran.
        empty = tmp_path / "empty.txt"
        empty.write_text("", encoding="utf-8")
        monkeypatch.setenv("RFC_GRADER_PROMPT", str(empty))
        _pid, phash, _gver = resolved_grader_provenance()
        assert _load_grader_prompt_body() == ""
        assert phash == sha256_hex("")
        assert phash != _registered_hash()

    def test_override_equal_to_registered_is_content_not_source_addressed(
        self, tmp_path, monkeypatch
    ):
        # An override whose CONTENT equals the registered file: the coordinate is
        # content-addressed, so its hash is identical to the no-override hash. The
        # row does NOT (and must not) encode which file the text came from — two
        # runs with identical prompt text share a coordinate (RFC-008 §5/§7). This
        # locks the intended semantics against a future "distinguish source" change.
        registered_text = _GRADER_PROMPT_PATH.read_text(encoding="utf-8")
        twin = tmp_path / "twin.txt"
        twin.write_text(registered_text, encoding="utf-8")

        monkeypatch.setenv("RFC_GRADER_PROMPT", str(twin))
        _pid, override_hash, _gver = resolved_grader_provenance()
        monkeypatch.delenv("RFC_GRADER_PROMPT", raising=False)
        _pid2, registered_hash, _gver2 = resolved_grader_provenance()

        assert override_hash == registered_hash == _registered_hash()

    def test_replay_spine_row_is_honest_under_unreadable_override(
        self, db, tmp_path, monkeypatch
    ):
        # End-to-end at the real writer: an unreadable override must NOT poison the
        # spine with a bogus hash — the row records the registered text that ran.
        monkeypatch.setenv("RFC_GRADER_PROMPT", str(tmp_path / "gone.txt"))
        rec = _seed_recording(db)
        result = replay_prompt_mode(
            db,
            rec,
            target_model="target-model",
            provider=FakeProvider(),
            grader=DialogGrader(FakeGraderProvider()),
        )
        harness = db.get_harness(result.session_id)
        assert harness is not None
        assert harness.prompt_hash == _registered_hash()
        assert harness.prompt_id == GRADER_PROMPT_ID


# --------------------------------------------------------------------------- #
# 2. params_json honesty — real regime, unset optionals omitted.
# --------------------------------------------------------------------------- #
class TestParamsJsonHonesty:
    def test_unset_optionals_are_omitted_not_defaulted(self, db):
        # A blob of defaults presented as provenance would be the quiet lie. Only
        # params the provider actually declares (non-None) land; top_k/top_p/num_ctx
        # left None must be ABSENT, and the recorded values must be the provider's
        # real attributes (change temperature/seed -> the blob follows).
        provider = FakeProvider()
        provider.temperature = 0.25
        provider.max_tokens = 512
        provider.seed = 7
        # top_p / top_k / num_ctx remain None.
        rec = _seed_recording(db)
        result = replay_prompt_mode(
            db,
            rec,
            target_model="m",
            provider=provider,
            grader=DialogGrader(FakeGraderProvider()),
        )
        params = json.loads(db.get_harness(result.session_id).params_json)
        assert params == {"temperature": 0.25, "max_tokens": 512, "seed": 7}
        for omitted in ("top_p", "top_k", "num_ctx"):
            assert omitted not in params


# --------------------------------------------------------------------------- #
# 3. Structural guard for the 12-16 alignment across all three representations.
# --------------------------------------------------------------------------- #
class TestIndexAlignmentGuard:
    def test_sqlite_physical_column_order_matches_canonical(self, tmp_path):
        db_file = tmp_path / "canon.db"
        HarnessDatabase(db_path=str(db_file))
        with sqlite3.connect(str(db_file)) as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(agentic_harnesses)")]
        assert cols == _CANONICAL_HARNESS_COLUMNS
        # The provenance set sits exactly where _harness_from_row reads it (12-16).
        assert cols[12:17] == _PROVENANCE_COLUMNS

    @pytest.mark.skipif(not HAS_SQLALCHEMY, reason="sqlalchemy not installed")
    def test_sqlalchemy_table_column_order_matches_canonical(self, tmp_path):
        db = HarnessDatabase(database_url=f"sqlite:///{tmp_path / 'canon.db'}")
        # .select() returns columns in Table order, which _harness_from_row indexes
        # positionally — so the Table order MUST equal the same canonical order.
        table_cols = list(db._backend._harnesses.columns.keys())
        assert table_cols == _CANONICAL_HARNESS_COLUMNS
        assert table_cols[12:17] == _PROVENANCE_COLUMNS

    @pytest.mark.parametrize("use_url", [False, True])
    def test_distinct_sentinel_roundtrip_detects_a_column_swap(self, tmp_path, use_url):
        # Each provenance column gets a UNIQUE value, so a swap of any two (in the
        # SELECT list, the Table order, or the marshaller) reads back a wrong field
        # and fails. Runs on BOTH backends.
        if use_url and not HAS_SQLALCHEMY:
            pytest.skip("sqlalchemy not installed")
        db = (
            HarnessDatabase(database_url=f"sqlite:///{tmp_path / 'rt.db'}")
            if use_url
            else HarnessDatabase(db_path=str(tmp_path / "rt.db"))
        )
        db.save_harness(
            AgenticHarness(
                session_id="rt",
                tool_name="replay",
                started_at=NOW,
                model_digest="DIGEST_SENTINEL",
                prompt_id="PROMPT_ID_SENTINEL",
                prompt_hash="PROMPT_HASH_SENTINEL",
                grader_version="GRADER_VERSION_SENTINEL",
                params_json="PARAMS_JSON_SENTINEL",
            )
        )
        got = db.get_harness("rt")
        assert got is not None
        assert got.model_digest == "DIGEST_SENTINEL"
        assert got.prompt_id == "PROMPT_ID_SENTINEL"
        assert got.prompt_hash == "PROMPT_HASH_SENTINEL"
        assert got.grader_version == "GRADER_VERSION_SENTINEL"
        assert got.params_json == "PARAMS_JSON_SENTINEL"


# --------------------------------------------------------------------------- #
# 4. Migration hostility beyond the engineer's single subset.
# --------------------------------------------------------------------------- #
class TestMigrationHostilityExtra:
    def _seed_pre_a3(self, db_file):
        with sqlite3.connect(str(db_file)) as conn:
            conn.executescript(_PRE_A3_HARNESSES_DDL)
            conn.execute(
                "INSERT INTO agentic_harnesses "
                "(session_id, tool_name, started_at, scenario_id) VALUES (?, ?, ?, ?)",
                ("old-row", "opencode", NOW, "tier4_bug_fix"),
            )

    def test_alternate_half_migrated_subset_backfills_the_rest(self, tmp_path):
        # The engineer's half-migrated test pre-adds the FIRST two provenance
        # columns; attack a different gap — pre-add the LAST two (grader_version,
        # params_json), leaving a hole in the middle. Per-statement idempotency
        # must land model_digest/prompt_id/prompt_hash and skip the two dups.
        db_file = tmp_path / "half2.db"
        self._seed_pre_a3(db_file)
        with sqlite3.connect(str(db_file)) as conn:
            conn.execute("ALTER TABLE agentic_harnesses ADD COLUMN grader_version TEXT")
            conn.execute("ALTER TABLE agentic_harnesses ADD COLUMN params_json TEXT")
        db = HarnessDatabase(db_path=str(db_file))  # must not raise on the dup ALTERs
        with sqlite3.connect(str(db_file)) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(agentic_harnesses)")}
        assert set(_PROVENANCE_COLUMNS).issubset(cols)
        # Old row survived; new row round-trips the full coordinate.
        assert db.get_harness("old-row").scenario_id == "tier4_bug_fix"
        db.save_harness(
            AgenticHarness(
                session_id="new",
                tool_name="replay",
                started_at=NOW,
                model_digest="dg",
                prompt_hash="hh",
                grader_version="gv",
                params_json="{}",
            )
        )
        new = db.get_harness("new")
        assert new.model_digest == "dg"
        assert new.prompt_hash == "hh"
        assert new.grader_version == "gv"

    def test_old_reader_tolerates_new_columns_rollback_direction(self, tmp_path):
        # Old-code/new-DB rollback: a reader that SELECTs only the pre-A3 12 columns
        # against a full 17-column DB is unaffected — the provenance columns are
        # purely additive and never shift or break a narrower explicit-column read.
        db_file = tmp_path / "fwd.db"
        db = HarnessDatabase(db_path=str(db_file))
        db.save_harness(
            AgenticHarness(
                session_id="s",
                tool_name="replay",
                started_at=NOW,
                battery_run_id="batt",
                model_digest="dg",
                prompt_hash="hh",
            )
        )
        with sqlite3.connect(str(db_file)) as conn:
            row = conn.execute(
                "SELECT session_id, tool_name, tool_version, model_id, rfc_version, "
                "branch, started_at, ended_at, outcome, replay_of_recording_id, "
                "scenario_id, battery_run_id FROM agentic_harnesses "
                "WHERE session_id = ?",
                ("s",),
            ).fetchone()
        assert len(row) == 12  # narrow reader sees exactly its known columns
        assert row[0] == "s"
        assert row[11] == "batt"
