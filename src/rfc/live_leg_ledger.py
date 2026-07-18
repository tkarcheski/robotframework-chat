"""Skip-streak ledger + gate for the live opencode enforcement legs (#394).

Two "real-proof" live legs certify opencode's routed permission enforcement
against the REAL CLI + local model, on top of the deterministic fixture/resolver
proofs that categorically close the defect classes:

  * ``opencode_host_leak_ab`` -- ``TestOpenCodeHostLeakABDirtyEnv``: a routed
    ``permission.bash=deny`` at the cwd tier must stop native host bash from
    reading a host-only marker under an adversarial ancestor
    (``test_opencode_config_precedence.py``).
  * ``opencode_returncode_390`` -- ``TestLiveOpenCodeReturncode390``: the parser
    must record a completed-but-nonzero shell exit as red
    (``test_harness_adapters.py``).

Both skip cleanly per run when the box cannot conclude them under model/compute
contention. That is acceptable once -- but a config regression could then leave
a leg perpetually skipped with no live enforcement proof on record. This ledger
records each leg's per-run outcome (executed vs skipped) on a box that is
CAPABLE of running it, tracks the consecutive-skip streak, and exposes a gate
that fails when a leg has skipped for N consecutive runs. Per the #394 owner
ruling the requirement is visibility, not blocking: an individual skip is
tolerated; a long silent streak is surfaced so a serialized/uncontended gate can
restore the live proof.

Outcomes are recorded only from inside a leg's body -- i.e. only once the box has
already been found capable (opencode CLI + local model present, not opted out).
A box that simply lacks opencode never records, so its "run where the tool
exists, skip elsewhere" contract never pollutes the streak.

The ledger persists as JSON under ``~/.rfc/`` (override with
``RFC_LIVE_LEG_LEDGER``); the streak threshold defaults to
:data:`DEFAULT_MAX_SKIP_STREAK` (override with ``RFC_LIVE_LEG_MAX_SKIP_STREAK``).
Run the gate as ``python -m rfc.live_leg_ledger check`` (``make live-leg-gate``).
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_MAX_SKIP_STREAK = 10

# The registered real-proof live legs folded into a single gate (#394 owner
# ruling: neither may silently vanish).
LIVE_LEGS: tuple[str, ...] = (
    "opencode_host_leak_ab",
    "opencode_returncode_390",
)


@dataclass
class LegRecord:
    """Persisted skip-streak state for one live enforcement leg."""

    leg: str
    consecutive_skips: int = 0
    last_outcome: str = ""  # "executed" | "skipped" | ""
    last_updated: str = ""
    total_runs: int = 0
    total_skips: int = 0


def ledger_path() -> Path:
    """Resolve the ledger file path (``RFC_LIVE_LEG_LEDGER`` overrides default)."""
    override = os.environ.get("RFC_LIVE_LEG_LEDGER")
    if override:
        return Path(override)
    return Path.home() / ".rfc" / "live_leg_ledger.json"


def max_skip_streak() -> int:
    """Resolve the consecutive-skip threshold that trips the gate."""
    raw = os.environ.get("RFC_LIVE_LEG_MAX_SKIP_STREAK")
    if not raw:
        return DEFAULT_MAX_SKIP_STREAK
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_SKIP_STREAK
    return value if value > 0 else DEFAULT_MAX_SKIP_STREAK


def load_ledger(path: Path | None = None) -> dict[str, LegRecord]:
    """Load the ledger; a missing or corrupt file reads as empty (never raises)."""
    path = path or ledger_path()
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    records: dict[str, LegRecord] = {}
    for leg, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        records[str(leg)] = LegRecord(
            leg=str(leg),
            consecutive_skips=int(entry.get("consecutive_skips", 0)),
            last_outcome=str(entry.get("last_outcome", "")),
            last_updated=str(entry.get("last_updated", "")),
            total_runs=int(entry.get("total_runs", 0)),
            total_skips=int(entry.get("total_skips", 0)),
        )
    return records


def _write_ledger(records: dict[str, LegRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {leg: asdict(rec) for leg, rec in records.items()}
    # Atomic replace so an interrupted write never corrupts the ledger.
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def record_outcome(leg: str, executed: bool, path: Path | None = None) -> LegRecord:
    """Record one run's outcome for ``leg`` and return its updated record.

    An executed run resets the consecutive-skip streak to zero; a skipped run
    increments it. Call only when the box is capable of running the leg.
    """
    path = path or ledger_path()
    records = load_ledger(path)
    rec = records.get(leg) or LegRecord(leg=leg)
    rec.total_runs += 1
    if executed:
        rec.consecutive_skips = 0
        rec.last_outcome = "executed"
    else:
        rec.consecutive_skips += 1
        rec.total_skips += 1
        rec.last_outcome = "skipped"
    rec.last_updated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records[leg] = rec
    _write_ledger(records, path)
    return rec


def safe_record_outcome(leg: str, executed: bool) -> None:
    """Best-effort :func:`record_outcome`; bookkeeping never fails a live leg."""
    try:
        record_outcome(leg, executed)
    except Exception:  # pragma: no cover - ledger IO is non-critical to the proof
        pass


def check_streaks(
    path: Path | None = None,
    threshold: int | None = None,
    legs: tuple[str, ...] = LIVE_LEGS,
) -> list[str]:
    """Return one breach message per leg whose streak >= threshold (empty = ok).

    Legs that have never recorded on this box are ignored: a box that cannot run
    a leg at all is not the silent-regression case the gate guards against.
    """
    threshold = threshold if threshold is not None else max_skip_streak()
    records = load_ledger(path)
    breaches: list[str] = []
    for leg in legs:
        rec = records.get(leg)
        if rec is None:
            continue
        if rec.consecutive_skips >= threshold:
            breaches.append(
                f"{leg}: skipped {rec.consecutive_skips} consecutive runs "
                f"(threshold {threshold}); last outcome {rec.last_outcome or 'n/a'} "
                f"at {rec.last_updated or 'unknown'}. Run it non-skipped on an "
                "uncontended/serialized gate to restore the live enforcement proof."
            )
    return breaches


def _print_report(records: dict[str, LegRecord]) -> None:
    for leg in LIVE_LEGS:
        rec = records.get(leg)
        if rec is None:
            print(f"  {leg}: no runs recorded on this box")
            continue
        print(
            f"  {leg}: streak={rec.consecutive_skips} "
            f"last={rec.last_outcome or 'n/a'} runs={rec.total_runs} "
            f"skips={rec.total_skips} updated={rec.last_updated or 'n/a'}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m rfc.live_leg_ledger",
        description=("Skip-streak gate for the live opencode enforcement legs (#394)."),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser(
        "check", help="fail if a leg has skipped for N consecutive runs"
    )
    p_check.add_argument(
        "--threshold",
        type=int,
        default=None,
        help="override the consecutive-skip threshold (default: env or 10)",
    )

    p_record = sub.add_parser(
        "record", help="record a single leg outcome (for the fleet/testing)"
    )
    p_record.add_argument("--leg", required=True, help="live leg id")
    outcome = p_record.add_mutually_exclusive_group(required=True)
    outcome.add_argument(
        "--executed", action="store_true", help="the leg ran a real assertion"
    )
    outcome.add_argument(
        "--skipped", action="store_true", help="the leg skipped this run"
    )

    args = parser.parse_args(argv)

    if args.command == "record":
        rec = record_outcome(args.leg, executed=bool(args.executed))
        print(f"recorded {rec.leg}: streak={rec.consecutive_skips}")
        return 0

    threshold = args.threshold if args.threshold is not None else max_skip_streak()
    print(f"live-leg skip-streak gate (threshold {threshold}):")
    _print_report(load_ledger())
    breaches = check_streaks(threshold=threshold)
    if breaches:
        print("FAIL: live enforcement leg(s) skipped too many consecutive runs:")
        for breach in breaches:
            print(f"  - {breach}")
        return 1
    print("OK: no live enforcement leg has exceeded the skip-streak threshold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
