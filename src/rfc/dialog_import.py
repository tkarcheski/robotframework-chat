"""``rfc dialog import`` — external transcript ingestion (#355).

Reads an agent tool's own session export (e.g. a Claude Code JSONL
file), parses it with the tool's registered parser
(:mod:`rfc.dialog_parsers`), and lands the conversation in the
``dialog_recordings`` / ``dialog_turns`` tables with
``source_type='imported'`` so laptop sessions can be replayed under
different harness variables later.

Tool/model metadata is fingerprinted from the transcript header where
available and falls back to the CLI flags. ``--session-id`` is
optional: omitted, the recording is written unattached and can be
linked to a harness session later.

Unlike the DialogListener (skip-and-log), a missing database is a hard
failure here — the DB write is the entire point of the command.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from rfc.dialog_parsers import get_parser
from rfc.dialog_parsers.base import DialogParseError
from rfc.harness_models import DialogRecording


def _utc_now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z"


def _resolve_database_url(database_url: str = "") -> str:
    """Flag > DIALOG_DATABASE_URL > DATABASE_URL (DialogListener precedence)."""
    return (
        database_url
        or os.environ.get("DIALOG_DATABASE_URL", "")
        or os.environ.get("DATABASE_URL", "")
    )


def import_transcript(
    path: Path,
    tool: str,
    *,
    session_id: str = "",
    model: str = "",
    tool_version: str = "",
    database_url: str = "",
) -> str:
    """Import one transcript file; return the new recording id.

    Raises ``UnknownDialogToolError`` for unregistered tools,
    ``NotImplementedError`` for stub parsers, ``DialogParseError`` for
    bad files, and ``RuntimeError`` when no database is configured.
    """
    parser = get_parser(tool)
    parsed = parser(Path(path))

    url = _resolve_database_url(database_url)
    if not url:
        raise RuntimeError(
            "no database configured — pass --database-url or set "
            "DIALOG_DATABASE_URL / DATABASE_URL. The dialog_recordings row "
            "is the point of `dialog import`, so this is a hard failure."
        )
    from rfc.harness_db import HarnessDatabase  # deferred like harness_cli

    db = HarnessDatabase(database_url=url)

    recording_id = uuid.uuid4().hex
    db.save_recording(
        DialogRecording(
            id=recording_id,
            source_type="imported",
            started_at=parsed.started_at or _utc_now(),
            session_id=session_id,
            tool_name=tool,
            tool_version=parsed.tool_version or tool_version,
            model_id=parsed.model_id or model,
            metadata_json=parsed.metadata_json,
        )
    )
    for turn in parsed.turns:
        turn.recording_id = recording_id
    db.save_turns(parsed.turns)
    if parsed.ended_at:
        db.end_recording(recording_id, parsed.ended_at)
    return recording_id


def _cmd_import(args: argparse.Namespace) -> int:
    if not _resolve_database_url(args.database_url):
        print(
            "ERROR: no database configured — pass --database-url or set "
            "DIALOG_DATABASE_URL / DATABASE_URL.",
            file=sys.stderr,
        )
        return 2
    try:
        recording_id = import_transcript(
            Path(args.path),
            args.tool,
            session_id=args.session_id,
            model=args.model,
            tool_version=args.tool_version,
            database_url=args.database_url,
        )
    except (DialogParseError, NotImplementedError, LookupError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    attachment = f"session {args.session_id}" if args.session_id else "unattached"
    print(
        json.dumps(
            {
                "imported": True,
                "recording_id": recording_id,
                "tool": args.tool,
                "attachment": attachment,
            },
            indent=2,
        )
    )
    return 0


def register_dialog_command(commands: argparse._SubParsersAction) -> None:
    """Attach the ``dialog`` subcommand to the ``rfc`` CLI parser."""
    from rfc.dialog_parsers import SUPPORTED_TOOLS  # local to avoid cycles
    from rfc.dialog_replay import register_replay_command  # local to avoid cycles

    dialog = commands.add_parser("dialog", help="dialog recording tools")
    actions = dialog.add_subparsers(dest="action", required=True)

    imp = actions.add_parser(
        "import", help="ingest an external agent-tool transcript export"
    )
    imp.add_argument("path", help="path to the transcript file (e.g. JSONL export)")
    imp.add_argument("--tool", required=True, choices=SUPPORTED_TOOLS)
    imp.add_argument(
        "--session-id",
        default="",
        help="attach the recording to an existing harness session (optional)",
    )
    imp.add_argument(
        "--model", default="", help="model id fallback if absent from the transcript"
    )
    imp.add_argument(
        "--tool-version",
        default="",
        help="tool version fallback if absent from the transcript",
    )
    imp.add_argument("--database-url", default="")
    imp.set_defaults(func=_cmd_import)

    register_replay_command(actions)
