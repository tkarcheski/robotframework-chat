"""Tests for src/rfc/agent_memory_manager.py."""

from __future__ import annotations

import time

import pytest

from rfc.agent_memory_manager import MemoryManager


class TestShortTerm:
    def test_appends_messages(self) -> None:
        mgr = MemoryManager(memory_size=3)
        mgr.add_to_short_term("a")
        mgr.add_to_short_term("b")
        assert mgr.memory.short_term == ["a", "b"]

    def test_evicts_oldest_when_full(self) -> None:
        mgr = MemoryManager(memory_size=2)
        mgr.add_to_short_term("a")
        mgr.add_to_short_term("b")
        mgr.add_to_short_term("c")
        assert mgr.memory.short_term == ["b", "c"]

    def test_get_context_joins_with_newlines(self) -> None:
        mgr = MemoryManager()
        mgr.add_to_short_term("first")
        mgr.add_to_short_term("second")
        assert mgr.get_short_term_context() == "first\nsecond"

    def test_clear_short_term(self) -> None:
        mgr = MemoryManager()
        mgr.add_to_short_term("a")
        mgr.clear_short_term()
        assert mgr.memory.short_term == []


class TestInit:
    def test_rejects_zero_memory_size(self) -> None:
        with pytest.raises(ValueError, match="memory_size"):
            MemoryManager(memory_size=0)

    def test_rejects_negative_memory_size(self) -> None:
        with pytest.raises(ValueError, match="memory_size"):
            MemoryManager(memory_size=-1)


class TestLongTermVectors:
    def test_stores_vector(self) -> None:
        mgr = MemoryManager()
        mgr.add_long_term_vector("doc1", [0.1, 0.2, 0.3])
        assert mgr.memory.long_term_vectors["doc1"] == [0.1, 0.2, 0.3]

    def test_rejects_empty_vector(self) -> None:
        mgr = MemoryManager()
        with pytest.raises(ValueError, match="non-empty"):
            mgr.add_long_term_vector("doc1", [])

    def test_stores_copy_not_reference(self) -> None:
        mgr = MemoryManager()
        original = [1.0, 2.0]
        mgr.add_long_term_vector("k", original)
        original.append(3.0)
        assert mgr.memory.long_term_vectors["k"] == [1.0, 2.0]


class TestPersistentFacts:
    def test_stores_fact_without_schema(self) -> None:
        mgr = MemoryManager()
        mgr.add_persistent_fact("user_id", 42)
        assert mgr.get_persistent_fact("user_id") == 42

    def test_returns_default_when_missing(self) -> None:
        mgr = MemoryManager()
        assert mgr.get_persistent_fact("missing", default="x") == "x"

    def test_validates_string_type(self) -> None:
        mgr = MemoryManager()
        mgr.add_persistent_fact("name", "alice", {"type": "string"})
        with pytest.raises(ValueError, match="Expected string"):
            mgr.add_persistent_fact("name", 123, {"type": "string"})

    def test_validates_object_with_required_keys(self) -> None:
        mgr = MemoryManager()
        schema = {"type": "object", "required": ["id", "name"]}
        mgr.add_persistent_fact("user", {"id": 1, "name": "x"}, schema)
        with pytest.raises(ValueError, match="Missing required key: name"):
            mgr.add_persistent_fact("user2", {"id": 2}, schema)

    def test_validates_nested_properties(self) -> None:
        mgr = MemoryManager()
        schema = {
            "type": "object",
            "required": ["count"],
            "properties": {"count": {"type": "integer"}},
        }
        mgr.add_persistent_fact("metric", {"count": 5}, schema)
        with pytest.raises(ValueError, match="Expected integer"):
            mgr.add_persistent_fact("metric2", {"count": "five"}, schema)

    def test_rejects_unknown_schema_type(self) -> None:
        mgr = MemoryManager()
        with pytest.raises(ValueError, match="Unsupported schema type"):
            mgr.add_persistent_fact("x", "y", {"type": "weird"})

    def test_rejects_bool_for_integer_schema(self) -> None:
        # bool is a subclass of int in Python, so isinstance(True, int) is
        # True. Numeric schemas must reject booleans explicitly.
        mgr = MemoryManager()
        with pytest.raises(ValueError, match="Expected integer"):
            mgr.add_persistent_fact("count", True, {"type": "integer"})

    def test_rejects_bool_for_number_schema(self) -> None:
        mgr = MemoryManager()
        with pytest.raises(ValueError, match="Expected number"):
            mgr.add_persistent_fact("ratio", False, {"type": "number"})

    def test_accepts_bool_for_boolean_schema(self) -> None:
        mgr = MemoryManager()
        mgr.add_persistent_fact("flag", True, {"type": "boolean"})
        assert mgr.get_persistent_fact("flag") is True


class TestExecutionLedger:
    def test_logs_action_with_timestamp(self) -> None:
        mgr = MemoryManager()
        before = time.time()
        mgr.log_action({"action": "tool_call", "tool": "git"})
        after = time.time()
        assert mgr.ledger_size() == 1
        entry = mgr.memory.execution_ledger[0]
        assert entry["action"] == "tool_call"
        assert before <= entry["timestamp"] <= after

    def test_multiple_actions_preserve_order(self) -> None:
        mgr = MemoryManager()
        mgr.log_action({"step": 1})
        mgr.log_action({"step": 2})
        mgr.log_action({"step": 3})
        assert [e["step"] for e in mgr.memory.execution_ledger] == [1, 2, 3]

    def test_reserved_timestamp_key_rejected(self) -> None:
        mgr = MemoryManager()
        with pytest.raises(ValueError, match="reserved"):
            mgr.log_action({"action": "x", "timestamp": 0})
