"""Tests for rfc.summarization_keywords.SummarizationKeywords."""

from unittest.mock import patch

from rfc.summarization_keywords import SummarizationKeywords


class TestCheckKeywordCoverage:
    def setup_method(self) -> None:
        self.sk = SummarizationKeywords()

    def test_all_groups_present_returns_full_coverage(self) -> None:
        text = "The Apollo 11 mission landed on the Moon in 1969."
        groups = ["Apollo 11", "Moon", "1969"]
        score, missing = self.sk.check_keyword_coverage(text, groups)
        assert score == 1.0
        assert missing == []

    def test_missing_groups_returns_partial_coverage(self) -> None:
        text = "The mission landed on the Moon."
        groups = ["Apollo 11", "Moon", "1969"]
        score, missing = self.sk.check_keyword_coverage(text, groups)
        assert 0.3 < score < 0.4
        assert "Apollo 11" in missing
        assert "1969" in missing
        assert "Moon" not in missing

    def test_synonym_alternatives_match_either(self) -> None:
        text = "The chief executive announced the news."
        groups = ["CEO|chief executive", "announced|stated"]
        score, missing = self.sk.check_keyword_coverage(text, groups)
        assert score == 1.0
        assert missing == []

    def test_case_insensitive_matching(self) -> None:
        text = "apollo 11 reached the moon."
        groups = ["Apollo 11", "Moon"]
        score, missing = self.sk.check_keyword_coverage(text, groups)
        assert score == 1.0

    def test_word_boundary_prevents_substring_match(self) -> None:
        text = "The catalog listed many items."
        groups = ["cat"]
        score, missing = self.sk.check_keyword_coverage(text, groups)
        assert score == 0.0
        assert missing == ["cat"]

    def test_empty_groups_returns_one(self) -> None:
        score, missing = self.sk.check_keyword_coverage("any text", [])
        assert score == 1.0
        assert missing == []

    def test_empty_text_returns_zero_with_groups(self) -> None:
        score, missing = self.sk.check_keyword_coverage("", ["Apollo 11"])
        assert score == 0.0
        assert missing == ["Apollo 11"]

    def test_alternative_with_whitespace_around_pipe(self) -> None:
        """Robot YAML may produce groups with surrounding whitespace."""
        text = "The CEO spoke."
        groups = ["CEO | chief executive"]
        score, missing = self.sk.check_keyword_coverage(text, groups)
        assert score == 1.0


class TestCheckForbiddenFacts:
    def setup_method(self) -> None:
        self.sk = SummarizationKeywords()

    def test_no_forbidden_returns_empty(self) -> None:
        text = "The mission was successful."
        violations = self.sk.check_forbidden_facts(text, ["died", "explosion"])
        assert violations == []

    def test_forbidden_present_returns_match(self) -> None:
        text = "The crew died during reentry."
        violations = self.sk.check_forbidden_facts(text, ["died", "explosion"])
        assert "died" in violations

    def test_case_insensitive_forbidden(self) -> None:
        text = "There was an EXPLOSION on board."
        violations = self.sk.check_forbidden_facts(text, ["explosion"])
        assert violations == ["explosion"]

    def test_word_boundary_for_forbidden(self) -> None:
        """Forbidden word 'die' should not match inside 'died'."""
        text = "The crew died safely."
        violations = self.sk.check_forbidden_facts(text, ["die"])
        assert violations == []


class TestCheckLengthCompliance:
    def setup_method(self) -> None:
        self.sk = SummarizationKeywords()

    def test_within_bounds_returns_true(self) -> None:
        text = "one two three four five six seven eight nine ten"
        result = self.sk.check_length_compliance(text, min_words=5, max_words=20)
        assert result["within_bounds"] is True
        assert result["word_count"] == 10

    def test_too_short_returns_false(self) -> None:
        text = "one two"
        result = self.sk.check_length_compliance(text, min_words=5, max_words=20)
        assert result["within_bounds"] is False
        assert result["word_count"] == 2

    def test_too_long_returns_false(self) -> None:
        text = " ".join(["word"] * 100)
        result = self.sk.check_length_compliance(text, min_words=5, max_words=20)
        assert result["within_bounds"] is False
        assert result["word_count"] == 100

    def test_zero_min_only_max(self) -> None:
        text = "one two three"
        result = self.sk.check_length_compliance(text, min_words=0, max_words=10)
        assert result["within_bounds"] is True


