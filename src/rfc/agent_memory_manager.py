"""Manage short-term, long-term, and persistent memory for an agent."""

from __future__ import annotations

import time
from typing import Any

from .agent_memory import AgentMemory


class MemoryManager:
    """Sliding-window short-term, vector long-term, schema-checked persistent facts."""

    def __init__(self, memory_size: int = 5) -> None:
        if memory_size < 1:
            raise ValueError("memory_size must be >= 1")
        self.memory = AgentMemory()
        self.memory_size = memory_size

    def add_to_short_term(self, message: str) -> None:
        self.memory.short_term.append(message)
        while len(self.memory.short_term) > self.memory_size:
            self.memory.short_term.pop(0)

    def get_short_term_context(self) -> str:
        return "\n".join(self.memory.short_term)

    def clear_short_term(self) -> None:
        self.memory.short_term.clear()

    def add_long_term_vector(self, key: str, vector: list[float]) -> None:
        if not vector:
            raise ValueError("vector must be non-empty")
        self.memory.long_term_vectors[key] = list(vector)

    def add_persistent_fact(
        self,
        key: str,
        value: Any,
        schema: dict[str, Any] | None = None,
    ) -> None:
        if schema is not None:
            _validate_against_schema(value, schema)
        self.memory.persistent_facts[key] = value

    def get_persistent_fact(self, key: str, default: Any = None) -> Any:
        return self.memory.persistent_facts.get(key, default)

    def log_action(self, action: dict[str, Any]) -> None:
        if "timestamp" in action:
            raise ValueError("'timestamp' is reserved and set by the manager")
        self.memory.execution_ledger.append({**action, "timestamp": time.time()})

    def ledger_size(self) -> int:
        return len(self.memory.execution_ledger)


_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


def _validate_against_schema(value: Any, schema: dict[str, Any]) -> None:
    """Lightweight JSON-Schema-shaped check: type + required keys, no external deps."""
    expected_type = schema.get("type")
    if expected_type is not None:
        py_type = _TYPE_MAP.get(expected_type)
        if py_type is None:
            raise ValueError(f"Unsupported schema type: {expected_type}")
        if not isinstance(value, py_type):
            raise ValueError(
                f"Expected {expected_type}, got {type(value).__name__}"
            )

    required = schema.get("required", [])
    if required:
        if not isinstance(value, dict):
            raise ValueError("'required' is only valid for object values")
        for key in required:
            if key not in value:
                raise ValueError(f"Missing required key: {key}")

    properties = schema.get("properties", {})
    if properties and isinstance(value, dict):
        for prop_name, prop_schema in properties.items():
            if prop_name in value:
                _validate_against_schema(value[prop_name], prop_schema)
