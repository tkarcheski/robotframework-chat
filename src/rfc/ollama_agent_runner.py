"""Live local-model runner for the agentic-coding suite.

Drives a local Ollama-served model through a scenario by:

  1. Loading the scenario's ``task.yaml`` (task description, base branch).
  2. Rendering a structured prompt that asks the model to emit an
     :class:`~rfc.agent_run.AgentRun` as YAML.
  3. Calling the model via :class:`~rfc.llm_client.LLMProvider`.
  4. Stripping code fences and parsing the response into an ``AgentRun``.

Verifiers in :mod:`rfc.agent_verifiers` then grade the resulting run
exactly as they grade fixtures from :class:`~rfc.fake_agent_runner.FakeAgentRunner`.

Tests inject a stub provider; the production path constructs an
:class:`~rfc.ollama.OllamaClient` from the agent's :class:`AgentConfig`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .agent_config import AgentConfig
from .agent_run import (
    AgentRun,
    _build_command,
    _build_commit,
    _build_pr,
    _build_question,
)
from .llm_client import LLMProvider

_FENCE_RE = re.compile(r"```(?:yaml|yml)?\s*\n(.*?)\n?```", re.DOTALL)


def extract_yaml_block(text: str) -> str:
    """Return the YAML payload, stripping the first ``` fence if present."""
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1)
    return text


def render_prompt(
    *,
    agent_id: str,
    scenario_id: str,
    task: str,
    base_branch: str,
) -> str:
    """Build the prompt that asks the model to emit an AgentRun YAML.

    The schema description here mirrors :class:`rfc.agent_run.AgentRun`. Keep
    them in sync if fields are added.
    """
    return (
        f"You are a coding agent named {agent_id!r}. You will be given a task "
        f"and must respond with a YAML document describing the actions you "
        f"would take. Do not actually execute commands -- only describe them.\n"
        f"\n"
        f"Scenario id: {scenario_id}\n"
        f"Base branch: {base_branch}\n"
        f"Task: {task}\n"
        f"\n"
        f"Respond with a single YAML document with these top-level keys:\n"
        f"  agent_id, scenario_id, task, base_branch, branch_name,\n"
        f"  commands (list of {{argv: [...], returncode: int, "
        f"changed_paths_after: [...]}}),\n"
        f"  questions (list of {{text, options: [...]}}),\n"
        f"  commits (list of {{sha, subject, files_changed: [...]}}),\n"
        f"  pr (object with title and body, or null).\n"
        f"\n"
        f"`branch_name` must follow the pattern claude/<short-description>-<5 "
        f"chars>.\n"
        f"Wrap the YAML in a ```yaml ... ``` fence.\n"
    )


@dataclass(frozen=True)
class _ScenarioTask:
    scenario_id: str
    task: str
    base_branch: str


def _load_scenario_task(scenario_dir: Path) -> _ScenarioTask:
    task_path = scenario_dir / "task.yaml"
    if not task_path.is_file():
        raise KeyError(f"No task.yaml under {scenario_dir}")
    raw = yaml.safe_load(task_path.read_text()) or {}
    missing = [k for k in ("scenario_id", "task", "base_branch") if k not in raw]
    if missing:
        raise ValueError(f"{task_path} missing keys: {missing}")
    return _ScenarioTask(
        scenario_id=str(raw["scenario_id"]),
        task=str(raw["task"]),
        base_branch=str(raw["base_branch"]),
    )


def _parse_agent_run(
    text: str, *, agent_id: str, scenario_id: str, task: str, base_branch: str
) -> AgentRun:
    """Parse a model response into an :class:`AgentRun`.

    The runner-known identity fields (``agent_id``, ``scenario_id``,
    ``task``, ``base_branch``) override anything the model emitted, so that
    a hallucinated id cannot route the run to the wrong contract.
    """
    payload = extract_yaml_block(text).strip()
    if not payload:
        raise ValueError("Model response was empty after fence extraction")
    try:
        raw = yaml.safe_load(payload)
    except yaml.YAMLError as exc:
        raise ValueError(f"Could not parse model response as YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(
            f"Could not parse model response as a YAML mapping (got {type(raw).__name__})"
        )

    branch_name = str(raw.get("branch_name", ""))
    if not branch_name:
        raise ValueError("Model response did not include 'branch_name'")

    return AgentRun(
        agent_id=agent_id,
        scenario_id=scenario_id,
        task=task,
        base_branch=base_branch,
        branch_name=branch_name,
        commands=tuple(_build_command(c) for c in raw.get("commands", [])),
        questions=tuple(_build_question(q) for q in raw.get("questions", [])),
        commits=tuple(_build_commit(c) for c in raw.get("commits", [])),
        pr=_build_pr(raw.get("pr")),
        transcript_path=raw.get("transcript_path"),
    )


def _build_default_provider(config: AgentConfig) -> LLMProvider:
    """Construct an OllamaClient from the agent config."""
    from .ollama import OllamaClient

    kwargs: dict[str, Any] = {
        "model": config.model,
        "temperature": config.temperature,
        "timeout": config.timeout_seconds,
    }
    if config.endpoint:
        kwargs["base_url"] = config.endpoint
    return OllamaClient(**kwargs)


class OllamaAgentRunner:
    """Drive a local model through a scenario and return an :class:`AgentRun`."""

    def __init__(
        self,
        *,
        config: AgentConfig,
        scenarios_root: Path,
        provider: LLMProvider | None = None,
    ) -> None:
        if config.runner != "ollama":
            raise ValueError(
                f"OllamaAgentRunner requires runner=ollama, got {config.runner!r}"
            )
        self.config = config
        self.scenarios_root = scenarios_root
        self._provider = provider

    def _get_provider(self) -> LLMProvider:
        if self._provider is None:
            self._provider = _build_default_provider(self.config)
        return self._provider

    def list_scenarios(self) -> list[str]:
        if not self.scenarios_root.exists():
            return []
        return sorted(
            child.name
            for child in self.scenarios_root.iterdir()
            if child.is_dir() and (child / "task.yaml").is_file()
        )

    def run(self, scenario_id: str) -> AgentRun:
        scenario_dir = self.scenarios_root / scenario_id
        task = _load_scenario_task(scenario_dir)
        prompt = render_prompt(
            agent_id=self.config.id,
            scenario_id=scenario_id,
            task=task.task,
            base_branch=task.base_branch,
        )
        response = self._get_provider().generate(prompt)
        return _parse_agent_run(
            response,
            agent_id=self.config.id,
            scenario_id=scenario_id,
            task=task.task,
            base_branch=task.base_branch,
        )
