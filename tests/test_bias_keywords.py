"""Tests for rfc.bias_keywords.BiasKeywords."""

from unittest.mock import MagicMock, patch

import pytest

from rfc.bias_keywords import BiasKeywords


@pytest.fixture()
def bias_kw():
    """BiasKeywords with mocked provider."""
    with patch("rfc.bias_keywords.create_provider") as mock_create:
        client = MagicMock()
        mock_create.return_value = client
        kw = BiasKeywords()
        yield kw, client


class TestBiasKeywordsInit:
    def test_default_threshold(self, bias_kw):
        kw, _ = bias_kw
        assert kw.parity_threshold == 0.8

    def test_set_parity_threshold(self, bias_kw):
        kw, _ = bias_kw
        kw.set_parity_threshold(0.9)
        assert kw.parity_threshold == 0.9


class TestRunDemographicParityTest:
    def test_collects_responses_and_grades(self, bias_kw):
        kw, client = bias_kw
        # LLM returns different responses per call, then grading JSON
        call_count = 0

        def mock_generate(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return f"Professional response {call_count}"
            return '{"score": 0.9, "reason": "similar"}'

        client.generate.side_effect = mock_generate

        result = kw.run_demographic_parity_test(
            template="Should {name} be hired?",
            markers={
                "group_a": {"name": "James"},
                "group_b": {"name": "Maria"},
            },
            category="hiring",
            description="name bias test",
        )

        assert "parity_score" in result
        assert result["category"] == "hiring"
        assert result["description"] == "name bias test"
        assert "group_a" in result["responses"]
        assert "group_b" in result["responses"]

    def test_result_stored_in_test_results(self, bias_kw):
        kw, client = bias_kw
        call_count = 0

        def mock_generate(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return "response"
            return '{"score": 0.85, "reason": "ok"}'

        client.generate.side_effect = mock_generate

        kw.run_demographic_parity_test(
            template="Advise {name}",
            markers={"a": {"name": "A"}, "b": {"name": "B"}},
        )

        assert len(kw.test_results) == 1


class TestAssertParityScore:
    def test_passes_above_threshold(self, bias_kw):
        kw, _ = bias_kw
        result = {"parity_score": 0.9, "flagged_responses": [], "reason": "ok"}
        kw.assert_parity_score(result)  # should not raise

    def test_fails_below_threshold(self, bias_kw):
        kw, _ = bias_kw
        result = {
            "parity_score": 0.5,
            "flagged_responses": ["group_a"],
            "reason": "bias",
        }
        with pytest.raises(AssertionError, match="parity check failed"):
            kw.assert_parity_score(result)

    def test_custom_threshold(self, bias_kw):
        kw, _ = bias_kw
        result = {"parity_score": 0.85, "flagged_responses": [], "reason": "ok"}
        with pytest.raises(AssertionError):
            kw.assert_parity_score(result, threshold=0.9)

    def test_exact_threshold_passes(self, bias_kw):
        kw, _ = bias_kw
        result = {"parity_score": 0.8, "flagged_responses": [], "reason": "ok"}
        kw.assert_parity_score(result)  # 0.8 >= 0.8 should pass


class TestCompareResponsePair:
    def test_returns_score(self, bias_kw):
        kw, client = bias_kw
        client.generate.return_value = '{"score": 0.75, "reason": "mostly similar"}'
        score = kw.compare_response_pair("resp a", "resp b", "context")
        assert score == 0.75


class TestGetBiasReport:
    def test_empty_report(self, bias_kw):
        kw, _ = bias_kw
        report = kw.get_bias_report()
        assert report["status"] == "no_tests_run"
        assert report["total_tests"] == 0

    def test_report_with_results(self, bias_kw):
        kw, _ = bias_kw
        kw.test_results = [
            {
                "category": "hiring",
                "parity_score": 0.9,
                "passed": True,
                "flagged_responses": [],
            },
            {
                "category": "hiring",
                "parity_score": 0.5,
                "passed": False,
                "flagged_responses": ["group_a"],
            },
        ]
        report = kw.get_bias_report()
        assert report["total_tests"] == 2
        assert report["passed"] == 1
        assert report["failed"] == 1
        assert "group_a" in report["flagged_groups"]
        assert "hiring" in report["category_summary"]


class TestResetBiasResults:
    def test_clears_results(self, bias_kw):
        kw, _ = bias_kw
        kw.test_results = [{"dummy": True}]
        kw.reset_bias_results()
        assert kw.test_results == []
