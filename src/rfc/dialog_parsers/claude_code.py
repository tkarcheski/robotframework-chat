"""Claude Code JSONL transcript parser (#355).

Claude Code stores one session per JSONL file under
``~/.claude/projects/<project-slug>/<session-id>.jsonl``. Each line is a
JSON object with a ``type``; only ``user`` and ``assistant`` lines carry
dialog turns (other types — ``mode``, ``attachment``,
``file-history-snapshot``, … — are bookkeeping and skipped). Sidechain
lines (``isSidechain: true``, subagent traffic) are skipped too: the
import target is the main conversation thread.

Turn mapping:

- ``user`` line, string content or ``text`` blocks  -> role ``user``
- ``user`` line containing ``tool_result`` blocks   -> role ``tool``
  (blocks land in ``tool_results_json``)
- ``assistant`` line: ``text`` blocks join into ``content``,
  ``tool_use`` blocks land in ``tool_calls_json``, ``thinking`` blocks
  are dropped; ``usage`` maps to prompt/completion token counts.

Recording metadata is fingerprinted from the lines themselves: the CLI
``version`` field, the first assistant ``model``, and session fields
(``sessionId``, ``cwd``, ``gitBranch``, ``slug``) for ``metadata_json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rfc.harness_models import DialogTurn

from .base import DialogParseError, ParsedTranscript


def _blocks(content: Any) -> list[dict[str, Any]]:
    """Normalize message content to a list of block dicts."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _text(blocks: list[dict[str, Any]]) -> str:
    return "\n".join(
        str(b.get("text", "")) for b in blocks if b.get("type") == "text"
    ).strip()


def _turn_from_line(line: dict[str, Any]) -> DialogTurn | None:
    """Map one ``user``/``assistant`` JSONL line to a DialogTurn, or None."""
    message = line.get("message")
    if not isinstance(message, dict):
        return None
    blocks = _blocks(message.get("content"))
    text = _text(blocks)
    timestamp = str(line.get("timestamp", ""))

    if line["type"] == "user":
        tool_results = [b for b in blocks if b.get("type") == "tool_result"]
        if tool_results:
            return DialogTurn(
                recording_id="",
                turn_number=0,
                role="tool",
                timestamp=timestamp,
                content=text,
                tool_results_json=json.dumps(tool_results),
            )
        if not text:
            return None
        return DialogTurn(
            recording_id="",
            turn_number=0,
            role="user",
            timestamp=timestamp,
            content=text,
        )

    tool_calls = [b for b in blocks if b.get("type") == "tool_use"]
    if not text and not tool_calls:
        return None  # e.g. thinking-only message
    usage = message.get("usage") or {}
    return DialogTurn(
        recording_id="",
        turn_number=0,
        role="assistant",
        timestamp=timestamp,
        content=text,
        tool_calls_json=json.dumps(tool_calls) if tool_calls else "",
        prompt_tokens=int(usage.get("input_tokens", -1)),
        completion_tokens=int(usage.get("output_tokens", -1)),
    )


def parse_claude_code(path: Path) -> ParsedTranscript:
    """Parse a Claude Code session JSONL export into a ParsedTranscript."""
    path = Path(path)
    if not path.is_file():
        raise DialogParseError(f"no such transcript: {path}")

    parsed = ParsedTranscript()
    metadata: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            line = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DialogParseError(f"malformed JSONL in {path}: {exc}") from exc
        if line.get("type") not in ("user", "assistant") or line.get("isSidechain"):
            continue

        if not parsed.tool_version and line.get("version"):
            parsed.tool_version = str(line["version"])
        if line.get("type") == "assistant" and not parsed.model_id:
            parsed.model_id = str((line.get("message") or {}).get("model", ""))
        for src, dst in (
            ("sessionId", "session_id"),
            ("cwd", "cwd"),
            ("gitBranch", "git_branch"),
            ("slug", "slug"),
        ):
            if line.get(src) and dst not in metadata:
                metadata[dst] = str(line[src])

        turn = _turn_from_line(line)
        if turn is None:
            continue
        turn.turn_number = len(parsed.turns) + 1
        parsed.turns.append(turn)

    if not parsed.turns:
        raise DialogParseError(f"no dialog turns found in {path}")
    parsed.started_at = parsed.turns[0].timestamp
    parsed.ended_at = parsed.turns[-1].timestamp
    parsed.metadata_json = json.dumps(metadata)
    return parsed