class TestScoreSummary:
    def setup_method(self) -> None:
        self.sk = SummarizationKeywords()

    @patch("rfc.summarization_keywords.emit_rfc_data")
    def test_perfect_summary_scores_one(self, mock_emit: patch) -> None:
        summary = "Apollo 11 landed on the Moon in 1969 with Armstrong as commander."
        result = self.sk.score_summary(
            summary=summary,
            required_keywords=["Apollo 11", "Moon", "1969", "Armstrong"],
            forbidden_facts=["Mars", "2001"],
            min_words=5,
            max_words=30,
        )
        assert result["pass"] is True
        assert result["total_score"] == 1.0
        assert result["coverage_score"] == 1.0
        assert result["forbidden_found"] == []
        assert result["length_ok"] is True

    @patch("rfc.summarization_keywords.emit_rfc_data")
    def test_missing_keywords_lowers_coverage(self, mock_emit: patch) -> None:
        summary = "The mission landed on the Moon."
        result = self.sk.score_summary(
            summary=summary,
            required_keywords=["Apollo 11", "Moon", "1969", "Armstrong"],
            forbidden_facts=[],
            min_words=2,
            max_words=30,
        )
        assert result["coverage_score"] == 0.25
        assert result["total_score"] < 1.0

    @patch("rfc.summarization_keywords.emit_rfc_data")
    def test_forbidden_fact_fails(self, mock_emit: patch) -> None:
        summary = "Apollo 11 landed on Mars in 1969."
        result = self.sk.score_summary(
            summary=summary,
            required_keywords=["Apollo 11", "1969"],
            forbidden_facts=["Mars"],
            min_words=2,
            max_words=30,
        )
        assert result["pass"] is False
        assert "Mars" in result["forbidden_found"]
        assert result["total_score"] < 1.0

    @patch("rfc.summarization_keywords.emit_rfc_data")
    def test_length_violation_fails(self, mock_emit: patch) -> None:
        summary = "tiny"
        result = self.sk.score_summary(
            summary=summary,
            required_keywords=[],
            forbidden_facts=[],
            min_words=10,
            max_words=50,
        )
        assert result["pass"] is False
        assert result["length_ok"] is False

    @patch("rfc.summarization_keywords.emit_rfc_data")
    def test_emits_rfc_data(self, mock_emit: patch) -> None:
        summary = "Apollo 11 landed on the Moon."
        self.sk.score_summary(
            summary=summary,
            required_keywords=["Apollo 11", "Moon"],
            forbidden_facts=[],
            min_words=2,
            max_words=30,
        )
        emitted_keys = {call.args[0] for call in mock_emit.call_args_list}
        assert "score" in emitted_keys
        assert "coverage_score" in emitted_keys
        assert "word_count" in emitted_keys

    @patch("rfc.summarization_keywords.emit_rfc_data")
    def test_empty_summary_scores_zero(self, mock_emit: patch) -> None:
        result = self.sk.score_summary(
            summary="",
            required_keywords=["Apollo 11"],
            forbidden_facts=[],
            min_words=5,
            max_words=30,
        )
        assert result["pass"] is False
        assert result["coverage_score"] == 0.0
        assert result["length_ok"] is False

    @patch("rfc.summarization_keywords.emit_rfc_data")
    def test_total_score_weighting(self, mock_emit: patch) -> None:
        """Coverage drives most of total; forbidden + length act as gates."""
        # Half coverage, no forbidden, length OK
        summary = "Apollo 11 happened."  # 3 words
        result = self.sk.score_summary(
            summary=summary,
            required_keywords=["Apollo 11", "Moon"],
            forbidden_facts=[],
            min_words=2,
            max_words=30,
        )
        # Half coverage with length-ok and no forbidden → total > 0, < 1
        assert 0.3 < result["total_score"] < 0.7


class TestAskAndScoreSummary:
    @patch("rfc.summarization_keywords.create_provider")
    @patch("rfc.summarization_keywords.emit_rfc_data")
    def test_uses_llm_response_for_scoring(
        self, mock_emit: patch, mock_create: patch
    ) -> None:
        fake_provider = mock_create.return_value
        fake_provider.generate.return_value = "Apollo 11 landed on the Moon in 1969."
        sk = SummarizationKeywords()
        result = sk.ask_and_score_summary(
            source_text="In July 1969, Apollo 11 carried Armstrong to the Moon.",
            instruction="Summarize in one sentence.",
            required_keywords=["Apollo 11", "Moon", "1969"],
            forbidden_facts=["Mars"],
            min_words=3,
            max_words=30,
        )
        assert result["pass"] is True
        assert result["coverage_score"] == 1.0
        fake_provider.generate.assert_called_once()
        # Prompt must include both the instruction and the source text.
        call_args = fake_provider.generate.call_args
        prompt = call_args.args[0] if call_args.args else call_args.kwargs["prompt"]
        assert "Summarize in one sentence." in prompt
        assert "Apollo 11 carried Armstrong" in prompt

    @patch("rfc.summarization_keywords.create_provider")
    @patch("rfc.summarization_keywords.emit_rfc_data")
    def test_strips_thinking_blocks(self, mock_emit: patch, mock_create: patch) -> None:
        fake_provider = mock_create.return_value
        fake_provider.generate.return_value = (
            "<think>let me think...</think>Apollo 11 landed on the Moon in 1969."
        )
        sk = SummarizationKeywords()
        result = sk.ask_and_score_summary(
            source_text="Apollo 11 landed on the Moon in 1969.",
            instruction="Summarize.",
            required_keywords=["Apollo 11", "Moon", "1969"],
            forbidden_facts=[],
            min_words=3,
            max_words=30,
        )
        # The think block must not be considered part of the summary content.
        # Coverage stays at 1.0 because the visible text still has the keywords.
        assert result["coverage_score"] == 1.0
        # Word count must reflect the cleaned summary, not the thinking block.
        assert result["word_count"] < 15
