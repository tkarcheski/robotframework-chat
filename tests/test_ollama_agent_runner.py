"""Tests for OllamaAgentRunner: drive a local model through a scenario."""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from rfc.agent_config import AgentConfig
from rfc.ollama_agent_runner import (
    OllamaAgentRunner,
    extract_yaml_block,
    render_prompt,
)


@dataclass
class StubLLMProvider:
    """Test double for the LLM provider that records prompts and returns canned text."""

    canned: str = ""
    prompts: list[str] = field(default_factory=list)
    model: str = "stub"
    temperature: float = 0.0
    max_tokens: int = 256
    seed: int | None = None
    top_p: float | None = None
    top_k: int | None = None
    num_ctx: int | None = None
    keep_alive: str | None = None
    last_metrics: dict[str, Any] | None = None

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.canned


def _config(**overrides: Any) -> AgentConfig:
    base = {
        "id": "ollama-local",
        "runner": "ollama",
        "model": "phi4:14b",
        "endpoint": "http://localhost:11434",
        "timeout_seconds": 600,
        "temperature": 0.0,
        "capabilities": (),
        "env_vars": (),
    }
    base.update(overrides)
    return AgentConfig(**base)


def _write_task(tmp_path: Path, scenario_id: str, **fields: Any) -> Path:
    scenario_dir = tmp_path / scenario_id
    scenario_dir.mkdir()
    task = {
        "scenario_id": scenario_id,
        "task": "Rename a function and update its tests.",
        "base_branch": "claude-code-staging",
    }
    task.update(fields)
    (scenario_dir / "task.yaml").write_text(yaml.safe_dump(task))
    return scenario_dir / "task.yaml"


def _canned_run_yaml() -> str:
    return textwrap.dedent(
        """\
        agent_id: ollama-local
        scenario_id: precise_task
        task: Rename a function and update its tests.
        base_branch: claude-code-staging
        branch_name: claude/rename-fn-12345
        commands:
          - argv: ["git", "fetch", "origin", "claude-code-staging"]
            returncode: 0
        questions: []
        commits:
          - sha: aaa111
            subject: "refactor: rename helper"
            files_changed: ["src/rfc/helper.py"]
        """
    )


class TestExtractYamlBlock:
    def test_strips_triple_backtick_yaml_fence(self) -> None:
        text = "Sure, here is the run:\n```yaml\nfoo: 1\n```\n"
        assert extract_yaml_block(text).strip() == "foo: 1"

    def test_strips_plain_triple_backtick_fence(self) -> None:
        text = "```\nfoo: 1\n```"
        assert extract_yaml_block(text).strip() == "foo: 1"

    def test_returns_text_unchanged_when_no_fence(self) -> None:
        text = "agent_id: x\nscenario_id: y\n"
        assert extract_yaml_block(text) == text

    def test_picks_first_fence_when_multiple(self) -> None:
        text = "```yaml\nfoo: 1\n```\ntrailing prose\n```yaml\nfoo: 2\n```"
        assert extract_yaml_block(text).strip() == "foo: 1"

    def test_fence_language_tag_is_case_insensitive(self) -> None:
        """Models emit fences with varied casing -- ```YAML, ```Yaml, ```YML."""
        for tag in ("YAML", "Yaml", "YML", "Yml"):
            text = f"```{tag}\nfoo: 1\n```"
            assert extract_yaml_block(text).strip() == "foo: 1", f"tag={tag!r}"


class TestRenderPrompt:
    def test_includes_task_and_schema(self) -> None:
        prompt = render_prompt(
            agent_id="ollama-local",
            scenario_id="precise_task",
            task="Rename DEFAULT_LIMIT.",
            base_branch="claude-code-staging",
        )
        assert "ollama-local" in prompt
        assert "precise_task" in prompt
        assert "Rename DEFAULT_LIMIT." in prompt
        assert "claude-code-staging" in prompt
        assert "agent_id" in prompt  # schema mentioned
        assert "branch_name" in prompt


