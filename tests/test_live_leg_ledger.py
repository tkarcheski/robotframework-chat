"""Deterministic tests for the #394 live-leg skip-streak ledger + gate.

The live enforcement legs themselves (``TestOpenCodeHostLeakABDirtyEnv`` and
``TestLiveOpenCodeReturncode390``) need a real opencode CLI + local model, so
they skip on a bare CI box. This module tests the ledger/gate *mechanism* they
feed -- consecutive-skip accounting, the threshold gate, and the CLI -- with no
CLI, model, or network, so the safeguard is itself always covered.
"""

from __future__ import annotations

import json
from pathlib import Path

from rfc.live_leg_ledger import (
    DEFAULT_MAX_SKIP_STREAK,
    LIVE_LEGS,
    check_streaks,
    ledger_path,
    load_ledger,
    main,
    max_skip_streak,
    record_outcome,
    safe_record_outcome,
)

_LEG = LIVE_LEGS[0]


def _ledger(tmp_path: Path) -> Path:
    return tmp_path / "live_leg_ledger.json"


def test_skip_increments_and_execute_resets_streak(tmp_path: Path) -> None:
    path = _ledger(tmp_path)
    assert record_outcome(_LEG, executed=False, path=path).consecutive_skips == 1
    assert record_outcome(_LEG, executed=False, path=path).consecutive_skips == 2
    rec = record_outcome(_LEG, executed=True, path=path)
    assert rec.consecutive_skips == 0
    assert rec.last_outcome == "executed"
    assert rec.total_runs == 3
    assert rec.total_skips == 2


def test_check_streaks_reports_leg_at_or_over_threshold(tmp_path: Path) -> None:
    path = _ledger(tmp_path)
    for _ in range(3):
        record_outcome(_LEG, executed=False, path=path)
    assert check_streaks(path=path, threshold=4) == []  # 3 < 4: below
    record_outcome(_LEG, executed=False, path=path)  # now 4
    breaches = check_streaks(path=path, threshold=4)
    assert len(breaches) == 1
    assert _LEG in breaches[0]
    assert "uncontended/serialized gate" in breaches[0]


def test_execute_clears_a_breach(tmp_path: Path) -> None:
    path = _ledger(tmp_path)
    for _ in range(5):
        record_outcome(_LEG, executed=False, path=path)
    assert check_streaks(path=path, threshold=3)
    record_outcome(_LEG, executed=True, path=path)
    assert check_streaks(path=path, threshold=3) == []


def test_check_streaks_ignores_never_recorded_and_empty(tmp_path: Path) -> None:
    # A box that has never run the legs (empty/absent ledger) is not the
    # silent-regression case -- the gate stays green (visibility, not blocking).
    assert check_streaks(path=_ledger(tmp_path), threshold=1) == []


def test_load_ledger_on_missing_or_corrupt_file_is_empty(tmp_path: Path) -> None:
    assert load_ledger(_ledger(tmp_path)) == {}
    corrupt = _ledger(tmp_path)
    corrupt.write_text("{ not json")
    assert load_ledger(corrupt) == {}


def test_ledger_persists_all_registered_legs_independently(tmp_path: Path) -> None:
    path = _ledger(tmp_path)
    record_outcome(LIVE_LEGS[0], executed=False, path=path)
    record_outcome(LIVE_LEGS[1], executed=True, path=path)
    records = load_ledger(path)
    assert records[LIVE_LEGS[0]].consecutive_skips == 1
    assert records[LIVE_LEGS[1]].consecutive_skips == 0


def test_ledger_path_honors_env_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("RFC_LIVE_LEG_LEDGER", raising=False)
    assert ledger_path() == Path.home() / ".rfc" / "live_leg_ledger.json"
    target = tmp_path / "custom.json"
    monkeypatch.setenv("RFC_LIVE_LEG_LEDGER", str(target))
    assert ledger_path() == target


def test_max_skip_streak_env_override(monkeypatch) -> None:
    monkeypatch.delenv("RFC_LIVE_LEG_MAX_SKIP_STREAK", raising=False)
    assert max_skip_streak() == DEFAULT_MAX_SKIP_STREAK
    monkeypatch.setenv("RFC_LIVE_LEG_MAX_SKIP_STREAK", "3")
    assert max_skip_streak() == 3
    # Non-positive / non-numeric fall back to the default rather than disabling.
    monkeypatch.setenv("RFC_LIVE_LEG_MAX_SKIP_STREAK", "0")
    assert max_skip_streak() == DEFAULT_MAX_SKIP_STREAK
    monkeypatch.setenv("RFC_LIVE_LEG_MAX_SKIP_STREAK", "nope")
    assert max_skip_streak() == DEFAULT_MAX_SKIP_STREAK


def test_safe_record_outcome_never_raises(monkeypatch, tmp_path: Path) -> None:
    # Point the ledger at a path whose parent is a file, so a write is impossible;
    # bookkeeping must swallow it rather than fail the live leg.
    wall = tmp_path / "wall"
    wall.write_text("x")
    monkeypatch.setenv("RFC_LIVE_LEG_LEDGER", str(wall / "ledger.json"))
    safe_record_outcome(_LEG, executed=False)  # must not raise


def test_cli_check_fails_at_threshold_then_passes_after_execute(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    path = _ledger(tmp_path)
    monkeypatch.setenv("RFC_LIVE_LEG_LEDGER", str(path))
    monkeypatch.setenv("RFC_LIVE_LEG_MAX_SKIP_STREAK", "2")

    assert main(["record", "--leg", _LEG, "--skipped"]) == 0
    assert main(["record", "--leg", _LEG, "--skipped"]) == 0  # streak now 2

    assert main(["check"]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and _LEG in out

    assert main(["record", "--leg", _LEG, "--executed"]) == 0
    assert main(["check"]) == 0
    assert "OK" in capsys.readouterr().out


def test_cli_check_threshold_flag_overrides_env(monkeypatch, tmp_path: Path) -> None:
    path = _ledger(tmp_path)
    monkeypatch.setenv("RFC_LIVE_LEG_LEDGER", str(path))
    for _ in range(3):
        record_outcome(_LEG, executed=False, path=path)
    assert main(["check", "--threshold", "10"]) == 0
    assert main(["check", "--threshold", "3"]) == 1


def test_written_ledger_is_valid_json_with_expected_fields(tmp_path: Path) -> None:
    path = _ledger(tmp_path)
    record_outcome(_LEG, executed=False, path=path)
    payload = json.loads(path.read_text())
    entry = payload[_LEG]
    assert entry["consecutive_skips"] == 1
    assert entry["last_outcome"] == "skipped"
    assert entry["last_updated"]
