"""``rfc harness start | end | status`` — session bracketing CLI.

One Claude-Code / Codex / OpenCode session = one feature branch
(CLAUDE.md "one branch per session"). ``start`` generates the
session_id UUID, snapshots plugins and skills, writes the
agentic_harnesses row, and persists session info to a per-worktree
sidecar (``.git/rfc-harness-session.json``) so subsequent Robot/pytest
runs can attach to it. ``end`` closes the row and removes the sidecar.

DB-write failures are skip-and-log (the sidecar still brackets the
session locally); only a missing database URL is a hard failure.
"""

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, Optional

from rfc import __version__
from rfc.dialog_import import register_dialog_command
from rfc.git_metadata import _git_command, collect_ci_metadata
from rfc.harness_models import (
    METRIC_CACHE_HIT_RATE,
    METRIC_SUITE_RUNTIME_MS,
    AgenticHarness,
)
from rfc.harness_snapshot import snapshot_plugins, snapshot_skills

if TYPE_CHECKING:
    from rfc.harness_db import HarnessDatabase

SIDECAR_NAME = "rfc-harness-session.json"
TOOLS = ("claude-code", "codex", "opencode")

# Tool name (our taxonomy) -> executable probed for --version. claude-code
# installs the `claude` binary (https://docs.claude.com/en/docs/claude-code/cli-reference).
_TOOL_EXECUTABLES = {"claude-code": "claude"}


def _sidecar_path() -> Path:
    """Locate the per-worktree sidecar inside the current .git dir."""
    git_dir = _git_command("rev-parse", "--absolute-git-dir")
    if not git_dir:
        raise RuntimeError("not inside a git repository")
    return Path(git_dir) / SIDECAR_NAME


def _utc_now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z"


def _tool_version(tool: str, explicit: str, probe: bool = True) -> str:
    """Use the explicit version, falling back to ``<executable> --version``.

    ``probe=False`` (the ``--no-version-probe`` flag) skips the subprocess
    fallback entirely.
    """
    if explicit:
        return explicit
    if not probe:
        return ""
    executable = _TOOL_EXECUTABLES.get(tool, tool)
    try:
        result = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return ""


def _open_db(database_url: str):  # type: ignore[no-untyped-def]
    """Open HarnessDatabase from flag or DATABASE_URL; None if URL unset.

    Import is deferred so ``status`` works without DB extras installed.
    """
    from rfc.harness_db import HarnessDatabase

    url = database_url or os.environ.get("DATABASE_URL", "")
    if not url:
        return None
    return HarnessDatabase(database_url=url)


def _cmd_start(args: argparse.Namespace) -> int:
    sidecar = _sidecar_path()
    previous_session_id = ""
    if sidecar.exists():
        if not args.force_overwrite:
            print(
                f"ERROR: active session already recorded in {sidecar}; "
                "use --force-overwrite to replace it.",
                file=sys.stderr,
            )
            return 1
        previous_session_id = json.loads(sidecar.read_text()).get("session_id", "")

    url = args.database_url or os.environ.get("DATABASE_URL", "")
    if not url:
        print(
            "ERROR: no database configured — pass --database-url or set "
            "DATABASE_URL. The harness row is the point of `harness start`, "
            "so this is a hard failure.",
            file=sys.stderr,
        )
        return 2

    session_id = uuid.uuid4().hex
    started_at = _utc_now()
    tool_version = _tool_version(
        args.tool, args.tool_version, probe=not args.no_version_probe
    )
    harness = AgenticHarness(
        session_id=session_id,
        tool_name=args.tool,
        started_at=started_at,
        tool_version=tool_version,
        model_id=args.model or os.environ.get("DEFAULT_MODEL", ""),
        rfc_version=__version__,
        branch=collect_ci_metadata().get("Branch", ""),
        replay_of_recording_id=args.replay_of,
    )

    try:
        db = _open_db(url)
        assert db is not None  # url checked above
        if previous_session_id:
            db.end_harness(previous_session_id, "abandoned", started_at)
        db.save_harness(harness)
        db.save_plugins(snapshot_plugins(session_id, started_at))
        repo_root = _git_command("rev-parse", "--show-toplevel") or "."
        db.save_skills(snapshot_skills(session_id, started_at, repo_root=repo_root))
    except Exception as exc:  # noqa: BLE001 — skip-and-log per CLAUDE.md
        print(
            f"WARN: skipping DB write ({exc}); session is still bracketed "
            "by the local sidecar.",
            file=sys.stderr,
        )

    sidecar.write_text(
        json.dumps(
            {
                "session_id": session_id,
                "tool_name": args.tool,
                "tool_version": tool_version,
                "started_at": started_at,
            },
            indent=2,
        )
    )
    print(f"started session {session_id} ({args.tool}) — sidecar: {sidecar}")
    return 0


