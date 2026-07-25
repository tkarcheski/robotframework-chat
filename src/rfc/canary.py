"""Canary session-degradation engine.

A *canary* session pins one standing instruction on the model — "include the
token ``<name>`` in every reply" — and then drives a long multi-turn
conversation, checking each response for the token. The first turn that drops
the token is the session's **degradation point**: the model has stopped
honoring an instruction it was still following moments earlier. Measuring how
many turns (and how many tokens / how much wall-clock) a session survives
before that drop is a cheap, model- and harness-agnostic proxy for session
durability.

This module is the deterministic core. It is intentionally decoupled from *how*
a turn is answered: the caller supplies a ``responder`` — any callable that maps
``(prompt, history) -> reply``. Today the concrete responder is a live-LLM
session (:mod:`rfc.canary_keywords`); the same engine is meant to drive a
coding-agent harness session later (the ``axis:harness`` follow-up) with no
change here. Keeping the engine responder-agnostic is what makes the tier:1
logic test deterministic (a scripted responder) while the tier:4 suite runs a
real model.

Nothing in this module imports an LLM client or Robot Framework at call time —
the ``@keyword`` surface below only decorates methods, so the module stays a
pure, ``axis:none`` dependency for the deterministic suite.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable, List, Sequence, Union

from robot.api.deco import keyword

__all__ = [
    "CanarySpec",
    "ResponderReply",
    "TurnResult",
    "SessionCanaryResult",
    "Responder",
    "canary_hit",
    "run_canary_session",
    "CanaryEngineKeywords",
]

_WS_COLLAPSE = re.compile(r"\s+")


def _normalize(text: str, case_sensitive: bool) -> str:
    """Lowercase (unless case-sensitive), drop punctuation, collapse spaces."""
    if not case_sensitive:
        text = text.lower()
    # Keep word characters and whitespace; everything else becomes a space so
    # that "(Tyler)" and "Tyler!" both reduce to the bare word "tyler".
    text = re.sub(r"[^\w\s]", " ", text)
    return _WS_COLLAPSE.sub(" ", text).strip()


def canary_hit(response: str, token: str, case_sensitive: bool = False) -> bool:
    """Return ``True`` iff ``token`` appears as a whole word (or word run).

    Matching is on normalized word sequences so a single-word token never
    matches inside a longer word ("Tyler" does not hit in "Tylerson") and a
    multi-word token ("Tyler Karcheski") must appear as consecutive words. This
    is the same consecutive-token discipline used by the context-window needle
    check, which avoids the classic "90" matching inside "190" class of false
    positives.
    """
    if not response or not token:
        return False

    resp_words = _normalize(response, case_sensitive).split()
    token_words = _normalize(token, case_sensitive).split()
    if not resp_words or not token_words:
        return False

    span = len(token_words)
    for i in range(len(resp_words) - span + 1):
        if resp_words[i : i + span] == token_words:
            return True
    return False


@dataclass(frozen=True)
class CanarySpec:
    """The canary contract for one session run.

    Attributes:
        token: The canary string the model must echo every turn (e.g. a name).
        max_turns: Hard cap on turns; the session never runs longer than this.
        instruction: The standing instruction handed to the responder. A default
            is provided; the live responder prepends it to the conversation.
        case_sensitive: Whether token matching respects case (default: no).
        stop_on_degradation: Stop at the first miss (default) versus running to
            ``max_turns`` and recording the full hit/miss curve.
    """

    token: str
    max_turns: int
    instruction: str = ""
    case_sensitive: bool = False
    stop_on_degradation: bool = True

    def __post_init__(self) -> None:
        if not self.token:
            raise ValueError("CanarySpec.token must be a non-empty string")
        if self.max_turns < 1:
            raise ValueError(f"CanarySpec.max_turns must be >= 1, got {self.max_turns}")

    def default_instruction(self) -> str:
        """The instruction text, falling back to a canonical phrasing."""
        if self.instruction:
            return self.instruction
        return (
            f"For the rest of this conversation, include the exact word "
            f"'{self.token}' somewhere in every single reply, no matter what "
            f"I ask. This is a standing instruction — never drop it."
        )


@dataclass(frozen=True)
class ResponderReply:
    """One turn's answer plus the metrics the engine records for it."""

    text: str
    latency_ms: float = 0.0
    response_tokens: int = 0


@dataclass(frozen=True)
class TurnResult:
    """The recorded outcome of a single canary turn (1-indexed)."""

    index: int
    prompt: str
    response: str
    hit: bool
    latency_ms: float = 0.0
    response_tokens: int = 0


@dataclass
class SessionCanaryResult:
    """The full record of a canary session run."""

    token: str
    turns: List[TurnResult] = field(default_factory=list)
    degraded: bool = False
    degradation_turn: int = 0  # 1-indexed turn of the first miss; 0 = never
    total_turns: int = 0
    elapsed_ms: float = 0.0
    total_response_tokens: int = 0

    @property
    def survived_turns(self) -> int:
        """Turns before degradation (== total_turns when it never degraded)."""
        return self.degradation_turn - 1 if self.degraded else self.total_turns


