"""Tests for rfc.benchmark_keywords.BenchmarkKeywords."""

from unittest.mock import patch

from rfc.benchmark_keywords import BenchmarkKeywords


class TestMeasureCompletionRatio:
    def setup_method(self) -> None:
        self.bk = BenchmarkKeywords()

    @patch("rfc.benchmark_keywords.emit_rfc_data")
    def test_perfect_completion(self, mock_emit: patch) -> None:
        """Model generated exactly as many tokens as requested."""
        ratio = self.bk.measure_completion_ratio(1024, 1024)
        assert ratio == 1.0
        mock_emit.assert_any_call("completion_ratio", "1.0000")
        mock_emit.assert_any_call("requested_tokens", "1024")

    @patch("rfc.benchmark_keywords.emit_rfc_data")
    def test_partial_completion(self, mock_emit: patch) -> None:
        """Model generated fewer tokens than requested."""
        ratio = self.bk.measure_completion_ratio(1000, 500)
        assert ratio == 0.5
        mock_emit.assert_any_call("completion_ratio", "0.5000")

    @patch("rfc.benchmark_keywords.emit_rfc_data")
    def test_over_completion(self, mock_emit: patch) -> None:
        """Model generated more tokens than requested (some models do this)."""
        ratio = self.bk.measure_completion_ratio(100, 150)
        assert ratio == 1.5
        mock_emit.assert_any_call("completion_ratio", "1.5000")

    @patch("rfc.benchmark_keywords.emit_rfc_data")
    def test_zero_eval_count(self, mock_emit: patch) -> None:
        """Model generated zero tokens."""
        ratio = self.bk.measure_completion_ratio(512, 0)
        assert ratio == 0.0

    @patch("rfc.benchmark_keywords.emit_rfc_data")
    def test_string_arguments_coerced(self, mock_emit: patch) -> None:
        """Robot Framework passes strings — ensure int coercion works."""
        ratio = self.bk.measure_completion_ratio("1024", "512")
        assert ratio == 0.5


class TestEstimateResponseTokens:
    def setup_method(self) -> None:
        self.bk = BenchmarkKeywords()

    @patch("rfc.benchmark_keywords.emit_rfc_data")
    def test_normal_text(self, mock_emit: patch) -> None:
        """Word count approximation for normal English text."""
        text = "The quick brown fox jumps over the lazy dog"
        count = self.bk.estimate_response_tokens(text)
        assert count == 9
        mock_emit.assert_any_call("estimated_response_tokens", "9")

    @patch("rfc.benchmark_keywords.emit_rfc_data")
    def test_empty_string(self, mock_emit: patch) -> None:
        count = self.bk.estimate_response_tokens("")
        assert count == 0

    @patch("rfc.benchmark_keywords.emit_rfc_data")
    def test_code_block(self, mock_emit: patch) -> None:
        """Code has different token density than prose."""
        code = "def foo(x: int) -> int:\n    return x * 2\n"
        count = self.bk.estimate_response_tokens(code)
        assert count > 0
