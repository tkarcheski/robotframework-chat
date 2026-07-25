"""Tests for the canary session-degradation engine (``rfc.canary``).

The engine is the deterministic core behind the canary suites: a standing
instruction tells the model to include a canary token (e.g. our name) in
*every* reply, and the engine drives a multi-turn session and detects the
first turn where the token drops — the session's degradation point. This
module is the TDD anchor; it exercises the engine with scripted responders
and never touches a live model.
"""

from __future__ import annotations

from typing import List

import pytest

from rfc.canary import (
    CanarySpec,
    ResponderReply,
    SessionCanaryResult,
    TurnResult,
    canary_hit,
    run_canary_session,
)


class TestCanaryHit:
    """Whole-word, case-insensitive-by-default token detection."""

    def test_simple_present(self):
        assert canary_hit("Sure thing, Tyler!", "Tyler") is True

    def test_absent(self):
        assert canary_hit("Sure thing.", "Tyler") is False

    def test_case_insensitive_default(self):
        assert canary_hit("sure thing, tyler", "Tyler") is True

    def test_case_sensitive_opt_in(self):
        assert canary_hit("sure thing, tyler", "Tyler", case_sensitive=True) is False

    def test_punctuation_stripped(self):
        assert canary_hit("(Tyler)", "Tyler") is True

    def test_no_substring_false_positive(self):
        # "Tyler" must not match inside a longer word.
        assert canary_hit("The Tylerson report is ready.", "Tyler") is False

    def test_multi_word_token(self):
        assert canary_hit("Regards, Tyler Karcheski.", "Tyler Karcheski") is True
        assert canary_hit("Regards, Tyler.", "Tyler Karcheski") is False

    def test_empty_inputs(self):
        assert canary_hit("", "Tyler") is False
        assert canary_hit("Tyler", "") is False


def _scripted(responses: List[str]):
    """A responder that replays a fixed list of responses and records history."""
    seen: List[int] = []

    def responder(prompt: str, history: List[TurnResult]) -> ResponderReply:
        # History must grow by exactly one each turn and never include the
        # current (in-flight) turn.
        seen.append(len(history))
        text = responses[len(history)]
        return ResponderReply(text=text, latency_ms=10.0, response_tokens=3)

    responder.seen = seen  # type: ignore[attr-defined]
    return responder


class TestRunCanarySession:
    """The drive-until-first-miss loop and its recorded metrics."""

    def test_all_hits_no_degradation(self):
        spec = CanarySpec(token="Tyler", max_turns=3)
        prompts = ["q1", "q2", "q3"]
        responder = _scripted(["hi Tyler", "yo Tyler", "hey Tyler"])

        result = run_canary_session(responder, spec, prompts)

        assert isinstance(result, SessionCanaryResult)
        assert result.degraded is False
        assert result.degradation_turn == 0
        assert result.total_turns == 3
        assert all(t.hit for t in result.turns)

    def test_first_miss_stops_by_default(self):
        spec = CanarySpec(token="Tyler", max_turns=5)
        prompts = ["q1", "q2", "q3", "q4", "q5"]
        # Miss on turn 3.
        responder = _scripted(
            ["hi Tyler", "yo Tyler", "no name here", "Tyler", "Tyler"]
        )

        result = run_canary_session(responder, spec, prompts)

        assert result.degraded is True
        assert result.degradation_turn == 3
        # Stopped at the first miss: only 3 turns were run.
        assert result.total_turns == 3
        assert result.turns[-1].hit is False

    def test_run_to_cap_when_not_stopping(self):
        spec = CanarySpec(token="Tyler", max_turns=5, stop_on_degradation=False)
        prompts = ["q1", "q2", "q3", "q4", "q5"]
        responder = _scripted(["Tyler", "Tyler", "miss", "Tyler", "miss"])

        result = run_canary_session(responder, spec, prompts)

        assert result.degraded is True
        # First miss is still recorded as the degradation point ...
        assert result.degradation_turn == 3
        # ... but the whole session ran.
        assert result.total_turns == 5
        assert [t.hit for t in result.turns] == [True, True, False, True, False]

    def test_max_turns_caps_prompts(self):
        spec = CanarySpec(token="Tyler", max_turns=2)
        prompts = ["q1", "q2", "q3", "q4"]
        responder = _scripted(["Tyler", "Tyler", "Tyler", "Tyler"])

        result = run_canary_session(responder, spec, prompts)

        assert result.total_turns == 2
        assert result.degraded is False

    def test_metrics_accumulate(self):
        spec = CanarySpec(token="Tyler", max_turns=3)
        prompts = ["q1", "q2", "q3"]
        responder = _scripted(["Tyler", "Tyler", "Tyler"])

        result = run_canary_session(responder, spec, prompts)

        assert result.total_response_tokens == 9  # 3 turns * 3 tokens
        assert result.elapsed_ms == pytest.approx(30.0)  # 3 turns * 10ms

    def test_responder_receives_growing_history(self):
        spec = CanarySpec(token="Tyler", max_turns=3)
        prompts = ["q1", "q2", "q3"]
        responder = _scripted(["Tyler", "Tyler", "Tyler"])

        run_canary_session(responder, spec, prompts)

        # History lengths seen by the responder: 0, 1, 2.
        assert responder.seen == [0, 1, 2]

    def test_string_responder_is_normalized(self):
        spec = CanarySpec(token="Tyler", max_turns=2)
        prompts = ["q1", "q2"]

        def responder(prompt: str, history: List[TurnResult]) -> str:
            return "Tyler" if len(history) == 0 else "nope"

        result = run_canary_session(responder, spec, prompts)

        assert result.degradation_turn == 2
        assert result.turns[0].hit is True
        assert result.turns[1].hit is False

    def test_prompts_shorter_than_cap_stop_cleanly(self):
        spec = CanarySpec(token="Tyler", max_turns=10)
        prompts = ["q1", "q2"]
        responder = _scripted(["Tyler", "Tyler"])

        result = run_canary_session(responder, spec, prompts)

        assert result.total_turns == 2
        assert result.degraded is False


class TestCanarySpec:
    """Spec validation guards against silently-degenerate runs."""

    def test_rejects_empty_token(self):
        with pytest.raises(ValueError):
            CanarySpec(token="", max_turns=3)

    def test_rejects_nonpositive_max_turns(self):
        with pytest.raises(ValueError):
            CanarySpec(token="Tyler", max_turns=0)
