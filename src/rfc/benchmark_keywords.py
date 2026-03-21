"""Robot Framework keywords for token output benchmarking.

Provides keywords to measure completion ratio and estimate response
token counts, emitting structured RFC_DATA for database capture.
"""

from robot.api.deco import keyword

from .rfc_data import emit_rfc_data
from .thinking import estimate_token_count


class BenchmarkKeywords:
    """Keywords for measuring LLM token output performance."""

    @keyword("Measure Completion Ratio")
    def measure_completion_ratio(self, requested_tokens: int, eval_count: int) -> float:
        """Compare actual eval_count to requested max_tokens.

        Args:
            requested_tokens: Number of tokens requested via max_tokens.
            eval_count: Actual tokens generated (from Ollama metrics).

        Returns:
            Ratio of eval_count / requested_tokens.
        """
        requested = int(requested_tokens)
        actual = int(eval_count)
        ratio = actual / requested if requested > 0 else 0.0
        emit_rfc_data("completion_ratio", f"{ratio:.4f}")
        emit_rfc_data("requested_tokens", str(requested))
        return ratio

    @keyword("Estimate Response Tokens")
    def estimate_response_tokens(self, response: str) -> int:
        """Emit word-based token estimate for the response.

        Args:
            response: The LLM response text.

        Returns:
            Estimated token count based on whitespace splitting.
        """
        count = estimate_token_count(response)
        emit_rfc_data("estimated_response_tokens", str(count))
        return count
