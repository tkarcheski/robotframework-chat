"""Tests for the AgentConfig dataclass and local_agents.yaml loader."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from rfc.agent_config import (
    AgentConfig,
    DEFAULT_LOCAL_AGENTS_PATH,
    SandboxLimits,
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


class TestNullValuesInYaml:
    """A YAML ``null`` for a present key is not the same as a missing key.

    ``raw.get("model", "")`` returns ``None`` when the key exists with value
    null; ``str(None)`` is then ``"None"`` -- a truthy string that silently
    bypasses the ``not model`` validation. Treat null and missing identically
    so misconfigured YAML fails loudly at load time.
    """

    def test_null_model_on_ollama_runner_is_rejected(self, tmp_path: Path) -> None:
        path = _write_agents_yaml(
            tmp_path, [{"id": "ollama-local", "runner": "ollama", "model": None}]
        )
        with pytest.raises(ValueError, match="model"):
            load_agent_config("ollama-local", path=path)

    def test_null_endpoint_treated_as_empty(self, tmp_path: Path) -> None:
        path = _write_agents_yaml(
            tmp_path,
            [
                {
                    "id": "ollama-local",
                    "runner": "ollama",
                    "model": "phi4:14b",
                    "endpoint": None,
                }
            ],
        )
        cfg = load_agent_config("ollama-local", path=path)
        assert cfg.endpoint == ""

    def test_null_env_vars_treated_as_empty_tuple(self, tmp_path: Path) -> None:
        path = _write_agents_yaml(
            tmp_path,
            [
                {
                    "id": "ollama-local",
                    "runner": "ollama",
                    "model": "phi4:14b",
                    "env_vars": None,
                }
            ],
        )
        cfg = load_agent_config("ollama-local", path=path)
        assert cfg.env_vars == ()

    def test_null_capabilities_treated_as_empty_tuple(self, tmp_path: Path) -> None:
        path = _write_agents_yaml(
            tmp_path,
            [
                {
                    "id": "ollama-local",
                    "runner": "ollama",
                    "model": "phi4:14b",
                    "capabilities": None,
                }
            ],
        )
        cfg = load_agent_config("ollama-local", path=path)
        assert cfg.capabilities == ()

    def test_null_timeout_falls_back_to_default(self, tmp_path: Path) -> None:
        path = _write_agents_yaml(
            tmp_path,
            [
                {
                    "id": "ollama-local",
                    "runner": "ollama",
                    "model": "phi4:14b",
                    "timeout_seconds": None,
                }
            ],
        )
        cfg = load_agent_config("ollama-local", path=path)
        assert cfg.timeout_seconds == 600

    def test_explicit_zero_timeout_is_preserved(self, tmp_path: Path) -> None:
        """`or` short-circuit must not turn explicit 0 into the default."""
        path = _write_agents_yaml(
            tmp_path,
            [
                {
                    "id": "ollama-local",
                    "runner": "ollama",
                    "model": "phi4:14b",
                    "timeout_seconds": 0,
                }
            ],
        )
        cfg = load_agent_config("ollama-local", path=path)
        assert cfg.timeout_seconds == 0

    def test_null_temperature_falls_back_to_default(self, tmp_path: Path) -> None:
        path = _write_agents_yaml(
            tmp_path,
            [
                {
                    "id": "ollama-local",
                    "runner": "ollama",
                    "model": "phi4:14b",
                    "temperature": None,
                }
            ],
        )
        cfg = load_agent_config("ollama-local", path=path)
        assert cfg.temperature == 0.0


class TestSandboxLimits:
    """Resource caps for tier:4 sandboxed runs (#290)."""

    def test_absent_sandbox_block_is_none(self, tmp_path: Path) -> None:
        path = _write_agents_yaml(tmp_path, [{"id": "claude-code", "runner": "fake"}])
        cfg = load_agent_config("claude-code", path=path)
        assert cfg.sandbox is None

    def test_full_sandbox_block(self, tmp_path: Path) -> None:
        path = _write_agents_yaml(
            tmp_path,
            [
                {
                    "id": "claude-code",
                    "runner": "fake",
                    "sandbox": {
                        "image": "python:3.11-slim",
                        "cpu_cores": 0.5,
                        "memory_mb": 256,
                        "wall_clock_seconds": 120,
                        "network_mode": "none",
                    },
                }
            ],
        )
        cfg = load_agent_config("claude-code", path=path)
        assert cfg.sandbox == SandboxLimits(
            image="python:3.11-slim",
            cpu_cores=0.5,
            memory_mb=256,
            wall_clock_seconds=120,
            network_mode="none",
        )

    def test_sandbox_defaults_fill_missing_keys(self, tmp_path: Path) -> None:
        path = _write_agents_yaml(
            tmp_path,
            [{"id": "claude-code", "runner": "fake", "sandbox": {}}],
        )
        cfg = load_agent_config("claude-code", path=path)
        assert cfg.sandbox is not None
        assert cfg.sandbox.image == "python:3.11-slim"
        assert cfg.sandbox.cpu_cores > 0
        assert cfg.sandbox.memory_mb > 0
        assert cfg.sandbox.wall_clock_seconds > 0
        assert cfg.sandbox.network_mode == "none"

    def test_sandbox_unknown_key_rejected(self, tmp_path: Path) -> None:
        path = _write_agents_yaml(
            tmp_path,
            [{"id": "x", "runner": "fake", "sandbox": {"gpus": 8}}],
        )
        with pytest.raises(ValueError, match="gpus"):
            load_agent_config("x", path=path)

    def test_sandbox_nonpositive_wall_clock_rejected(self, tmp_path: Path) -> None:
        path = _write_agents_yaml(
            tmp_path,
            [{"id": "x", "runner": "fake", "sandbox": {"wall_clock_seconds": 0}}],
        )
        with pytest.raises(ValueError, match="wall_clock_seconds"):
            load_agent_config("x", path=path)

    def test_shipped_claude_code_entry_declares_sandbox_caps(self) -> None:
        """#290 acceptance: caps declared in config/local_agents.yaml."""
        cfg = load_agent_config("claude-code", path=DEFAULT_LOCAL_AGENTS_PATH)
        assert cfg.sandbox is not None
        assert cfg.sandbox.network_mode == "none"
