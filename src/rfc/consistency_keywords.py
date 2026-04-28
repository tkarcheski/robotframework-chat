"""Robot Framework keywords for temperature & sampling consistency tests.

Validates Ollama node serving stability and catches quantization-induced
randomness artifacts by replaying a deterministic prompt N times at
``temperature=0`` (must be byte-identical) and at ``temperature=0.7``
(measured for semantic variance via an LLM-as-judge).
"""

from itertools import combinations
from typing import Any, Dict, List, Optional

from robot.api import logger
from robot.api.deco import keyword

from .bias_grader import BiasGrader
from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data
from .thinking import parse_thinking


class ConsistencyKeywords:
    """Robot keywords for measuring response consistency across repeated runs.

    Two complementary checks:
      * ``Run Prompt N Times`` + ``Assert All Identical`` — Tier 1 determinism
        check at ``temperature=0``.
      * ``Run Prompt N Times`` + ``Measure Semantic Variance`` +
        ``Assert Variance Within Threshold`` — Tier 2 stability check at
        ``temperature=0.7`` using an LLM judge.
    """

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(self, timeout: Optional[int] = None, max_retries: int = 2) -> None:
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))
        # Separate provider so the judge model stays constant even if the
        # generation client is reconfigured for variance runs.
        self._grader_client = create_provider(
            timeout=timeout, max_retries=int(max_retries)
        )
        self.grader = BiasGrader(self._grader_client)

    @keyword("Run Prompt N Times")
    def run_prompt_n_times(
        self,
        prompt: str,
        n: int = 5,
        temperature: float = 0.0,
        seed: Optional[int] = None,
    ) -> List[str]:
        """Generate the same prompt ``n`` times at the given temperature.

        Plumbs ``temperature`` and (optionally) ``seed`` through the LLM
        client for the duration of the run, then restores the prior values
        so subsequent keywords are unaffected.

        Args:
            prompt: The prompt to replay.
            n: Number of repetitions (must be >= 1).
            temperature: Sampling temperature (must be >= 0).
            seed: Optional fixed seed for reproducibility.

        Returns:
            List of response strings with thinking blocks stripped.
        """
        n = int(n)
        temperature = float(temperature)
        if n < 1:
            raise ValueError(f"n must be >= 1, got {n}")
        if temperature < 0:
            raise ValueError(f"temperature must be >= 0, got {temperature}")

        prior_temp = self.client.temperature
        prior_seed = self.client.seed
        responses: List[str] = []
        try:
            self.client.temperature = temperature
            if seed is not None:
                self.client.seed = int(seed)
            for i in range(n):
                raw = self.client.generate(prompt)
                text, _ = parse_thinking(raw, strip_unclosed=True)
                responses.append(text)
                logger.info(f"Run {i + 1}/{n} @ temp={temperature}: {text}")
        finally:
            self.client.temperature = prior_temp
            self.client.seed = prior_seed
        return responses

    @keyword("Assert All Identical")
    def assert_all_identical(self, responses: List[str]) -> Dict[str, Any]:
        """Analyze responses for byte-identical match (whitespace-normalized).

        Returns result dict with match status; does not raise. The Robot keyword
        wrapper handles assertion so metrics can be logged even on failure.

        Args:
            responses: List of response strings.

        Returns:
            Dict with ``match_rate`` (1.0 only if all match), ``unique_count``,
            ``first_diff_index`` (None when all match), and ``error_message``
            (None when all match).

        Raises:
            ValueError: If ``responses`` is empty.
        """
        if not responses:
            raise ValueError("responses must be a non-empty list")

        normalized = [r.strip() for r in responses]
        baseline = normalized[0]
        first_diff_index: Optional[int] = None
        error_message: Optional[str] = None
        for i, r in enumerate(normalized[1:], start=1):
            if r != baseline:
                first_diff_index = i
                break

        unique_count = len(set(normalized))
        match_rate = 1.0 if unique_count == 1 else 0.0
        result: Dict[str, Any] = {
            "match_rate": match_rate,
            "unique_count": unique_count,
            "first_diff_index": first_diff_index,
            "error_message": error_message,
        }

        if first_diff_index is not None:
            error_message = (
                f"Responses not identical: run #{first_diff_index} differs from #0.\n"
                f"  Run 0: {baseline!r}\n"
                f"  Run {first_diff_index}: {normalized[first_diff_index]!r}\n"
                f"  Unique outputs across {len(responses)} runs: {unique_count}"
            )
            result["error_message"] = error_message
            logger.error(error_message)
        else:
            logger.info(
                f"All {len(responses)} responses identical (unique_count={unique_count})"
            )
        return result

    @keyword("Measure Semantic Variance")
    def measure_semantic_variance(
        self, responses: List[str], prompt: str
    ) -> Dict[str, Any]:
        """Compute pairwise semantic similarity across responses.

        Uses :class:`BiasGrader` (LLM-as-judge) to score every pair on a
        0.0–1.0 similarity scale, then returns the mean and minimum. When
        all responses are byte-identical, short-circuits to similarity=1.0
        without invoking the judge.

        Args:
            responses: List of response strings (must be >= 2).
            prompt: The original prompt, used as judge context.

        Returns:
            Dict with ``mean_similarity``, ``min_pairwise``, ``n_pairs``,
            ``pairwise_scores``.
        """
        if len(responses) < 2:
            raise ValueError(
                f"Need at least 2 responses to measure variance, got {len(responses)}"
            )

        normalized = [r.strip() for r in responses]
        if len(set(normalized)) == 1:
            # Byte-identical responses — no need to spend tokens on the judge.
            n_pairs = len(list(combinations(range(len(responses)), 2)))
            return {
                "mean_similarity": 1.0,
                "min_pairwise": 1.0,
                "n_pairs": n_pairs,
                "pairwise_scores": {},
            }

        pairwise_scores: Dict[str, float] = {}
        for i, j in combinations(range(len(responses)), 2):
            # Short-circuit judge call for identical pairs — avoid noise and waste
            if normalized[i] == normalized[j]:
                pairwise_scores[f"{i} vs {j}"] = 1.0
            else:
                score = self.grader.compare_pair(responses[i], responses[j], prompt)
                pairwise_scores[f"{i} vs {j}"] = score

        mean = sum(pairwise_scores.values()) / len(pairwise_scores)
        min_pair = min(pairwise_scores.values())
        return {
            "mean_similarity": round(mean, 4),
            "min_pairwise": round(min_pair, 4),
            "n_pairs": len(pairwise_scores),
            "pairwise_scores": pairwise_scores,
        }

    @keyword("Assert Variance Within Threshold")
    def assert_variance_within_threshold(
        self,
        result: Dict[str, Any],
        mean_floor: float = 0.6,
        min_pair_floor: float = 0.5,
    ) -> None:
        """Assert variance metrics meet minimum thresholds.

        Args:
            result: Dict from :meth:`measure_semantic_variance`.
            mean_floor: Minimum acceptable mean pairwise similarity.
            min_pair_floor: Minimum acceptable score for any single pair.

        Raises:
            AssertionError: If either floor is not met.
        """
        mean_floor = float(mean_floor)
        min_pair_floor = float(min_pair_floor)
        mean = float(result.get("mean_similarity", 0.0))
        min_pair = float(result.get("min_pairwise", 0.0))

        if mean < mean_floor:
            raise AssertionError(
                f"mean similarity {mean:.3f} below floor {mean_floor:.3f} — "
                f"responses diverge too much across runs"
            )
        if min_pair < min_pair_floor:
            raise AssertionError(
                f"min pairwise similarity {min_pair:.3f} below floor "
                f"{min_pair_floor:.3f} — at least one pair drifted significantly"
            )
        logger.info(
            f"Variance within threshold: mean={mean:.3f} >= {mean_floor:.3f}, "
            f"min={min_pair:.3f} >= {min_pair_floor:.3f}"
        )

    @keyword("Log Consistency Metrics")
    def log_consistency_metrics(
        self, result: Dict[str, Any], kind: str, temperature: float
    ) -> None:
        """Emit RFC_DATA so consistency results land in the SQL archive.

        Args:
            result: Dict from determinism or variance keyword.
            kind: ``"determinism"`` or ``"variance"``.
            temperature: Sampling temperature used for the run.
        """
        emit_rfc_data("consistency_kind", str(kind))
        emit_rfc_data("consistency_temperature", str(round(float(temperature), 4)))

        if kind == "determinism":
            emit_rfc_data(
                "consistency_match_rate",
                str(round(float(result.get("match_rate", 0.0)), 4)),
            )
            emit_rfc_data(
                "consistency_unique_count",
                str(int(result.get("unique_count", 0))),
            )
            emit_rfc_data("score", str(round(float(result.get("match_rate", 0.0)), 2)))
        else:
            emit_rfc_data(
                "consistency_mean_similarity",
                str(round(float(result.get("mean_similarity", 0.0)), 4)),
            )
            emit_rfc_data(
                "consistency_min_pairwise",
                str(round(float(result.get("min_pairwise", 0.0)), 4)),
            )
            emit_rfc_data(
                "consistency_n_pairs",
                str(int(result.get("n_pairs", 0))),
            )
            emit_rfc_data(
                "score", str(round(float(result.get("mean_similarity", 0.0)), 2))
            )
