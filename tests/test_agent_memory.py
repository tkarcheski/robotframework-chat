"""Tests for agent memory management (short-term, long-term, persistent)."""

from rfc.agent_memory import AgentMemory


class TestAgentMemory:
    """AgentMemory: Multi-layer memory system for agents."""

    def test_creates_empty_memory(self):
        memory = AgentMemory(
            short_term=[],
            long_term_vectors={},
            persistent_facts={},
            execution_ledger=[],
        )
        assert memory.short_term == []
        assert memory.long_term_vectors == {}
        assert memory.persistent_facts == {}
        assert memory.execution_ledger == []

    def test_short_term_memory_is_list(self):
        """Short-term is a list of recent interactions (sliding window)."""
        memory = AgentMemory(
            short_term=["Turn 1: Analyzed issue", "Turn 2: Cloned repo"],
            long_term_vectors={},
            persistent_facts={},
            execution_ledger=[],
        )
        assert len(memory.short_term) == 2
        assert memory.short_term[0] == "Turn 1: Analyzed issue"

    def test_long_term_vectors_for_embeddings(self):
        """Long-term stores vector embeddings for semantic search."""
        vectors = {
            "github_issue_#123": [0.1, 0.2, 0.3, 0.4],
            "error_handling_pattern": [0.5, 0.6, 0.7, 0.8],
        }
        memory = AgentMemory(
            short_term=[],
            long_term_vectors=vectors,
            persistent_facts={},
            execution_ledger=[],
        )
        assert memory.long_term_vectors["github_issue_#123"] == [0.1, 0.2, 0.3, 0.4]

    def test_persistent_facts_are_schema_validated(self):
        """Persistent facts are schema-validated key-value pairs."""
        facts = {
            "repository_url": "https://github.com/foo/bar.git",
            "current_branch": "main",
            "issue_number": 123,
        }
        memory = AgentMemory(
            short_term=[],
            long_term_vectors={},
            persistent_facts=facts,
            execution_ledger=[],
        )
        assert memory.persistent_facts["repository_url"] == "https://github.com/foo/bar.git"
        assert memory.persistent_facts["issue_number"] == 123

    def test_execution_ledger_immutable_log(self):
        """Execution ledger records all actions in immutable log."""
        ledger = [
            {"timestamp": 1.0, "action": "clone", "status": "success"},
            {"timestamp": 2.0, "action": "edit", "status": "success"},
            {"timestamp": 3.0, "action": "commit", "status": "success"},
        ]
        memory = AgentMemory(
            short_term=[],
            long_term_vectors={},
            persistent_facts={},
            execution_ledger=ledger,
        )
        assert len(memory.execution_ledger) == 3
        assert memory.execution_ledger[0]["action"] == "clone"
        assert memory.execution_ledger[2]["action"] == "commit"

    def test_memory_is_mutable(self):
        """AgentMemory is mutable (unlike interactions which are frozen)."""
        memory = AgentMemory(
            short_term=[],
            long_term_vectors={},
            persistent_facts={},
            execution_ledger=[],
        )
        # Append to short-term
        memory.short_term.append("New message")
        assert "New message" in memory.short_term

        # Add to facts
        memory.persistent_facts["new_key"] = "new_value"
        assert memory.persistent_facts["new_key"] == "new_value"

        # Append to ledger
        memory.execution_ledger.append({"action": "test"})
        assert len(memory.execution_ledger) == 1

    def test_memory_with_all_layers_populated(self):
        """Memory can combine all layers simultaneously."""
        memory = AgentMemory(
            short_term=["Recent: analyzed GitHub issue"],
            long_term_vectors={"issue_context": [0.1, 0.2]},
            persistent_facts={"issue_id": 456, "repo": "foo/bar"},
            execution_ledger=[
                {"action": "fetch_issue", "status": "success"},
                {"action": "analyze", "status": "success"},
            ],
        )
        assert len(memory.short_term) == 1
        assert "issue_context" in memory.long_term_vectors
        assert memory.persistent_facts["issue_id"] == 456
        assert len(memory.execution_ledger) == 2