class TestOllamaAgentRunner:
    def test_returns_agentrun_from_canned_yaml(self, tmp_path: Path) -> None:
        _write_task(tmp_path, "precise_task")
        provider = StubLLMProvider(canned=_canned_run_yaml())
        runner = OllamaAgentRunner(
            config=_config(),
            scenarios_root=tmp_path,
            provider=provider,
        )
        run = runner.run("precise_task")
        assert run.agent_id == "ollama-local"
        assert run.scenario_id == "precise_task"
        assert run.commits[0].subject.startswith("refactor:")
        assert provider.prompts, "provider should have been called"

    def test_strips_yaml_fences_from_response(self, tmp_path: Path) -> None:
        _write_task(tmp_path, "precise_task")
        provider = StubLLMProvider(
            canned="Here you go:\n```yaml\n" + _canned_run_yaml() + "```\n"
        )
        runner = OllamaAgentRunner(
            config=_config(),
            scenarios_root=tmp_path,
            provider=provider,
        )
        run = runner.run("precise_task")
        assert run.scenario_id == "precise_task"

    def test_overrides_response_agent_and_scenario(self, tmp_path: Path) -> None:
        """If the model emits a different agent_id/scenario_id, ours wins.

        The runner must not let a hallucinated id pollute downstream verifiers.
        """
        _write_task(tmp_path, "precise_task")
        bad_yaml = (
            _canned_run_yaml()
            .replace("agent_id: ollama-local", "agent_id: claude-code")
            .replace("scenario_id: precise_task", "scenario_id: something_else")
        )
        provider = StubLLMProvider(canned=bad_yaml)
        runner = OllamaAgentRunner(
            config=_config(),
            scenarios_root=tmp_path,
            provider=provider,
        )
        run = runner.run("precise_task")
        assert run.agent_id == "ollama-local"
        assert run.scenario_id == "precise_task"

    def test_unknown_scenario_raises(self, tmp_path: Path) -> None:
        runner = OllamaAgentRunner(
            config=_config(),
            scenarios_root=tmp_path,
            provider=StubLLMProvider(canned=_canned_run_yaml()),
        )
        with pytest.raises(KeyError, match="precise_task"):
            runner.run("precise_task")

    def test_invalid_yaml_response_raises_value_error(self, tmp_path: Path) -> None:
        _write_task(tmp_path, "precise_task")
        provider = StubLLMProvider(canned="not yaml: : :\n")
        runner = OllamaAgentRunner(
            config=_config(),
            scenarios_root=tmp_path,
            provider=provider,
        )
        with pytest.raises(ValueError, match="parse"):
            runner.run("precise_task")

    def test_empty_response_raises(self, tmp_path: Path) -> None:
        _write_task(tmp_path, "precise_task")
        runner = OllamaAgentRunner(
            config=_config(),
            scenarios_root=tmp_path,
            provider=StubLLMProvider(canned="   \n"),
        )
        with pytest.raises(ValueError, match="empty"):
            runner.run("precise_task")

    def test_null_collection_fields_are_normalized(self, tmp_path: Path) -> None:
        """A model response with `commands: null` (or other nulls) must not crash.

        LLM YAML often emits `null` for empty optional fields, and naive
        `raw.get("commands", [])` returns None when the key IS present with a
        null value, which then explodes during tuple construction.
        """
        _write_task(tmp_path, "precise_task")
        canned = textwrap.dedent(
            """\
            agent_id: ollama-local
            scenario_id: precise_task
            task: Rename a function and update its tests.
            base_branch: claude-code-staging
            branch_name: claude/rename-fn-12345
            commands: null
            questions: null
            commits: null
            pr: null
            """
        )
        runner = OllamaAgentRunner(
            config=_config(),
            scenarios_root=tmp_path,
            provider=StubLLMProvider(canned=canned),
        )
        run = runner.run("precise_task")
        assert run.commands == ()
        assert run.questions == ()
        assert run.commits == ()
        assert run.pr is None

    def test_list_scenarios_uses_task_yaml(self, tmp_path: Path) -> None:
        _write_task(tmp_path, "alpha")
        _write_task(tmp_path, "bravo")
        runner = OllamaAgentRunner(
            config=_config(),
            scenarios_root=tmp_path,
            provider=StubLLMProvider(),
        )
        assert runner.list_scenarios() == ["alpha", "bravo"]
