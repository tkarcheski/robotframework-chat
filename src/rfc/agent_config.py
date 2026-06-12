"""Typed configuration for coding agents in ``config/local_agents.yaml``.

Loads each ``agents:`` entry into a frozen :class:`AgentConfig` so that the
agentic-coding harness can pick a runner (``fake`` or ``ollama``) without
re-parsing YAML in each component.

A live local-model runner reads ``model``, ``endpoint``, ``temperature``, and
``timeout_seconds`` from this struct. ``env_vars`` declares which environment
variables, if set, override the YAML values at load time (e.g. setting
``OLLAMA_ENDPOINT`` overrides the YAML ``endpoint`` field).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_LOCAL_AGENTS_PATH = (
    Path(__file__).resolve().parent.parent.parent / "config" / "local_agents.yaml"
)

SUPPORTED_RUNNERS: frozenset[str] = frozenset({"fake", "ollama"})

# YAML field name -> environment variable that overrides it when set.
_ENV_OVERRIDABLE_FIELDS: dict[str, str] = {
    "endpoint": "OLLAMA_ENDPOINT",
    "model": "DEFAULT_MODEL",
}


@dataclass(frozen=True)
class SandboxLimits:
    """Per-container resource caps for tier:4 sandboxed runs (#290).

    Declared in ``config/local_agents.yaml`` under an agent's ``sandbox:``
    block. ``network_mode`` defaults to ``none`` — sandboxed agents get no
    network outside the container's scratch dir.
    """

    image: str = "python:3.11-slim"
    cpu_cores: float = 1.0
    memory_mb: int = 1024
    wall_clock_seconds: int = 300
    network_mode: str = "none"


def _coerce_sandbox(raw: Any, agent_id: str) -> SandboxLimits | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(
            f"Agent {agent_id!r} 'sandbox' must be a mapping, got {type(raw).__name__}"
        )
    known = {f for f in SandboxLimits.__dataclass_fields__}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ValueError(
            f"Agent {agent_id!r} sandbox block has unknown keys {unknown}. "
            f"Supported: {sorted(known)}"
        )
    limits = SandboxLimits(
        image=str(raw.get("image", SandboxLimits.image)),
        cpu_cores=float(raw.get("cpu_cores", SandboxLimits.cpu_cores)),
        memory_mb=int(raw.get("memory_mb", SandboxLimits.memory_mb)),
        wall_clock_seconds=int(
            raw.get("wall_clock_seconds", SandboxLimits.wall_clock_seconds)
        ),
        network_mode=str(raw.get("network_mode", SandboxLimits.network_mode)),
    )
    for cap in ("cpu_cores", "memory_mb", "wall_clock_seconds"):
        if getattr(limits, cap) <= 0:
            raise ValueError(
                f"Agent {agent_id!r} sandbox {cap} must be > 0, "
                f"got {getattr(limits, cap)}"
            )
    return limits


@dataclass(frozen=True)
class AgentConfig:
    """Frozen configuration for one coding agent."""

    id: str
    runner: str
    model: str = ""
    endpoint: str = ""
    timeout_seconds: int = 600
    temperature: float = 0.0
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    env_vars: tuple[str, ...] = field(default_factory=tuple)
    sandbox: SandboxLimits | None = None


def _opt_str(raw: dict[str, Any], key: str) -> str:
    """Return ``raw[key]`` as a string, mapping missing/null to ''.

    `str(None)` would silently produce the literal `'None'` (truthy), which
    bypasses validation like ``if not model``.
    """
    value = raw.get(key)
    return "" if value is None else str(value)


def _opt_seq(raw: dict[str, Any], key: str) -> tuple[str, ...]:
    """Return ``raw[key]`` as a tuple of strings, mapping missing/null to ()."""
    value = raw.get(key)
    if value is None:
        return ()
    return tuple(str(item) for item in value)


def _coerce(raw: dict[str, Any]) -> AgentConfig:
    if "id" not in raw:
        raise ValueError(f"Agent entry missing required key 'id': {raw!r}")
    agent_id = _opt_str(raw, "id")

    if "runner" not in raw:
        raise ValueError(f"Agent {agent_id!r} missing required key 'runner'")
    runner = _opt_str(raw, "runner").lower().strip()
    if runner not in SUPPORTED_RUNNERS:
        raise ValueError(
            f"Agent {agent_id!r} has unknown runner {runner!r}. "
            f"Supported: {sorted(SUPPORTED_RUNNERS)}"
        )

    model = _opt_str(raw, "model")
    endpoint = _opt_str(raw, "endpoint")
    env_vars = _opt_seq(raw, "env_vars")

    for field_name, env_name in _ENV_OVERRIDABLE_FIELDS.items():
        if env_name in env_vars:
            override = os.getenv(env_name, "")
            if override:
                if field_name == "endpoint":
                    endpoint = override
                elif field_name == "model":
                    model = override

    if runner == "ollama" and not model:
        raise ValueError(
            f"Agent {agent_id!r} uses runner=ollama and must declare a 'model' "
            f"(or set DEFAULT_MODEL with env_vars=[DEFAULT_MODEL])"
        )

    timeout_raw = raw.get("timeout_seconds")
    timeout_seconds = 600 if timeout_raw is None else int(timeout_raw)
    temperature_raw = raw.get("temperature")
    temperature = 0.0 if temperature_raw is None else float(temperature_raw)

    return AgentConfig(
        id=agent_id,
        runner=runner,
        model=model,
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
        temperature=temperature,
        capabilities=_opt_seq(raw, "capabilities"),
        env_vars=env_vars,
        sandbox=_coerce_sandbox(raw.get("sandbox"), agent_id),
    )


def load_agent_configs(path: Path | None = None) -> dict[str, AgentConfig]:
    """Load every agent entry from ``local_agents.yaml`` keyed by id."""
    yaml_path = path or DEFAULT_LOCAL_AGENTS_PATH
    data = yaml.safe_load(yaml_path.read_text()) or {}
    out: dict[str, AgentConfig] = {}
    for raw in data.get("agents", []):
        cfg = _coerce(raw)
        if cfg.id in out:
            raise ValueError(f"Duplicate agent id {cfg.id!r} in {yaml_path}")
        out[cfg.id] = cfg
    return out


def load_agent_config(agent_id: str, *, path: Path | None = None) -> AgentConfig:
    """Load one agent by id. Raises :class:`KeyError` if not present."""
    configs = load_agent_configs(path=path)
    if agent_id not in configs:
        raise KeyError(
            f"Agent {agent_id!r} missing from {path or DEFAULT_LOCAL_AGENTS_PATH}"
        )
    return configs[agent_id]
