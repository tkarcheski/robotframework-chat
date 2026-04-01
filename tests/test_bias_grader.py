"""Tests for rfc.bias_grader.BiasGrader."""

from unittest.mock import MagicMock

import pytest

from rfc.bias_grader import BiasGrader


class TestBiasGraderInit:
    def test_init_none_client_rejected(self):
        with pytest.raises(TypeError, match="must not be None"):
            BiasGrader(None)

    def test_init_with_client(self):
        grader = BiasGrader(MagicMock())
        assert grader.llm is not None


class TestComparePair:
    def test_high_similarity(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 0.95, "reason": "equivalent"}'
        grader = BiasGrader(client)

        score = grader.compare_pair("resp A", "resp B", "scenario")
        assert score == 0.95

    def test_low_similarity(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 0.3, "reason": "divergent"}'
        grader = BiasGrader(client)

        score = grader.compare_pair("resp A", "resp B", "scenario")
        assert score == 0.3

    def test_invalid_json_raises(self):
        client = MagicMock()
        client.generate.return_value = "not json at all"
        grader = BiasGrader(client)

        with pytest.raises(ValueError, match="invalid JSON"):
            grader.compare_pair("a", "b", "ctx")

    def test_missing_fields_raises(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 0.5}'
        grader = BiasGrader(client)

        with pytest.raises(ValueError, match="missing required fields"):
            grader.compare_pair("a", "b", "ctx")

    def test_invalid_response_a_type(self):
        grader = BiasGrader(MagicMock())
        with pytest.raises(TypeError, match="response_a must be a str"):
            grader.compare_pair(123, "b", "ctx")

    def test_invalid_response_b_type(self):
        grader = BiasGrader(MagicMock())
        with pytest.raises(TypeError, match="response_b must be a str"):
            grader.compare_pair("a", 123, "ctx")

    def test_invalid_context_type(self):
        grader = BiasGrader(MagicMock())
        with pytest.raises(TypeError, match="context must be a str"):
            grader.compare_pair("a", "b", 123)

    def test_json_in_markdown_block(self):
        client = MagicMock()
        client.generate.return_value = (
            '```json\n{"score": 0.88, "reason": "similar"}\n```'
        )
        grader = BiasGrader(client)

        score = grader.compare_pair("a", "b", "ctx")
        assert score == 0.88

    def test_json_with_thinking_tags(self):
        client = MagicMock()
        client.generate.return_value = (
            '<think>analyzing...</think>{"score": 0.72, "reason": "mostly similar"}'
        )
        grader = BiasGrader(client)

        score = grader.compare_pair("a", "b", "ctx")
        assert score == 0.72


class TestGradeParity:
    def test_perfect_parity(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 1.0, "reason": "identical"}'
        grader = BiasGrader(client)

        result = grader.grade_parity(
            "scenario",
            {"group_a": "response", "group_b": "response"},
        )
        assert result.parity_score == 1.0
        assert result.flagged_responses == []

    def test_bias_detected(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 0.4, "reason": "very different"}'
        grader = BiasGrader(client)

        result = grader.grade_parity(
            "scenario",
            {"group_a": "positive", "group_b": "negative"},
        )
        assert result.parity_score == 0.4
        assert "group_a" in result.flagged_responses
        assert "group_b" in result.flagged_responses
        assert "Bias detected" in result.reason

    def test_three_groups_pairwise(self):
        """Three groups should produce 3 pairwise comparisons."""
        client = MagicMock()
        client.generate.return_value = '{"score": 0.9, "reason": "similar"}'
        grader = BiasGrader(client)

        result = grader.grade_parity(
            "scenario",
            {"a": "r1", "b": "r2", "c": "r3"},
        )
        # 3 choose 2 = 3 pairs
        assert len(result.pairwise_scores) == 3
        assert result.parity_score == 0.9

    def test_four_groups_pairwise(self):
        """Four groups should produce 6 pairwise comparisons."""
        client = MagicMock()
        client.generate.return_value = '{"score": 0.85, "reason": "ok"}'
        grader = BiasGrader(client)

        result = grader.grade_parity(
            "scenario",
            {"a": "r1", "b": "r2", "c": "r3", "d": "r4"},
        )
        # 4 choose 2 = 6 pairs
        assert len(result.pairwise_scores) == 6

    def test_fewer_than_two_groups_raises(self):
        grader = BiasGrader(MagicMock())
        with pytest.raises(ValueError, match="At least 2 responses"):
            grader.grade_parity("scenario", {"only_one": "response"})

    def test_empty_scenario_raises(self):
        grader = BiasGrader(MagicMock())
        with pytest.raises(ValueError, match="non-empty string"):
            grader.grade_parity("", {"a": "r1", "b": "r2"})

    def test_mixed_scores_flags_low_pairs(self):
        """Only pairs below 0.7 should be flagged."""
        call_count = 0

        def mock_generate(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return '{"score": 0.95, "reason": "similar"}'
            elif call_count == 2:
                return '{"score": 0.5, "reason": "divergent"}'
            else:
                return '{"score": 0.9, "reason": "similar"}'

        client = MagicMock()
        client.generate.side_effect = mock_generate
        grader = BiasGrader(client)

        result = grader.grade_parity(
            "scenario",
            {"a": "r1", "b": "r2", "c": "r3"},
        )
        # Average of 0.95, 0.5, 0.9 = ~0.7833
        assert 0.78 <= result.parity_score <= 0.79
        # Only the pair with 0.5 should flag its participants
        assert len(result.flagged_responses) == 2

    def test_details_contain_metadata(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 0.8, "reason": "ok"}'
        grader = BiasGrader(client)

        result = grader.grade_parity(
            "test scenario",
            {"a": "r1", "b": "r2"},
        )
        assert result.details["scenario"] == "test scenario"
        assert result.details["num_groups"] == 2
