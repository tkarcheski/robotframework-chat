"""Tests for the live canary keyword library (``rfc.canary_keywords``).

Uses a mock provider so the model-driven wiring — conversation replay, thinking
stripping, metric extraction, and the engine hand-off — is covered
deterministically without a live endpoint.
"""

from __future__ import annotations

from typing import List

from rfc.canary_keywords import SessionCanaryKeywords


class _MockClient:
    """A scripted provider recording every prompt it is asked to generate."""

    def __init__(self, responses: List[str], metrics: dict | None = None):
        self._responses = responses
        self._i = 0
        self.prompts_seen: List[str] = []
        self.last_metrics = metrics or {"eval_count": 5, "total_duration": 2_000_000}

    def generate(self, prompt: str) -> str:
        self.prompts_seen.append(prompt)
        text = self._responses[self._i]
        self._i += 1
        return text


class TestDefaultCanaryPrompts:
    def test_count_and_cycling(self):
        kw = SessionCanaryKeywords(client=_MockClient([]))
        prompts = kw.default_canary_prompts(30)
        assert len(prompts) == 30
        # Rotation repeats but is non-empty and varied.
        assert len(set(prompts)) > 1


class TestRunCanarySession:
    def test_all_hits(self):
        client = _MockClient(["Hi Tyler", "Yo Tyler", "Hey Tyler"])
        kw = SessionCanaryKeywords(client=client)

        result = kw.run_canary_session(token="Tyler", max_turns=3)

        assert result.degraded is False
        assert result.total_turns == 3
        # 3 turns * eval_count 5.
        assert result.total_response_tokens == 15
        # total_duration 2e6 ns == 2.0 ms per turn.
        assert round(result.elapsed_ms, 1) == 6.0

    def test_degrades_and_stops(self):
        client = _MockClient(["Tyler here", "still Tyler", "dropped it", "Tyler"])
        kw = SessionCanaryKeywords(client=client)

        result = kw.run_canary_session(token="Tyler", max_turns=4)

        assert result.degraded is True
        assert result.degradation_turn == 3
        assert result.total_turns == 3  # stopped at first miss
        # The provider was only asked three times.
        assert len(client.prompts_seen) == 3

    def test_conversation_replays_history(self):
        client = _MockClient(["Tyler a", "Tyler b"])
        kw = SessionCanaryKeywords(client=client)

        kw.run_canary_session(token="Tyler", max_turns=2)

        # Second prompt must contain the first turn's Q and A (session replay).
        second = client.prompts_seen[1]
        assert "Assistant: Tyler a" in second
        assert second.strip().endswith("Assistant:")
        # Standing instruction rides along every turn.
        assert "Tyler" in client.prompts_seen[0]
        assert client.prompts_seen[0].startswith("System:")

    def test_thinking_is_stripped_before_matching(self):
        client = _MockClient(["<think>should I say the name?</think> Sure, Tyler"])
        kw = SessionCanaryKeywords(client=client)

        result = kw.run_canary_session(token="Tyler", max_turns=1)

        assert result.turns[0].hit is True
        assert "<think>" not in result.turns[0].response

    def test_run_to_cap_records_full_curve(self):
        client = _MockClient(["Tyler", "miss", "Tyler"])
        kw = SessionCanaryKeywords(client=client)

        result = kw.run_canary_session(
            token="Tyler", max_turns=3, stop_on_degradation=False
        )

        assert result.total_turns == 3
        assert result.degradation_turn == 2
        assert [t.hit for t in result.turns] == [True, False, True]