def _cmd_end(args: argparse.Namespace) -> int:
    sidecar = _sidecar_path()
    if not sidecar.exists():
        print("ERROR: no active session (sidecar not found).", file=sys.stderr)
        return 1
    session = json.loads(sidecar.read_text())
    ended_at = _utc_now()
    try:
        db = _open_db(args.database_url)
        if db is None:
            print(
                "WARN: skipping DB update (no database configured); "
                "removing sidecar only.",
                file=sys.stderr,
            )
        else:
            db.end_harness(session["session_id"], args.outcome, ended_at)
    except Exception as exc:  # noqa: BLE001 — skip-and-log per CLAUDE.md
        print(f"WARN: skipping DB update ({exc}).", file=sys.stderr)
    sidecar.unlink()
    print(f"ended session {session['session_id']} — outcome: {args.outcome}")
    return 0


def _cmd_status(_args: argparse.Namespace) -> int:
    sidecar = _sidecar_path()
    if not sidecar.exists():
        print("no active session")
        return 0
    session = json.loads(sidecar.read_text())
    print(
        f"active session {session['session_id']}\n"
        f"  tool:       {session['tool_name']} {session['tool_version']}\n"
        f"  started_at: {session['started_at']}\n"
        f"  sidecar:    {sidecar}"
    )
    return 0


class EfficiencySummary(NamedTuple):
    """Per-session rollup of the RFC-010 S1 efficiency metrics (#258)."""

    cache_hit_rate: Optional[float]  # mean per-run rate; None if never recorded
    cache_runs: int  # number of runs that contributed a cache_hit_rate
    suite_runtime_ms: Optional[float]  # total wall time; None if never recorded
    suites: int  # number of suites that contributed a runtime


def summarize_efficiency(db: "HarnessDatabase", session_id: str) -> EfficiencySummary:
    """Aggregate the efficiency EAV rows for *session_id*.

    Mirrors the ``agentic_sessions_full`` pivot: ``cache_hit_rate`` is averaged
    (mean per-run rate) and ``suite_runtime_ms`` is summed (total wall time
    across the session's suites). Reads through the same ``get_metrics`` API
    every other metric consumer uses.
    """
    rates = [
        m.metric_value
        for m in db.get_metrics(session_id, metric_key=METRIC_CACHE_HIT_RATE)
    ]
    runtimes = [
        m.metric_value
        for m in db.get_metrics(session_id, metric_key=METRIC_SUITE_RUNTIME_MS)
    ]
    return EfficiencySummary(
        cache_hit_rate=(sum(rates) / len(rates)) if rates else None,
        cache_runs=len(rates),
        suite_runtime_ms=sum(runtimes) if runtimes else None,
        suites=len(runtimes),
    )


def _cmd_scoreboard(args: argparse.Namespace) -> int:
    """Print the efficiency scoreboard for a session (RFC-010 S1, #258)."""
    session_id = args.session or active_session_id()
    if not session_id:
        print(
            "ERROR: no session (pass --session or start one with `rfc harness start`).",
            file=sys.stderr,
        )
        return 1
    db = _open_db(args.database_url)
    if db is None:
        print(
            "ERROR: no database configured (set DATABASE_URL or --database-url).",
            file=sys.stderr,
        )
        return 1
    summary = summarize_efficiency(db, session_id)
    print(f"efficiency scoreboard — session {session_id}")
    if summary.cache_hit_rate is None and summary.suite_runtime_ms is None:
        print("  (no efficiency metrics recorded yet)")
        return 0
    if summary.cache_hit_rate is None:
        print("  cache_hit_rate:   n/a")
    else:
        print(
            f"  cache_hit_rate:   {summary.cache_hit_rate:.3f}"
            f"  (mean of {summary.cache_runs} run(s))"
        )
    if summary.suite_runtime_ms is None:
        print("  suite_runtime_ms: n/a")
    else:
        print(
            f"  suite_runtime_ms: {summary.suite_runtime_ms:.1f}"
            f"  (total of {summary.suites} suite(s))"
        )
    return 0


