"""Tests for rfc.analyzer_agent — AnalyzerAgent, FailureRecord, Recommendation."""

import json
from unittest.mock import MagicMock

import pytest

from rfc.analyzer_agent import (
    AnalyzerAgent,
    FailureRecord,
    Recommendation,
    _extract_first_json_object,
)


class TestFailureRecord:
    def test_basic_creation(self):
        rec = FailureRecord(
            test_name="Test Math Addition",
            test_suite="math",
            model_name="phi4:14b",
            question="What is 2+2?",
            expected_answer="4",
            actual_answer="5",
            grading_reason="Incorrect arithmetic",
            score=0.0,
        )
        assert rec.test_name == "Test Math Addition"
        assert rec.model_name == "phi4:14b"
        assert rec.score == 0.0
        assert rec.self_healing_strategies_tried == []

    def test_with_strategies(self):
        rec = FailureRecord(
            test_name="Test",
            test_suite="safety",
            model_name="model",
            question="q",
            expected_answer="e",
            actual_answer="a",
            grading_reason="r",
            score=0.3,
            self_healing_strategies_tried=["original", "prompt"],
        )
        assert rec.self_healing_strategies_tried == ["original", "prompt"]


class TestRecommendation:
    def test_basic_creation(self):
        rec = Recommendation(
            recommendation_type="prompt",
            test_name="Test Math",
            details="Add clarification",
            confidence=0.8,
        )
        assert rec.recommendation_type == "prompt"
        assert rec.confidence == 0.8
        assert rec.suggested_prompt == ""
        assert rec.suggested_params == {}

    def test_with_suggested_prompt(self):
        rec = Recommendation(
            recommendation_type="prompt",
            test_name="Test",
            details="Rewrite",
            confidence=0.9,
            suggested_prompt="Better prompt",
        )
        assert rec.suggested_prompt == "Better prompt"


class TestAnalyzerAgent:
    def test_init_none_client_rejected(self):
        with pytest.raises(TypeError, match="must not be None"):
            AnalyzerAgent(None)

    def test_init_with_client(self):
        client = MagicMock()
        agent = AnalyzerAgent(client)
        assert agent.llm is client

    def test_analyze_single_prompt_recommendation(self):
        client = MagicMock()
        client.generate.return_value = json.dumps(
            {
                "recommendation_type": "prompt",
                "details": "Add examples to the prompt",
                "confidence": 0.85,
                "suggested_prompt": "What is 2+2? (answer with a number)",
                "suggested_params": {},
            }
        )
        agent = AnalyzerAgent(client)
        failure = FailureRecord(
            test_name="Test Math",
            test_suite="math",
            model_name="phi4:14b",
            question="What is 2+2?",
            expected_answer="4",
            actual_answer="two plus two equals four",
            grading_reason="Format mismatch",
            score=0.3,
        )
        recs = agent.analyze_failures([failure])
        assert len(recs) == 1
        assert recs[0].recommendation_type == "prompt"
        assert recs[0].confidence == 0.85

    def test_analyze_params_recommendation(self):
        client = MagicMock()
        client.generate.return_value = json.dumps(
            {
                "recommendation_type": "params",
                "details": "Lower temperature for deterministic output",
                "confidence": 0.7,
                "suggested_params": {"temperature": 0.0},
            }
        )
        agent = AnalyzerAgent(client)
        failure = FailureRecord(
            test_name="Test",
            test_suite="math",
            model_name="model",
            question="q",
            expected_answer="e",
            actual_answer="a",
            grading_reason="r",
            score=0.0,
        )
        recs = agent.analyze_failures([failure])
        assert recs[0].recommendation_type == "params"
        assert recs[0].suggested_params == {"temperature": 0.0}

    def test_analyze_handles_invalid_json(self):
        client = MagicMock()
        client.generate.return_value = "not valid json at all"
        agent = AnalyzerAgent(client)
        failure = FailureRecord(
            test_name="Test",
            test_suite="math",
            model_name="model",
            question="q",
            expected_answer="e",
            actual_answer="a",
            grading_reason="r",
            score=0.0,
        )
        recs = agent.analyze_failures([failure])
        assert len(recs) == 1
        assert recs[0].recommendation_type == "escalate"

    def test_analyze_handles_json_in_markdown(self):
        client = MagicMock()
        client.generate.return_value = (
            "Here is my analysis:\n```json\n"
            '{"recommendation_type": "input", "details": "change input", '
            '"confidence": 0.6}\n```'
        )
        agent = AnalyzerAgent(client)
        failure = FailureRecord(
            test_name="Test",
            test_suite="math",
            model_name="model",
            question="q",
            expected_answer="e",
            actual_answer="a",
            grading_reason="r",
            score=0.0,
        )
        recs = agent.analyze_failures([failure])
        assert recs[0].recommendation_type == "input"

    def test_analyze_handles_exception(self):
        client = MagicMock()
        client.generate.side_effect = RuntimeError("LLM unavailable")
        agent = AnalyzerAgent(client)
        failure = FailureRecord(
            test_name="Test",
            test_suite="math",
            model_name="model",
            question="q",
            expected_answer="e",
            actual_answer="a",
            grading_reason="r",
            score=0.0,
        )
        recs = agent.analyze_failures([failure])
        assert len(recs) == 1
        assert recs[0].recommendation_type == "escalate"
        assert "LLM unavailable" in recs[0].details

    def test_analyze_invalid_type_defaults_to_escalate(self):
        client = MagicMock()
        client.generate.return_value = json.dumps(
            {
                "recommendation_type": "invalid_type",
                "details": "something",
                "confidence": 0.5,
            }
        )
        agent = AnalyzerAgent(client)
        failure = FailureRecord(
            test_name="Test",
            test_suite="math",
            model_name="model",
            question="q",
            expected_answer="e",
            actual_answer="a",
            grading_reason="r",
            score=0.0,
        )
        recs = agent.analyze_failures([failure])
        assert recs[0].recommendation_type == "escalate"

    def test_analyze_multiple_failures(self):
        client = MagicMock()
        client.generate.return_value = json.dumps(
            {
                "recommendation_type": "prompt",
                "details": "fix it",
                "confidence": 0.9,
            }
        )
        agent = AnalyzerAgent(client)
        failures = [
            FailureRecord(
                test_name=f"Test {i}",
                test_suite="math",
                model_name="model",
                question="q",
                expected_answer="e",
                actual_answer="a",
                grading_reason="r",
                score=0.0,
            )
            for i in range(3)
        ]
        recs = agent.analyze_failures(failures)
        assert len(recs) == 3
        assert client.generate.call_count == 3


