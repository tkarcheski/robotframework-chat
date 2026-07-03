"""Live LLM console feed (owner request 2026-07-03).

``LLM_CONSOLE_FEED_ENABLED=1`` wraps every provider from ``create_provider``
so each ``generate()`` emits ONE self-contained line to the Robot console:

    [<node>/<model>] <prompt preview> -> <response preview> (1.2s, 42 tok/s)

Parallel host-scheduler runs are separate ``robot`` processes sharing one
terminal, so the single-line, node-prefixed format is the interleaving-safe
design. The ollama warm-up probe (``generate("ping")``) is suppressed.
"""

from __future__ import annotations

import pytest

from rfc import llm_client
from rfc.llm_client import _maybe_wrap_with_console, unwrap_provider


class FakeProvider:
    """Minimal LLMProvider stand-in with the attrs the feed reads."""

    def __init__(self, response: str = "the answer", fail: Exception | None = None):
        self.model = "qwen3:8b"
        self.base_url = "http://192.168.68.61:11434"
        self.last_metrics = {"eval_rate": 41.7}
        self._response = response
        self._fail = fail
        self.calls: list[str] = []

    def generate(self, prompt: str, **kwargs):
        self.calls.append(prompt)
        if self._fail:
            raise self._fail
        return self._response

    def is_available(self) -> bool:
        return True


@pytest.fixture
def console_lines(monkeypatch):
    """Capture robot.api logger.console output."""
    lines: list[str] = []
    from robot.api import logger as robot_logger

    monkeypatch.setattr(robot_logger, "console", lambda msg, **kw: lines.append(msg))
    return lines


def test_disabled_by_default_returns_same_client(monkeypatch):
    monkeypatch.delenv("LLM_CONSOLE_FEED_ENABLED", raising=False)
    client = FakeProvider()
    assert _maybe_wrap_with_console(client) is client


def test_enabled_wraps_and_emits_one_line(monkeypatch, console_lines):
    monkeypatch.setenv("LLM_CONSOLE_FEED_ENABLED", "1")
    monkeypatch.setenv("RFC_HOSTNAME", "dev1")
    wrapped = _maybe_wrap_with_console(FakeProvider())
    out = wrapped.generate("What is 2+2?")
    assert out == "the answer"
    assert len(console_lines) == 1
    line = console_lines[0]
    assert line.startswith("[dev1/qwen3:8b] ")
    assert "What is 2+2?" in line
    assert "the answer" in line
    assert "tok/s" in line
    assert "\n" not in line


def test_node_falls_back_to_endpoint_host(monkeypatch, console_lines):
    monkeypatch.setenv("LLM_CONSOLE_FEED_ENABLED", "1")
    monkeypatch.delenv("RFC_HOSTNAME", raising=False)
    wrapped = _maybe_wrap_with_console(FakeProvider())
    wrapped.generate("hi")
    assert console_lines[0].startswith("[192.168.68.61/qwen3:8b] ")


def test_previews_are_truncated_and_flattened(monkeypatch, console_lines):
    monkeypatch.setenv("LLM_CONSOLE_FEED_ENABLED", "1")
    monkeypatch.setenv("RFC_HOSTNAME", "ai1")
    long_prompt = "spam " * 100
    wrapped = _maybe_wrap_with_console(FakeProvider(response="line1\nline2\t" + "y" * 300))
    wrapped.generate(long_prompt)
    line = console_lines[0]
    assert "\n" not in line and "\t" not in line
    # both previews capped (some slack for prefix/suffix/ellipses)
    assert len(line) < 350


def test_warmup_ping_is_suppressed(monkeypatch, console_lines):
    monkeypatch.setenv("LLM_CONSOLE_FEED_ENABLED", "1")
    wrapped = _maybe_wrap_with_console(FakeProvider())
    assert wrapped.generate("ping") == "the answer"
    assert console_lines == []


def test_failure_emits_error_line_and_reraises(monkeypatch, console_lines):
    monkeypatch.setenv("LLM_CONSOLE_FEED_ENABLED", "1")
    monkeypatch.setenv("RFC_HOSTNAME", "mini2")
    boom = RuntimeError("connection reset")
    wrapped = _maybe_wrap_with_console(FakeProvider(fail=boom))
    with pytest.raises(RuntimeError):
        wrapped.generate("hello?")
    assert len(console_lines) == 1
    assert "ERROR" in console_lines[0]
    assert "connection reset" in console_lines[0]
    assert console_lines[0].startswith("[mini2/qwen3:8b] ")


def test_unwrap_provider_peels_console_wrapper(monkeypatch):
    monkeypatch.setenv("LLM_CONSOLE_FEED_ENABLED", "1")
    inner = FakeProvider()
    wrapped = _maybe_wrap_with_console(inner)
    assert wrapped is not inner
    assert unwrap_provider(wrapped) is inner


def test_attribute_passthrough(monkeypatch):
    monkeypatch.setenv("LLM_CONSOLE_FEED_ENABLED", "1")
    inner = FakeProvider()
    wrapped = _maybe_wrap_with_console(inner)
    assert wrapped.model == inner.model
    assert wrapped.last_metrics == inner.last_metrics
    assert wrapped.is_available() is True


def test_create_provider_chain_includes_console_wrapper(monkeypatch):
    monkeypatch.setenv("LLM_CONSOLE_FEED_ENABLED", "1")
    monkeypatch.delenv("ANSWER_CACHE_ENABLED", raising=False)
    monkeypatch.delenv("GRAYLOG_LLM_ENABLED", raising=False)
    client = llm_client.create_provider("ollama", model="m", base_url="http://x:1")
    # console wrapper is in the chain and unwrap still reaches the concrete client
    assert type(wrapped := client).__name__ == "_ConsoleFeedProvider" or hasattr(
        wrapped, "__wrapped__"
    )
    concrete = unwrap_provider(client)
    assert type(concrete).__name__ == "OllamaClient"
