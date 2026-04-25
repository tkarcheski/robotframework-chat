"""Multi-layer memory management for agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentMemory:
    """Multi-layer memory: short-term, long-term, and persistent."""

    short_term: list[str] = field(default_factory=list)
    long_term_vectors: dict[str, list[float]] = field(default_factory=dict)
    persistent_facts: dict[str, Any] = field(default_factory=dict)
    execution_ledger: list[dict[str, Any]] = field(default_factory=list)
