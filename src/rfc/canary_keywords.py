"""Robot Framework keywords for live canary session-degradation runs.

This is the model-driven surface of the canary suite: it wires a *live* LLM
session into the responder-agnostic engine in :mod:`rfc.canary`. The engine
owns the degradation contract (drive turns, detect the first dropped token,
record turns / tokens / wall-clock); this module only supplies the concrete
responder — a stateless provider re-sent the full conversation each turn, the
same conversation-replay technique the multi-turn suite uses — and emits the
per-turn and summary metrics onto the run's RFC_DATA stream.

Because this library reaches a model under test (``create_provider``), any suite
importing it is an LLM surface and is therefore ``axis:model``. The
``axis:harness`` follow-up — the same canary driven through a coding-agent
harness session — is a *different* responder plugged into the *same* engine; it
lives behind the harness keyword surface, not here.
"""

from __future__ import annotations

import json
from typing import Any, List, Optional, Sequence

from robot.api import logger
from robot.api.deco import keyword

from .canary import (
    CanarySpec,
    ResponderReply,
    SessionCanaryResult,
    TurnResult,
    run_canary_session,
)
from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data
from .thinking import parse_thinking

# A small, topic-varied rotation of benign driver prompts. The content is
# deliberately unrelated to the canary so a model that keeps echoing the token
# is following the standing instruction, not merely parroting the prompt.
_DEFAULT_PROMPTS: tuple[str, ...] = (
    "What's a good way to stay focused while working?",
    "Explain how a rainbow forms, briefly.",
    "Suggest a simple vegetarian dinner.",
    "What are the benefits of taking short walks?",
    "Describe the water cycle in a sentence or two.",
    "Recommend a classic novel and why.",
    "How does compound interest work?",
    "Give me a quick stretch I can do at my desk.",
    "What's the difference between weather and climate?",
    "Name a fun fact about octopuses.",
    "How do I brew a decent cup of coffee?",
    "What makes a good password?",
)


class SessionCanaryKeywords:
    """Robot Framework keywords that run a live canary session against a model."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_retries: int = 2,
        hide_thinking: bool | str = True,
        client: Any = None,
    ) -> None:
        if client is not None:
            self.client = client
        else:
            timeout = resolve_timeout(timeout)
            self.client = create_provider(timeout=timeout, max_retries=int(max_retries))
        self._hide_thinking: bool = (
            hide_thinking.lower() not in ("false", "0", "no")
            if isinstance(hide_thinking, str)
            else bool(hide_thinking)
        )

    # -- prompt helpers -------------------------------------------------------

    @keyword("Default Canary Prompts")
    def default_canary_prompts(self, count: int) -> List[str]:
        """Return ``count`` benign driver prompts, cycling the built-in rotation."""
        count = int(count)
        if count < 1:
            raise ValueError(f"count must be >= 1, got {count}")
        return [_DEFAULT_PROMPTS[i % len(_DEFAULT_PROMPTS)] for i in range(count)]

    # -- the live session -----------------------------------------------------

    @keyword("Run Canary Session")
    def run_canary_session(
        self,
        token: str,
        max_turns: int,
        prompts: Optional[Sequence[str]] = None,
        instruction: str = "",
        stop_on_degradation: bool = True,
    ) -> SessionCanaryResult:
        """Drive a live canary session and return its degradation record.

        Args:
            token: The canary word the model is told to echo every turn.
            max_turns: Hard cap on turns.
            prompts: Driver prompts; when omitted a benign rotation of length
                ``max_turns`` is used.
            instruction: Override the standing instruction handed to the model.
            stop_on_degradation: Stop at the first miss (default) or run to cap.

        The full conversation is re-sent each turn so a stateless provider
        behaves like a session; per-turn and summary metrics are emitted as
        RFC_DATA for the spine.
        """
        max_turns = int(max_turns)
        spec = CanarySpec(
            token=token,
            max_turns=max_turns,
            instruction=instruction,
            stop_on_degradation=_as_bool(stop_on_degradation),
        )
        driver = list(prompts) if prompts else self.default_canary_prompts(max_turns)

        result = run_canary_session(self._responder(spec), spec, driver)
        self._emit_summary(result, spec)
        return result

    def _responder(self, spec: CanarySpec):
        """Build a responder that replays the whole conversation each turn."""
        instruction = spec.default_instruction()

        def responder(prompt: str, history: List[TurnResult]) -> ResponderReply:
            conversation = self._build_prompt(instruction, history, prompt)
            raw = self.client.generate(conversation)
            clean, thinking = parse_thinking(raw, strip_unclosed=self._hide_thinking)
            if thinking is not None:
                emit_rfc_data("thinking_text", thinking)

            metrics = getattr(self.client, "last_metrics", None)
            latency_ms = 0.0
            response_tokens = 0
            if isinstance(metrics, dict) and metrics:
                emit_rfc_data("llm_metrics", json.dumps(metrics))
                latency_ms = _metric_ms(metrics.get("total_duration"))
                response_tokens = int(metrics.get("eval_count") or 0)

            turn_index = len(history) + 1
            hit = _quick_hit(clean, spec.token, spec.case_sensitive)
            emit_rfc_data("canary_turn", str(turn_index))
            emit_rfc_data("canary_turn_hit", str(hit))
            logger.info(
                f"Canary turn {turn_index}: hit={hit} "
                f"tokens={response_tokens} latency_ms={int(latency_ms)}"
            )
            return ResponderReply(
                text=clean,
                latency_ms=latency_ms,
                response_tokens=response_tokens,
            )

        return responder

    @staticmethod
    def _build_prompt(instruction: str, history: List[TurnResult], current: str) -> str:
        """Assemble a single-string conversation with the standing instruction."""
        parts: List[str] = [f"System: {instruction}", ""]
        for turn in history:
            parts.append(f"User: {turn.prompt}")
            parts.append(f"Assistant: {turn.response}")
        parts.append(f"User: {current}")
        parts.append("Assistant:")
        return "\n".join(parts)

    def _emit_summary(self, result: SessionCanaryResult, spec: CanarySpec) -> None:
        emit_rfc_data("canary_token", spec.token)
        emit_rfc_data("canary_degraded", str(result.degraded))
        emit_rfc_data("canary_degradation_turn", str(result.degradation_turn))
        emit_rfc_data("canary_survived_turns", str(result.survived_turns))
        emit_rfc_data("canary_total_turns", str(result.total_turns))
        emit_rfc_data("canary_elapsed_ms", str(int(result.elapsed_ms)))
        emit_rfc_data("canary_response_tokens", str(result.total_response_tokens))
        logger.info(
            f"Canary session summary: token='{spec.token}' "
            f"degraded={result.degraded} degradation_turn={result.degradation_turn} "
            f"survived_turns={result.survived_turns}/{result.total_turns} "
            f"tokens={result.total_response_tokens} elapsed_ms={int(result.elapsed_ms)}"
        )


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "")
    return bool(value)


def _quick_hit(text: str, token: str, case_sensitive: bool) -> bool:
    # Lightweight per-turn hit for logging; the engine recomputes authoritatively.
    from .canary import canary_hit

    return canary_hit(text, token, case_sensitive)


def _metric_ms(total_duration: Any) -> float:
    """Ollama reports ``total_duration`` in nanoseconds; convert to ms."""
    try:
        return float(total_duration) / 1_000_000.0
    except (TypeError, ValueError):
        return 0.0
