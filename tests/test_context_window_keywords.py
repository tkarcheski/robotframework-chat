"""Tests for context_window_keywords — filled-context retrieval stress testing."""

import pytest

from rfc.context_window_keywords import ContextWindowKeywords


class TestBuildFilledPrompt:
    """Test prompt assembly with filler content."""

    def setup_method(self):
        self.kw = ContextWindowKeywords()

    def test_respects_context_budget(self):
        """Built prompt should fit within fill_pct of context window."""
        needle_fact = "Database key XYZ-789 requires rotation every 90 days."
        question = "How often does XYZ-789 need rotation?"
        context_window = 1000
        fill_pct = 50
        position = "end"

        prompt = self.kw.build_filled_prompt(
            needle_fact, question, fill_pct, context_window, position
        )

        # Token estimate via word split
        tokens = len(prompt.split())
        budget = int(context_window * fill_pct / 100)
        # Allow +/- 10% margin for estimation error and safety reserves
        assert tokens <= budget + 100, (
            f"Prompt {tokens} tokens exceeds budget {budget}; "
            f"diff={tokens - budget}"
        )

    def test_needle_position_at_start(self):
        """Needle at 'start' should appear before most filler."""
        needle_fact = "NEEDLE_MARKER_START"
        question = "Where is the needle?"
        context_window = 2000
        fill_pct = 80
        position = "start"

        prompt = self.kw.build_filled_prompt(
            needle_fact, question, fill_pct, context_window, position
        )

        # Needle should be in first third
        needle_idx = prompt.find(needle_fact)
        total_len = len(prompt)
        assert needle_idx < total_len / 3, (
            f"Needle at position {needle_idx} "
            f"should be in first third (< {total_len / 3})"
        )

    def test_needle_position_at_middle(self):
        """Needle at 'middle' should appear near center."""
        needle_fact = "NEEDLE_MARKER_MIDDLE"
        question = "Where is the needle?"
        context_window = 2000
        fill_pct = 80
        position = "middle"

        prompt = self.kw.build_filled_prompt(
            needle_fact, question, fill_pct, context_window, position
        )

        needle_idx = prompt.find(needle_fact)
        total_len = len(prompt)
        # Middle third: between 1/3 and 2/3
        assert total_len / 3 < needle_idx < (2 * total_len / 3), (
            f"Needle at position {needle_idx} "
            f"should be in middle third"
        )

    def test_needle_position_at_end(self):
        """Needle at 'end' should appear after most filler."""
        needle_fact = "NEEDLE_MARKER_END"
        question = "Where is the needle?"
        context_window = 2000
        fill_pct = 80
        position = "end"

        prompt = self.kw.build_filled_prompt(
            needle_fact, question, fill_pct, context_window, position
        )

        needle_idx = prompt.find(needle_fact)
        total_len = len(prompt)
        assert needle_idx > (2 * total_len / 3), (
            f"Needle at position {needle_idx} "
            f"should be in last third (> {2 * total_len / 3})"
        )

    def test_includes_question(self):
        """Prompt should include the retrieval question."""
        needle_fact = "Key detail XYZ"
        question = "What is the key detail?"
        context_window = 1000
        fill_pct = 50
        position = "middle"

        prompt = self.kw.build_filled_prompt(
            needle_fact, question, fill_pct, context_window, position
        )

        assert question in prompt, "Question should be included in prompt"

    def test_reserves_response_headroom(self):
        """Should not fill such that prompt + max_tokens exceeds context window."""
        needle_fact = "Test fact"
        question = "Test question"
        context_window = 2000
        fill_pct = 95
        position = "middle"
        max_tokens = 256

        prompt = self.kw.build_filled_prompt(
            needle_fact, question, fill_pct, context_window, position,
            max_tokens=max_tokens
        )

        tokens = len(prompt.split())
        # Prompt + response tokens + safety margin should not exceed context
        total = tokens + max_tokens + 50  # 50-token safety buffer
        assert total <= context_window, (
            f"Prompt {tokens} + max_tokens {max_tokens} + safety 50 = {total} "
            f"exceeds context {context_window}"
        )

    def test_small_fill_percentage(self):
        """Should handle small fill percentages without error."""
        needle_fact = "Fact"
        question = "Question?"
        context_window = 2000
        fill_pct = 10
        position = "middle"

        prompt = self.kw.build_filled_prompt(
            needle_fact, question, fill_pct, context_window, position
        )

        assert needle_fact in prompt
        assert question in prompt
        assert len(prompt.split()) > 0


class TestCheckNeedleRecalled:
    """Test needle detection in model responses."""

    def setup_method(self):
        self.kw = ContextWindowKeywords()

    def test_exact_substring_match(self):
        """Should detect exact substring match."""
        response = "The key detail is ABC-123-XYZ per the documentation."
        expected = "ABC-123-XYZ"

        result = self.kw.check_needle_recalled(response, expected)
        assert result is True

    def test_case_insensitive_match(self):
        """Should match regardless of case."""
        response = "The key is abc-123-xyz according to specs."
        expected = "ABC-123-XYZ"

        result = self.kw.check_needle_recalled(response, expected)
        assert result is True

    def test_whitespace_normalized_match(self):
        """Should match with normalized whitespace."""
        response = "The value is  ABC - 123 - XYZ  per docs."
        expected = "ABC-123-XYZ"

        result = self.kw.check_needle_recalled(response, expected)
        # Whitespace-normalized comparison should work
        assert result is True

    def test_missing_needle(self):
        """Should return False when needle not found."""
        response = "The interval is 90 days per standard procedure."
        expected = "ABC-123-XYZ"

        result = self.kw.check_needle_recalled(response, expected)
        assert result is False

    def test_partial_match_fails(self):
        """Should not match partial substrings."""
        response = "The code is ABC-123 but not full."
        expected = "ABC-123-XYZ"

        result = self.kw.check_needle_recalled(response, expected)
        assert result is False

    def test_empty_response(self):
        """Should handle empty responses."""
        response = ""
        expected = "NEEDLE"

        result = self.kw.check_needle_recalled(response, expected)
        assert result is False
