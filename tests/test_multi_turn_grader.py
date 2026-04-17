"""Tests for rfc.multi_turn_grader.MultiTurnGrader."""

from unittest.mock import MagicMock

import pytest

from rfc.multi_turn_grader import MultiTurnGrader


class TestMultiTurnGraderInit:
    def test_none_client_raises(self) -> None:
        with pytest.raises(TypeError, match="must not be None"):
            MultiTurnGrader(None)

    def test_valid_client_accepted(self) -> None:
        grader = MultiTurnGrader(MagicMock())
        assert grader.llm is not None


class TestGradeFactConsistency:
    def test_returns_grade_result(self) -> None:
        client = MagicMock()
        client.generate.return_value = '{"score": 0.9, "reason": "consistent"}'
        grader = MultiTurnGrader(client)
        result = grader.grade_fact_consistency(
            "User birthday is March 15",
            [
                "March 15th is your birthday!",
                "hiking gear",
                "Your birthday is March 15.",
            ],
            [0, 2],
        )
        assert result.score == 0.9
        assert result.reason == "consistent"

    def test_prompt_contains_fact_and_responses(self) -> None:
        client = MagicMock()
        client.generate.return_value = '{"score": 1.0, "reason": "ok"}'
        grader = MultiTurnGrader(client)
        grader.grade_fact_consistency(
            "birthday is March 15",
            ["Response A", "Response B", "Response C"],
            [0, 2],
        )
        prompt = client.generate.call_args[0][0]
        assert "birthday is March 15" in prompt
        assert "Response A" in prompt
        assert "Response C" in prompt
        # Response B is not probed so should not appear in probe texts
        assert "Response B" not in prompt

    def test_invalid_json_raises(self) -> None:
        client = MagicMock()
        client.generate.return_value = "not json"
        grader = MultiTurnGrader(client)
        with pytest.raises(ValueError, match="invalid JSON"):
            grader.grade_fact_consistency("fact", ["resp"], [0])

    def test_missing_fields_raises(self) -> None:
        client = MagicMock()
        client.generate.return_value = '{"score": 0.5}'
        grader = MultiTurnGrader(client)
        with pytest.raises(ValueError, match="missing required fields"):
            grader.grade_fact_consistency("fact", ["resp"], [0])


class TestGradeInstructionCompliance:
    def test_returns_grade_result(self) -> None:
        client = MagicMock()
        client.generate.return_value = '{"score": 0.8, "reason": "mostly bullets"}'
        grader = MultiTurnGrader(client)
        result = grader.grade_instruction_compliance(
            "respond in bullet points",
            "- point one\n- point two",
        )
        assert result.score == 0.8
        assert "bullets" in result.reason

    def test_prompt_contains_constraint_and_response(self) -> None:
        client = MagicMock()
        client.generate.return_value = '{"score": 1.0, "reason": "ok"}'
        grader = MultiTurnGrader(client)
        grader.grade_instruction_compliance("only bullet points", "- item 1")
        prompt = client.generate.call_args[0][0]
        assert "only bullet points" in prompt
        assert "- item 1" in prompt


class TestGradeTopicIsolation:
    def test_returns_grade_result(self) -> None:
        client = MagicMock()
        client.generate.return_value = '{"score": 0.95, "reason": "no bleed"}'
        grader = MultiTurnGrader(client)
        result = grader.grade_topic_isolation(
            "Italian cooking",
            "black hole formation",
            "Black holes form when massive stars collapse.",
        )
        assert result.score == 0.95
        assert "bleed" in result.reason

    def test_prompt_contains_both_topics(self) -> None:
        client = MagicMock()
        client.generate.return_value = '{"score": 1.0, "reason": "ok"}'
        grader = MultiTurnGrader(client)
        grader.grade_topic_isolation(
            "gardening", "cryptocurrency", "Bitcoin uses proof of work."
        )
        prompt = client.generate.call_args[0][0]
        assert "gardening" in prompt
        assert "cryptocurrency" in prompt
        assert "Bitcoin uses proof of work" in prompt