def _cmd_cache_invalidate(args: argparse.Namespace) -> int:
    """Bust cached answers by scope (RFC-010 S4, #262).

    Reuses the version namespace as the bust lever: ``--all`` flushes every
    namespace, otherwise a single version (default: the current schema version)
    is deleted. ``--dry-run`` reports the match count without deleting. A Redis
    outage is a loud failure here — an operator running an explicit invalidation
    must not be told "0 keys" as if the cache were already clean.
    """
    import redis

    from rfc.answer_cache import AnswerCache

    cache = AnswerCache.from_env()
    # Default (no --version) busts the namespace the cache is ACTUALLY on —
    # ``cache.version`` honors ANSWER_CACHE_VERSION, resolved by from_env — not
    # the compiled-in DEFAULT_VERSION. Reading the constant would delete the
    # wrong namespace whenever an operator set the documented version knob, and
    # print a confident "deleted N key(s)" for a bust that never touched the
    # live cache (RFC-010's cache-honesty thesis, applied to invalidation).
    version = None if args.all else (args.version or cache.version)
    try:
        matched = cache.invalidate(version=version, dry_run=args.dry_run)
    except (redis.RedisError, OSError) as exc:
        print(
            f"ERROR: could not reach the answer cache ({exc}); nothing invalidated.",
            file=sys.stderr,
        )
        return 1
    scope = "all namespaces" if version is None else f"namespace {version}"
    verb = "would delete" if args.dry_run else "deleted"
    print(f"answer cache: {verb} {matched} key(s) ({scope}).")
    return 0


def active_session_id() -> str:
    """The sidecar's session_id, or '' when no session is active.

    Safe to call outside a git repository or with a corrupt sidecar —
    both simply mean "no active session".
    """
    try:
        sidecar = _sidecar_path()
        if sidecar.exists():
            return str(json.loads(sidecar.read_text()).get("session_id", ""))
    except (RuntimeError, OSError, json.JSONDecodeError):
        pass
    return ""


def makefile_session_id() -> str:
    """SESSION_ID for the Makefile: the active sidecar's ID, else a fresh UUID.

    This is how `rfc harness start` attaches subsequent ``make robot`` runs
    to the open harness row (Issue #411): the Makefile calls this instead of
    generating an unconditional UUID. Outside a git repo, or with no active
    session, behaviour is unchanged (fresh UUID per invocation).
    """
    return active_session_id() or uuid.uuid4().hex


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rfc", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    harness = commands.add_parser("harness", help="agent session bracketing")
    actions = harness.add_subparsers(dest="action", required=True)

    start = actions.add_parser("start", help="open a session")
    start.add_argument("--tool", required=True, choices=TOOLS)
    start.add_argument("--tool-version", default="")
    start.add_argument("--model", default="")
    start.add_argument(
        "--replay-of",
        default="",
        help=(
            "recording id this session replays (RFC-010 S3, #261); stamps "
            "agentic_harnesses.replay_of_recording_id so a replayed run is never "
            "mistaken for a fresh live pass"
        ),
    )
    start.add_argument("--database-url", default="")
    start.add_argument("--force-overwrite", action="store_true")
    start.add_argument(
        "--no-version-probe",
        action="store_true",
        help="do not run `<tool> --version` to detect the tool version",
    )
    start.set_defaults(func=_cmd_start)

    end = actions.add_parser("end", help="close the active session")
    end.add_argument(
        "--outcome", default="success", choices=("success", "partial", "failed")
    )
    end.add_argument("--database-url", default="")
    end.set_defaults(func=_cmd_end)

    status = actions.add_parser("status", help="show the active session")
    status.set_defaults(func=_cmd_status)

    scoreboard = actions.add_parser(
        "scoreboard", help="print a session's efficiency metrics (RFC-010 S1)"
    )
    scoreboard.add_argument(
        "--session", default="", help="session_id (default: active sidecar)"
    )
    scoreboard.add_argument("--database-url", default="")
    scoreboard.set_defaults(func=_cmd_scoreboard)

    cache = commands.add_parser("cache", help="answer-cache maintenance (RFC-010 S4)")
    cache_actions = cache.add_subparsers(dest="action", required=True)
    invalidate = cache_actions.add_parser(
        "invalidate", help="bust cached answers by scope (version namespace or all)"
    )
    scope = invalidate.add_mutually_exclusive_group()
    scope.add_argument(
        "--all",
        action="store_true",
        help="delete every namespace (rfc:answer_cache:*), not just one version",
    )
    scope.add_argument(
        "--version",
        default="",
        help="version namespace to bust (default: the current schema version)",
    )
    invalidate.add_argument(
        "--dry-run",
        action="store_true",
        help="report how many keys match without deleting them",
    )
    invalidate.set_defaults(func=_cmd_cache_invalidate)

    register_dialog_command(commands)
    return parser


def main(argv: "list[str] | None" = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
