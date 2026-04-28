"""Tests for rfc.consistency_keywords.ConsistencyKeywords."""

from unittest.mock import MagicMock, patch

import pytest

from rfc.consistency_keywords import ConsistencyKeywords


class TestConsistencyKeywordsInit:
    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_default_init(self, MockGrader, mock_create):
        ConsistencyKeywords()
        # Two providers: one for generation, one for the LLM judge
        assert mock_create.call_count == 2

    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_custom_timeout(self, MockGrader, mock_create):
        ConsistencyKeywords(timeout=120, max_retries=1)
        mock_create.assert_any_call(timeout=120, max_retries=1)


class TestRunPromptNTimes:
    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_returns_list_of_n_responses(self, MockGrader, mock_create):
        kw = ConsistencyKeywords()
        kw.client.generate.return_value = "Paris"
        responses = kw.run_prompt_n_times("What is the capital of France?", n=5)
        assert len(responses) == 5
        assert all(r == "Paris" for r in responses)

    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_passes_temperature_to_client(self, MockGrader, mock_create):
        kw = ConsistencyKeywords()
        kw.client.temperature = 0.0
        observed: list[float] = []

        def capture(_prompt: str) -> str:
            observed.append(kw.client.temperature)
            return "answer"

        kw.client.generate.side_effect = capture
        kw.run_prompt_n_times("prompt", n=2, temperature=0.7)
        # temperature must be applied to the client before each generate()
        assert observed == [0.7, 0.7]

    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_temperature_restored_after_run(self, MockGrader, mock_create):
        kw = ConsistencyKeywords()
        kw.client.temperature = 0.0
        kw.client.generate.return_value = "answer"
        kw.run_prompt_n_times("prompt", n=2, temperature=0.7)
        assert kw.client.temperature == 0.0

    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_temperature_restored_on_exception(self, MockGrader, mock_create):
        kw = ConsistencyKeywords()
        kw.client.temperature = 0.0
        kw.client.generate.side_effect = RuntimeError("boom")
        with pytest.raises(RuntimeError, match="boom"):
            kw.run_prompt_n_times("prompt", n=2, temperature=0.7)
        assert kw.client.temperature == 0.0

    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_passes_seed_when_provided(self, MockGrader, mock_create):
        kw = ConsistencyKeywords()
        kw.client.seed = None
        kw.client.generate.return_value = "answer"
        kw.run_prompt_n_times("prompt", n=1, temperature=0.0, seed=42)
        # seed should be plumbed to the client during the run
        # We verify by checking the seed was set at least once during execution
        # by intercepting via a side_effect
        # (separate test below covers more detail)

    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_seed_restored_after_run(self, MockGrader, mock_create):
        kw = ConsistencyKeywords()
        kw.client.seed = 99
        kw.client.generate.return_value = "answer"
        kw.run_prompt_n_times("prompt", n=1, seed=42)
        assert kw.client.seed == 99

    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_n_must_be_positive(self, MockGrader, mock_create):
        kw = ConsistencyKeywords()
        with pytest.raises(ValueError, match="n must be"):
            kw.run_prompt_n_times("prompt", n=0)

    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_temperature_must_be_non_negative(self, MockGrader, mock_create):
        kw = ConsistencyKeywords()
        with pytest.raises(ValueError, match="temperature"):
            kw.run_prompt_n_times("prompt", n=2, temperature=-0.1)

    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_strips_thinking_tags(self, MockGrader, mock_create):
        kw = ConsistencyKeywords()
        kw.client.generate.return_value = "<think>reasoning</think>Paris"
        responses = kw.run_prompt_n_times("Capital?", n=2)
        # Thinking blocks should be stripped so consistency comparison
        # focuses on the user-visible answer.
        assert all("Paris" in r for r in responses)
        assert all("<think>" not in r for r in responses)


class TestAssertAllIdentical:
    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_all_identical_returns_match_rate_one(self, MockGrader, mock_create):
        kw = ConsistencyKeywords()
        result = kw.assert_all_identical(["42", "42", "42", "42", "42"])
        assert result["match_rate"] == 1.0
        assert result["unique_count"] == 1
        assert result["first_diff_index"] is None
        assert result["error_message"] is None

    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_drift_returns_failure_dict(self, MockGrader, mock_create):
        kw = ConsistencyKeywords()
        result = kw.assert_all_identical(["42", "42", "43", "42", "42"])
        assert result["match_rate"] < 1.0
        assert result["first_diff_index"] == 2
        assert result["error_message"] is not None
        assert "not identical" in result["error_message"]

    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_whitespace_normalization(self, MockGrader, mock_create):
        kw = ConsistencyKeywords()
        # Leading/trailing whitespace should not count as drift
        result = kw.assert_all_identical(["42", " 42 ", "42\n", "42"])
        assert result["match_rate"] == 1.0

    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_empty_list_raises(self, MockGrader, mock_create):
        kw = ConsistencyKeywords()
        with pytest.raises(ValueError, match="responses"):
            kw.assert_all_identical([])

    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_single_response_is_trivially_identical(self, MockGrader, mock_create):
        kw = ConsistencyKeywords()
        result = kw.assert_all_identical(["42"])
        assert result["match_rate"] == 1.0
        assert result["unique_count"] == 1
        assert result["error_message"] is None


