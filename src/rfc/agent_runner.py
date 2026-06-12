"""Runner protocol and factory for the agentic-coding suite.

Every agent runner -- fake (replay) or live (local model) -- exposes the
same minimal surface so verifiers and Robot keywords stay independent of
the source. :func:`create_agent_runner` dispatches on
``AgentConfig.runner`` to pick the implementation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from .agent_config import AgentConfig
from .agent_run import AgentRun
from .fake_agent_runner import FakeAgentRunner
from .live_agent_runner import LiveClaudeCodeRunner
from .llm_client import LLMProvider
from .ollama_agent_runner import OllamaAgentRunner


@runtime_checkable
class Runner(Protocol):
    """Structural protocol satisfied by every agent runner."""

    def run(self, scenario_id: str) -> AgentRun: ...
    def list_scenarios(self) -> list[str]: ...


def create_agent_runner(
    config: AgentConfig,
    *,
    scenarios_root: Path,
    provider: LLMProvider | None = None,
) -> Runner:
    """Build the runner appropriate for ``config.runner``.

    ``scenarios_root`` is the directory containing per-scenario subdirs.
    For ``runner: fake`` each subdir must have a ``run.yaml``; for
    ``runner: ollama`` and ``runner: live`` each subdir must have a
    ``task.yaml``.

    ``provider`` is only used for ``runner: ollama``. If omitted, the
    OllamaAgentRunner constructs a default OllamaClient from ``config``
    on first use. ``runner: live`` shells out to the ``claude`` CLI
    against an isolated git worktree -- see :mod:`rfc.live_agent_runner`.
    """
    if config.runner == "fake":
        return FakeAgentRunner(fixtures_root=scenarios_root, agent_id=config.id)
    if config.runner == "ollama":
        return OllamaAgentRunner(
            config=config,
            scenarios_root=scenarios_root,
            provider=provider,
        )
    if config.runner == "live":
        return LiveClaudeCodeRunner(
            config=config,
            scenarios_root=scenarios_root,
        )
    raise ValueError(
        f"Cannot build runner for agent {config.id!r}: "
        f"unknown runner type {config.runner!r}"
    )