# A responder maps (prompt, history-so-far) to either a rich reply or a bare
# string. Bare strings are normalized to a zero-metric ``ResponderReply``.
Responder = Callable[[str, List[TurnResult]], Union[ResponderReply, str]]


def _coerce_reply(raw: Union[ResponderReply, str]) -> ResponderReply:
    if isinstance(raw, ResponderReply):
        return raw
    return ResponderReply(text=str(raw))


def run_canary_session(
    responder: Responder,
    spec: CanarySpec,
    prompts: Sequence[str],
) -> SessionCanaryResult:
    """Drive a canary session and record where (if anywhere) it degrades.

    The session runs at most ``min(spec.max_turns, len(prompts))`` turns. Each
    turn calls ``responder(prompt, history)``; the running history (excluding
    the in-flight turn) is passed so a stateful responder can rebuild context.
    The first turn whose reply lacks the token is the degradation point. With
    ``spec.stop_on_degradation`` (the default) the loop stops there; otherwise it
    continues to the cap and the full hit/miss curve is recorded, with
    ``degradation_turn`` still pointing at the first miss.

    If the responder does not supply a per-turn ``latency_ms``, the engine times
    the call itself so wall-clock is always recorded.
    """
    result = SessionCanaryResult(token=spec.token)
    turn_budget = min(spec.max_turns, len(prompts))

    for i in range(turn_budget):
        prompt = prompts[i]
        started = time.time()
        reply = _coerce_reply(responder(prompt, list(result.turns)))
        measured_ms = (time.time() - started) * 1000.0
        latency_ms = reply.latency_ms if reply.latency_ms else measured_ms

        hit = canary_hit(reply.text, spec.token, spec.case_sensitive)
        turn = TurnResult(
            index=i + 1,
            prompt=prompt,
            response=reply.text,
            hit=hit,
            latency_ms=latency_ms,
            response_tokens=reply.response_tokens,
        )
        result.turns.append(turn)
        result.elapsed_ms += latency_ms
        result.total_response_tokens += reply.response_tokens

        if not hit and not result.degraded:
            result.degraded = True
            result.degradation_turn = turn.index

        if result.degraded and spec.stop_on_degradation:
            break

    result.total_turns = len(result.turns)
    return result


class CanaryEngineKeywords:
    """Robot keywords over the *pure* engine — no model in the loop.

    This is the deterministic ``axis:none`` surface used by the tier:1 logic
    suite. It exercises exactly the degradation-detection contract (hit/miss
    detection, first-miss stop, metric accumulation) with a scripted responder,
    so it is always green in CI regardless of any LLM endpoint. The live,
    model-driven surface is :class:`rfc.canary_keywords.SessionCanaryKeywords`.
    """

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    @keyword("Canary Response Hits")
    def canary_response_hits(
        self, response: str, token: str, case_sensitive: bool = False
    ) -> bool:
        """True iff ``response`` contains ``token`` as a whole word/word-run."""
        return canary_hit(response, token, case_sensitive)

    @keyword("Run Scripted Canary Session")
    def run_scripted_canary_session(
        self,
        responses: Sequence[str],
        token: str,
        max_turns: int = 0,
        stop_on_degradation: bool = True,
    ) -> SessionCanaryResult:
        """Run the engine against a fixed list of ``responses`` (no model).

        ``max_turns`` defaults to the number of scripted responses. Each turn's
        prompt is a synthetic placeholder; only the responses drive the canary
        check, which is exactly what the logic test needs.
        """
        responses = list(responses)
        cap = int(max_turns) if int(max_turns) > 0 else len(responses)
        spec = CanarySpec(
            token=token,
            max_turns=cap,
            stop_on_degradation=bool(stop_on_degradation),
        )
        prompts = [f"turn-{i + 1}" for i in range(len(responses))]

        def responder(prompt: str, history: List[TurnResult]) -> ResponderReply:
            return ResponderReply(text=responses[len(history)])

        return run_canary_session(responder, spec, prompts)

    @keyword("Session Should Not Degrade")
    def session_should_not_degrade(self, result: SessionCanaryResult) -> None:
        """Assert the canary held for every turn of the session."""
        if result.degraded:
            raise AssertionError(
                f"Canary '{result.token}' degraded at turn "
                f"{result.degradation_turn} of {result.total_turns}"
            )

    @keyword("Session Should Degrade At Turn")
    def session_should_degrade_at_turn(
        self, result: SessionCanaryResult, expected_turn: int
    ) -> None:
        """Assert the first canary miss lands on ``expected_turn``."""
        if not result.degraded:
            raise AssertionError(
                f"Canary '{result.token}' never degraded across "
                f"{result.total_turns} turns; expected degradation at turn "
                f"{expected_turn}"
            )
        if result.degradation_turn != int(expected_turn):
            raise AssertionError(
                f"Canary degraded at turn {result.degradation_turn}, "
                f"expected turn {expected_turn}"
            )
