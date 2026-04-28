"""Tests for the agent-runner factory and Runner protocol."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from rfc.agent_config import AgentConfig
from rfc.agent_runner import (
    Runner,
    create_agent_runner,
)
from rfc.fake_agent_runner import FakeAgentRunner
from rfc.ollama_agent_runner import OllamaAgentRunner


def _config(runner: str, **kwargs: object) -> AgentConfig:
    base = {
        "id": "test-agent",
        "runner": runner,
        "model": "phi4:14b" if runner == "ollama" else "",
        "endpoint": "http://localhost:11434" if runner == "ollama" else "",
        "timeout_seconds": 600,
        "temperature": 0.0,
        "capabilities": (),
        "env_vars": (),
    }
    base.update(kwargs)
    return AgentConfig(**base)  # type: ignore[arg-type]


class TestCreateAgentRunner:
    def test_fake_runner_dispatch(self, tmp_path: Path) -> None:
        runner = create_agent_runner(_config("fake"), scenarios_root=tmp_path)
        assert isinstance(runner, FakeAgentRunner)

    def test_ollama_runner_dispatch(self, tmp_path: Path) -> None:
        runner = create_agent_runner(
            _config("ollama"), scenarios_root=tmp_path, provider=_StubProvider()
        )
        assert isinstance(runner, OllamaAgentRunner)

    def test_returned_runner_satisfies_protocol(self, tmp_path: Path) -> None:
        runner: Runner = create_agent_runner(_config("fake"), scenarios_root=tmp_path)
        assert hasattr(runner, "run")
        assert hasattr(runner, "list_scenarios")

    def test_fake_runner_filters_by_agent_id(self, tmp_path: Path) -> None:
        scenario_dir = tmp_path / "alpha"
        scenario_dir.mkdir()
        (scenario_dir / "run.yaml").write_text(
            yaml.safe_dump(
                {
                    "agent_id": "test-agent",
                    "scenario_id": "alpha",
                    "task": "x",
                    "base_branch": "main",
                    "branch_name": "claude/x-12345",
                }
            )
        )
        runner = create_agent_runner(_config("fake"), scenarios_root=tmp_path)
        run = runner.run("alpha")
        assert run.agent_id == "test-agent"
        assert runner.list_scenarios() == ["alpha"]

    def test_unknown_runner_rejected(self, tmp_path: Path) -> None:
        bad = AgentConfig(id="x", runner="fake")
        object.__setattr__(bad, "runner", "bogus")
        with pytest.raises(ValueError, match="runner"):
            create_agent_runner(bad, scenarios_root=tmp_path)


class _StubProvider:
    """Minimal LLMProvider stub so OllamaAgentRunner construction doesn't try Ollama."""

    model = "stub"
    temperature = 0.0
    max_tokens = 256
    seed = None
    top_p = None
    top_k = None
    num_ctx = None
    keep_alive = None
    last_metrics = None

    def generate(self, prompt: str) -> str:
        return ""
