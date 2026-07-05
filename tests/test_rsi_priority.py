"""Unit tests for the RSI-model update-detection logic.

Context: the goal is "keep testing running 24/7, prioritize the RSI model when
it updates." ``rfc.rsi_priority`` provides the pure logic that
``scripts/rsi_priority_watcher.py`` uses to decide, from Ollama ``/api/tags``
digests, when the RSI model has changed and should be re-tested with priority.
"""

from __future__ import annotations

from rfc.rsi_priority import DEFAULT_RSI_MODEL, extract_digest, needs_retest


def _tags(*models: dict) -> dict:
    """Wrap model dicts into an Ollama /api/tags-shaped payload."""
    return {"models": list(models)}


class TestExtractDigest:
    def test_returns_digest_for_matching_tag(self) -> None:
        payload = _tags(
            {"name": "llama3:latest", "digest": "aaaa1111"},
            {"name": DEFAULT_RSI_MODEL, "digest": "ce292ba5c503789e"},
        )
        assert extract_digest(payload, DEFAULT_RSI_MODEL) == "ce292ba5c503789e"

    def test_returns_none_when_model_absent(self) -> None:
        payload = _tags({"name": "llama3:latest", "digest": "aaaa1111"})
        assert extract_digest(payload, DEFAULT_RSI_MODEL) is None

    def test_returns_none_for_empty_digest(self) -> None:
        payload = _tags({"name": DEFAULT_RSI_MODEL, "digest": ""})
        assert extract_digest(payload, DEFAULT_RSI_MODEL) is None

    def test_returns_none_for_missing_digest_key(self) -> None:
        payload = _tags({"name": DEFAULT_RSI_MODEL})
        assert extract_digest(payload, DEFAULT_RSI_MODEL) is None

    def test_handles_payload_without_models_key(self) -> None:
        assert extract_digest({}, DEFAULT_RSI_MODEL) is None


class TestNeedsRetest:
    def test_absent_now_is_false(self) -> None:
        # Model not present on this host right now -> nothing to run.
        assert needs_retest("old", None) is False
        assert needs_retest(None, None) is False

    def test_first_sighting_is_true(self) -> None:
        # Never tested on this host before -> run a baseline.
        assert needs_retest(None, "ce292ba5c503789e") is True

    def test_changed_digest_is_true(self) -> None:
        assert needs_retest("770cbde647c7", "ce292ba5c503789e") is True

    def test_unchanged_digest_is_false(self) -> None:
        assert needs_retest("ce292ba5c503789e", "ce292ba5c503789e") is False
