"""Tests for the AgentConfig dataclass and local_agents.yaml loader."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from rfc.agent_config import (
    AgentConfig,
    DEFAULT_LOCAL_AGENTS_PATH,
    load_agent_config,
    load_agent_configs,
)


def _write_agents_yaml(tmp_path: Path, agents: list[dict[str, object]]) -> Path:
    path = tmp_path / "local_agents.yaml"
    path.write_text(yaml.safe_dump({"agents": agents, "executions": []}))
    return path


class TestAgentConfigDefaults:
    def test_runner_required(self, tmp_path: Path) -> None:
        path = _write_agents_yaml(tmp_path, [{"id": "foo"}])
        with pytest.raises(ValueError, match="runner"):
            load_agent_config("foo", path=path)

    def test_id_required(self, tmp_path: Path) -> None:
        path = _write_agents_yaml(tmp_path, [{"runner": "fake"}])
        with pytest.raises(ValueError, match="id"):
            load_agent_configs(path=path)

    def test_fake_runner_does_not_require_model(self, tmp_path: Path) -> None:
        path = _write_agents_yaml(tmp_path, [{"id": "claude-code", "runner": "fake"}])
        cfg = load_agent_config("claude-code", path=path)
        assert cfg.id == "claude-code"
        assert cfg.runner == "fake"
        assert cfg.model == ""
        assert cfg.endpoint == ""

    def test_ollama_runner_requires_model(self, tmp_path: Path) -> None:
        path = _write_agents_yaml(
            tmp_path, [{"id": "ollama-local", "runner": "ollama"}]
        )
        with pytest.raises(ValueError, match="model"):
            load_agent_config("ollama-local", path=path)

    def test_unknown_runner_rejected(self, tmp_path: Path) -> None:
        path = _write_agents_yaml(tmp_path, [{"id": "x", "runner": "bogus"}])
        with pytest.raises(ValueError, match="runner"):
            load_agent_config("x", path=path)


class TestAgentConfigParsing:
    def test_full_ollama_entry(self, tmp_path: Path) -> None:
        path = _write_agents_yaml(
            tmp_path,
            [
                {
                    "id": "ollama-local",
                    "runner": "ollama",
                    "model": "phi4:14b",
                    "endpoint": "http://localhost:11434",
                    "timeout_seconds": 600,
                    "temperature": 0.0,
                    "capabilities": ["git", "pr"],
                    "env_vars": ["OLLAMA_ENDPOINT"],
                }
            ],
        )
        cfg = load_agent_config("ollama-local", path=path)
        assert isinstance(cfg, AgentConfig)
        assert cfg.runner == "ollama"
        assert cfg.model == "phi4:14b"
        assert cfg.endpoint == "http://localhost:11434"
        assert cfg.timeout_seconds == 600
        assert cfg.temperature == 0.0
        assert cfg.capabilities == ("git", "pr")
        assert cfg.env_vars == ("OLLAMA_ENDPOINT",)

    def test_load_all_returns_dict_keyed_by_id(self, tmp_path: Path) -> None:
        path = _write_agents_yaml(
            tmp_path,
            [
                {"id": "a", "runner": "fake"},
                {"id": "b", "runner": "ollama", "model": "m"},
            ],
        )
        configs = load_agent_configs(path=path)
        assert set(configs) == {"a", "b"}
        assert configs["b"].model == "m"

    def test_unknown_id_raises_keyerror(self, tmp_path: Path) -> None:
        path = _write_agents_yaml(tmp_path, [{"id": "a", "runner": "fake"}])
        with pytest.raises(KeyError, match="missing"):
            load_agent_config("missing", path=path)

    def test_duplicate_ids_rejected(self, tmp_path: Path) -> None:
        path = _write_agents_yaml(
            tmp_path,
            [
                {"id": "dup", "runner": "fake"},
                {"id": "dup", "runner": "fake"},
            ],
        )
        with pytest.raises(ValueError, match="duplicate"):
            load_agent_configs(path=path)


class TestEnvOverrides:
    def test_endpoint_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = _write_agents_yaml(
            tmp_path,
            [
                {
                    "id": "ollama-local",
                    "runner": "ollama",
                    "model": "phi4:14b",
                    "endpoint": "http://from-yaml:11434",
                    "env_vars": ["OLLAMA_ENDPOINT"],
                }
            ],
        )
        monkeypatch.setenv("OLLAMA_ENDPOINT", "http://from-env:11434")
        cfg = load_agent_config("ollama-local", path=path)
        assert cfg.endpoint == "http://from-env:11434"

    def test_no_env_override_when_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = _write_agents_yaml(
            tmp_path,
            [
                {
                    "id": "ollama-local",
                    "runner": "ollama",
                    "model": "phi4:14b",
                    "endpoint": "http://from-yaml:11434",
                    "env_vars": ["OLLAMA_ENDPOINT"],
                }
            ],
        )
        monkeypatch.delenv("OLLAMA_ENDPOINT", raising=False)
        cfg = load_agent_config("ollama-local", path=path)
        assert cfg.endpoint == "http://from-yaml:11434"


class TestRepoLocalAgentsYaml:
    def test_default_path_resolves(self) -> None:
        assert DEFAULT_LOCAL_AGENTS_PATH.is_file()

    def test_repo_local_agents_yaml_loads(self) -> None:
        configs = load_agent_configs()
        assert "claude-code" in configs
        assert configs["claude-code"].runner == "fake"