class TestCreateTrainingPairs:
    def test_basic_pair_creation(self):
        client = MagicMock()
        agent = AnalyzerAgent(client)
        failure = FailureRecord(
            test_name="Test Math",
            test_suite="math",
            model_name="phi4:14b",
            question="What is 2+2?",
            expected_answer="4",
            actual_answer="five",
            grading_reason="wrong",
            score=0.0,
        )
        pairs = agent.create_training_pairs([failure])
        assert len(pairs) == 1
        pair = pairs[0]
        assert pair["messages"][0]["role"] == "user"
        assert pair["messages"][0]["content"] == "What is 2+2?"
        assert pair["messages"][1]["role"] == "assistant"
        assert pair["messages"][1]["content"] == "4"
        assert pair["metadata"]["source"] == "failure"
        assert pair["metadata"]["model_name"] == "phi4:14b"

    def test_multiple_pairs(self):
        client = MagicMock()
        agent = AnalyzerAgent(client)
        failures = [
            FailureRecord(
                test_name=f"Test {i}",
                test_suite="math",
                model_name="model",
                question=f"Q{i}",
                expected_answer=f"A{i}",
                actual_answer="wrong",
                grading_reason="r",
                score=0.0,
            )
            for i in range(5)
        ]
        pairs = agent.create_training_pairs(failures)
        assert len(pairs) == 5
        for i, pair in enumerate(pairs):
            assert pair["messages"][0]["content"] == f"Q{i}"
            assert pair["messages"][1]["content"] == f"A{i}"

    def test_empty_failures(self):
        client = MagicMock()
        agent = AnalyzerAgent(client)
        pairs = agent.create_training_pairs([])
        assert pairs == []


class TestExtractFirstJsonObject:
    def test_flat_object(self):
        assert _extract_first_json_object('{"a": 1}') == '{"a": 1}'

    def test_nested_object_round_trips(self):
        text = '{"recommendation_type": "params", "suggested_params": {"temperature": 0.0, "seed": 42}}'
        extracted = _extract_first_json_object(text)
        assert extracted == text
        # The whole point — json.loads must succeed.
        parsed = json.loads(extracted)
        assert parsed["suggested_params"]["temperature"] == 0.0

    def test_object_inside_markdown_fence(self):
        text = 'Here is my analysis:\n```json\n{"recommendation_type": "prompt", "details": {"why": "unclear"}}\n```\nDone.'
        extracted = _extract_first_json_object(text)
        assert extracted is not None
        parsed = json.loads(extracted)
        assert parsed["recommendation_type"] == "prompt"
        assert parsed["details"]["why"] == "unclear"

    def test_braces_inside_strings_dont_unbalance(self):
        # The opening "{" inside the string must not increase depth.
        text = '{"snippet": "if (x) { return y; }", "type": "code"}'
        extracted = _extract_first_json_object(text)
        assert extracted == text
        assert json.loads(extracted)["type"] == "code"

    def test_escaped_quote_in_string(self):
        text = '{"q": "she said \\"hi\\" then left", "ok": true}'
        extracted = _extract_first_json_object(text)
        assert extracted == text
        assert json.loads(extracted)["ok"] is True

    def test_returns_none_when_no_brace(self):
        assert _extract_first_json_object("no json here, sorry") is None

    def test_returns_none_when_unbalanced(self):
        # Open brace but never closes.
        assert _extract_first_json_object('{"a": "no close') is None


class TestParseRecommendationNestedJson:
    """Regression test for the nested-JSON parsing fix."""

    def _failure(self) -> FailureRecord:
        return FailureRecord(
            test_name="t",
            test_suite="s",
            model_name="m",
            question="q",
            expected_answer="e",
            actual_answer="a",
            grading_reason="g",
            score=0.0,
        )

    def test_nested_suggested_params_survives_markdown_wrap(self):
        client = MagicMock()
        client.generate.return_value = (
            "Sure, here is the analysis:\n```json\n"
            '{"recommendation_type": "params", '
            '"suggested_params": {"temperature": 0.0, "seed": 42}, '
            '"confidence": 0.8, "details": "lower temperature"}\n```'
        )
        agent = AnalyzerAgent(client)
        recs = agent.analyze_failures([self._failure()])
        assert len(recs) == 1
        rec = recs[0]
        assert rec.recommendation_type == "params"
        assert rec.suggested_params == {"temperature": 0.0, "seed": 42}
        assert rec.confidence == 0.8