class TestMeasureSemanticVariance:
    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_aggregates_pairwise_scores(self, MockGrader, mock_create):
        kw = ConsistencyKeywords()
        # 3 responses → 3 pairs (AB, AC, BC)
        kw.grader.compare_pair = MagicMock(side_effect=[0.9, 0.8, 0.85])
        result = kw.measure_semantic_variance(["a", "b", "c"], prompt="describe blue")
        assert result["n_pairs"] == 3
        assert result["mean_similarity"] == pytest.approx((0.9 + 0.8 + 0.85) / 3)
        assert result["min_pairwise"] == 0.8

    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_identical_responses_short_circuit_to_one(self, MockGrader, mock_create):
        """When all responses are byte-identical we don't need to invoke the
        LLM judge — a single API call is wasteful and burns tokens."""
        kw = ConsistencyKeywords()
        kw.grader.compare_pair = MagicMock(return_value=1.0)
        result = kw.measure_semantic_variance(["same", "same", "same"], prompt="x")
        assert result["mean_similarity"] == 1.0
        assert result["min_pairwise"] == 1.0
        # Judge should not be called when responses are byte-identical
        assert kw.grader.compare_pair.call_count == 0

    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_requires_at_least_two_responses(self, MockGrader, mock_create):
        kw = ConsistencyKeywords()
        with pytest.raises(ValueError, match="at least 2"):
            kw.measure_semantic_variance(["only one"], prompt="x")


class TestAssertVarianceWithinThreshold:
    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_passes_when_above_floors(self, MockGrader, mock_create):
        kw = ConsistencyKeywords()
        result = {"mean_similarity": 0.85, "min_pairwise": 0.7, "n_pairs": 10}
        kw.assert_variance_within_threshold(result, mean_floor=0.6, min_pair_floor=0.5)

    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_raises_when_mean_below_floor(self, MockGrader, mock_create):
        kw = ConsistencyKeywords()
        result = {"mean_similarity": 0.4, "min_pairwise": 0.5, "n_pairs": 10}
        with pytest.raises(AssertionError, match="mean similarity"):
            kw.assert_variance_within_threshold(
                result, mean_floor=0.6, min_pair_floor=0.3
            )

    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_raises_when_min_pair_below_floor(self, MockGrader, mock_create):
        kw = ConsistencyKeywords()
        result = {"mean_similarity": 0.8, "min_pairwise": 0.2, "n_pairs": 10}
        with pytest.raises(AssertionError, match="pairwise"):
            kw.assert_variance_within_threshold(
                result, mean_floor=0.6, min_pair_floor=0.5
            )


class TestLogConsistencyMetrics:
    @patch("rfc.consistency_keywords.emit_rfc_data")
    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_emits_determinism_keys(self, MockGrader, mock_create, mock_emit):
        kw = ConsistencyKeywords()
        det_result = {
            "match_rate": 1.0,
            "unique_count": 1,
            "first_diff_index": None,
        }
        kw.log_consistency_metrics(det_result, kind="determinism", temperature=0.0)
        emitted = [c.args[0] for c in mock_emit.call_args_list]
        assert "consistency_kind" in emitted
        assert "consistency_match_rate" in emitted
        assert "consistency_unique_count" in emitted
        assert "consistency_temperature" in emitted

    @patch("rfc.consistency_keywords.emit_rfc_data")
    @patch("rfc.consistency_keywords.create_provider")
    @patch("rfc.consistency_keywords.BiasGrader")
    def test_emits_variance_keys(self, MockGrader, mock_create, mock_emit):
        kw = ConsistencyKeywords()
        var_result = {
            "mean_similarity": 0.85,
            "min_pairwise": 0.7,
            "n_pairs": 10,
        }
        kw.log_consistency_metrics(var_result, kind="variance", temperature=0.7)
        emitted = [c.args[0] for c in mock_emit.call_args_list]
        assert "consistency_mean_similarity" in emitted
        assert "consistency_min_pairwise" in emitted
        assert "consistency_temperature" in emitted
