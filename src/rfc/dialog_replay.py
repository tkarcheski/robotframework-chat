"""``rfc dialog replay`` — prompt-mode replay engine (#356).

Walks the ``role='user'`` turns of a recorded dialog
(``dialog_recordings`` / ``dialog_turns``), re-prompts a target model
via :func:`rfc.llm_client.create_provider`, and grades each fresh
response against the originally recorded assistant response with the
``Grade Answer`` machinery (:class:`rfc.dialog_grader.DialogGrader`).

Each replay opens a new ``agentic_harnesses`` row whose
``replay_of_recording_id`` points at the source recording (the schema's
name for the issue's ``replay_of_workflow_id``), so the dashboard's
harness comparison table can A/B different configurations of the same
task. The fresh responses are captured as a *new* recording
(``source_type='replay'``) so the replay itself is replayable, and
per-turn ``grader_score`` / ``tokens_in`` / ``tokens_out`` /
``latency_ms`` rows land in ``agentic_metrics``.

Like ``rfc dialog import``, a missing database is a hard failure —
the DB rows are the entire point of the command.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Optional

from rfc import __version__
from rfc.dialog_grader import DialogGrader
from rfc.git_metadata import collect_ci_metadata
from rfc.harness_db import HarnessDatabase
from rfc.harness_models import (
    AgenticHarness,
    AgenticMetric,
    DialogRecording,
    DialogTurn,
)
from rfc.llm_client import LLMProvider, create_provider

REPLAY_MODES = ("prompt",)
SUCCESS_THRESHOLD = 0.8
PARTIAL_THRESHOLD = 0.5


def _utc_now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z"


def derive_outcome(aggregate_score: float) -> str:
    """Map an aggregate grader score onto a harness outcome.

    ``success`` at >= 0.8, ``partial`` at >= 0.5, else ``failed``.
    """
    if aggregate_score >= SUCCESS_THRESHOLD:
        return "success"
    if aggregate_score >= PARTIAL_THRESHOLD:
        return "partial"
    return "failed"


@dataclass
class TurnReplay:
    """One replayed user turn: fresh response plus its grade and costs."""

    turn_number: int  # turn_number of the user turn in the SOURCE recording
    prompt: str
    original_response: str
    new_response: str
    score: float
    reason: str
    tokens_in: int = -1  # -1 sentinel = provider reported no usage
    tokens_out: int = -1
    latency_ms: float = 0.0


@dataclass
class ReplayResult:
    """Everything a caller needs to locate and judge one replay run."""

    session_id: str
    source_recording_id: str
    new_recording_id: str
    target_model: str
    mode: str
    outcome: str
    aggregate_score: float
    turns: list[TurnReplay] = field(default_factory=list)


def _original_response_for(turns: list[DialogTurn], user_index: int) -> str:
    """The first assistant turn following ``turns[user_index]``, or ''."""
    for turn in turns[user_index + 1 :]:
        if turn.role == "assistant":
            return turn.content
        if turn.role == "user":
            break
    return ""


def _provider_token_counts(provider: LLMProvider) -> tuple[int, int]:
    """(tokens_in, tokens_out) from the provider's last_metrics, -1 unknown.

    Both Ollama and OpenAI providers expose Ollama-style
    ``prompt_eval_count`` / ``eval_count`` keys in ``last_metrics``.
    """
    metrics = provider.last_metrics or {}
    tokens_in = metrics.get("prompt_eval_count")
    tokens_out = metrics.get("eval_count")
    return (
        int(tokens_in) if tokens_in is not None else -1,
        int(tokens_out) if tokens_out is not None else -1,
    )


def replay_prompt_mode(
    db: HarnessDatabase,
    recording_id: str,
    *,
    target_model: str,
    target_tool: str = "",
    provider: Optional[LLMProvider] = None,
    grader: Optional[DialogGrader] = None,
    grader_model: str = "",
) -> ReplayResult:
    """Replay every user turn of ``recording_id`` against ``target_model``.

    ``provider`` and ``grader`` are injectable for hermetic tests; when
    omitted they are built with :func:`create_provider` (the grader
    defaults to the target model unless ``grader_model`` is given).

    Raises ``LookupError`` for an unknown recording and ``ValueError``
    when the recording contains no user turns.
    """
    source = db.get_recording(recording_id)
    if source is None:
        raise LookupError(f"no recording with id={recording_id!r}")
    source_turns = db.get_turns(recording_id)
    user_indices = [i for i, t in enumerate(source_turns) if t.role == "user"]
    if not user_indices:
        raise ValueError(f"recording {recording_id!r} has no user turns to replay")

    if provider is None:
        provider = create_provider(model=target_model)
    if grader is None:
        grader = DialogGrader(create_provider(model=grader_model or target_model))

    session_id = uuid.uuid4().hex
    started_at = _utc_now()
    tool_name = target_tool or source.tool_name or "replay"
    db.save_harness(
        AgenticHarness(
            session_id=session_id,
            tool_name=tool_name,
            started_at=started_at,
            model_id=target_model,
            rfc_version=__version__,
            branch=collect_ci_metadata().get("Branch", ""),
            replay_of_recording_id=recording_id,
        )
    )

    new_recording_id = uuid.uuid4().hex
    db.save_recording(
        DialogRecording(
            id=new_recording_id,
            source_type="replay",
            started_at=started_at,
            session_id=session_id,
            tool_name=tool_name,
            model_id=target_model,
            metadata_json=json.dumps(
                {
                    "mode": "prompt",
                    "replay_of_recording_id": recording_id,
                    "target_model": target_model,
                }
            ),
        )
    )

    replays: list[TurnReplay] = []
    new_turns: list[DialogTurn] = []
    metrics: list[AgenticMetric] = []
    next_turn_number = 1
    for index in user_indices:
        user_turn = source_turns[index]
        prompt = user_turn.content
        original_response = _original_response_for(source_turns, index)

        start = time.perf_counter()
        new_response = provider.generate(prompt)
        latency_ms = (time.perf_counter() - start) * 1000.0
        tokens_in, tokens_out = _provider_token_counts(provider)

        grade = grader.grade(prompt, original_response, new_response)
        replays.append(
            TurnReplay(
                turn_number=user_turn.turn_number,
                prompt=prompt,
                original_response=original_response,
                new_response=new_response,
                score=grade.score,
                reason=grade.reason,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=latency_ms,
            )
        )

        now = _utc_now()
        new_turns.append(
            DialogTurn(
                recording_id=new_recording_id,
                turn_number=next_turn_number,
                role="user",
                timestamp=now,
                content=prompt,
            )
        )
        next_turn_number += 1
        new_turns.append(
            DialogTurn(
                recording_id=new_recording_id,
                turn_number=next_turn_number,
                role="assistant",
                timestamp=_utc_now(),
                content=new_response,
                prompt_tokens=tokens_in,
                completion_tokens=tokens_out,
                latency_ms=latency_ms,
            )
        )
        next_turn_number += 1
        metrics.extend(
            AgenticMetric(
                session_id=session_id,
                metric_key=key,
                metric_value=value,
                recorded_at=now,
            )
            for key, value in (
                ("grader_score", grade.score),
                ("tokens_in", float(tokens_in)),
                ("tokens_out", float(tokens_out)),
                ("latency_ms", latency_ms),
            )
        )

    db.save_turns(new_turns)
    db.save_metrics(metrics)

    aggregate_score = sum(r.score for r in replays) / len(replays)
    outcome = derive_outcome(aggregate_score)
    ended_at = _utc_now()
    db.end_recording(new_recording_id, ended_at)
    db.end_harness(session_id, outcome, ended_at)

    return ReplayResult(
        session_id=session_id,
        source_recording_id=recording_id,
        new_recording_id=new_recording_id,
        target_model=target_model,
        mode="prompt",
        outcome=outcome,
        aggregate_score=aggregate_score,
        turns=replays,
    )


def _cmd_replay(args: argparse.Namespace) -> int:
    # Late import: shares dialog import's flag > DIALOG_DATABASE_URL >
    # DATABASE_URL precedence without duplicating it.
    from rfc.dialog_import import _resolve_database_url

    url = _resolve_database_url(args.database_url)
    if not url:
        print(
            "ERROR: no database configured — pass --database-url or set "
            "DIALOG_DATABASE_URL / DATABASE_URL. The replay rows are the "
            "point of `dialog replay`, so this is a hard failure.",
            file=sys.stderr,
        )
        return 2
    db = HarnessDatabase(database_url=url)
    try:
        result = replay_prompt_mode(
            db,
            args.recording_id,
            target_model=args.target_model,
            target_tool=args.target_tool,
            grader_model=args.grader_model,
        )
    except (LookupError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "replayed": True,
                "mode": result.mode,
                "session_id": result.session_id,
                "source_recording_id": result.source_recording_id,
                "new_recording_id": result.new_recording_id,
                "target_model": result.target_model,
                "turns": len(result.turns),
                "aggregate_score": round(result.aggregate_score, 4),
                "outcome": result.outcome,
            },
            indent=2,
        )
    )
    return 0


def register_replay_command(actions: argparse._SubParsersAction) -> None:
    """Attach ``replay`` to the ``rfc dialog`` subcommand parser."""
    replay = actions.add_parser(
        "replay", help="re-prompt a recorded dialog against a target model"
    )
    replay.add_argument("recording_id", help="dialog_recordings.id to replay")
    replay.add_argument("--target-model", required=True, help="model id to re-prompt")
    replay.add_argument(
        "--target-tool",
        default="",
        help="tool name for the new harness row (default: source recording's tool)",
    )
    replay.add_argument(
        "--mode",
        default="prompt",
        choices=REPLAY_MODES,
        help="replay mode (only 'prompt' is implemented; it is the default)",
    )
    replay.add_argument(
        "--grader-model",
        default="",
        help="judge model for Grade Answer (default: the target model)",
    )
    replay.add_argument("--database-url", default="")
    replay.set_defaults(func=_cmd_replay)
