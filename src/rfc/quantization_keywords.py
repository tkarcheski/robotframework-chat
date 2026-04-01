"""Robot Framework keywords for quantization degradation testing.

Compares LLM accuracy between Q4 and Q8 GGUF quantization variants,
logging deltas to the SQL archive for Superset trend visualisation.
"""

import re
from typing import Any, Dict, List, Optional

from robot.api import logger
from robot.api.deco import keyword

from .grader import Grader
from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data
from .thinking import parse_thinking

# Regex patterns for matching quantization levels in model names.
_Q4_PATTERN = re.compile(r"q4", re.IGNORECASE)
_Q8_PATTERN = re.compile(r"q8", re.IGNORECASE)


class QuantizationKeywords:
    """Robot Framework keywords for comparing accuracy across quantization levels."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(self, timeout: Optional[int] = None, max_retries: int = 2) -> None:
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))
        self.grader = Grader(self.client)

    @keyword("Discover Quantization Variants")
    def discover_quantization_variants(self, base_model: str) -> Dict[str, Any]:
        """Query Ollama for available Q4 and Q8 variants of a base model.

        Scans all models available on the Ollama endpoint and matches those
        whose name starts with the base_model prefix and contains q4 or q8
        in the name.

        Args:
            base_model: The base model family name (e.g. "mistral", "llama3").

        Returns:
            Dict with base_model, q4_model, q8_model, both_available.
        """
        logger.info(f"Discovering quantization variants for: {base_model}")
        models = self.client.list_models_detailed()  # type: ignore[attr-defined]

        q4_model: Optional[str] = None
        q8_model: Optional[str] = None
        base_lower = base_model.lower()

        for model in models:
            name = model.get("name", "")
            name_lower = name.lower()
            if not name_lower.startswith(base_lower):
                continue

            if _Q4_PATTERN.search(name_lower) and q4_model is None:
                q4_model = name
                logger.info(f"Found Q4 variant: {name}")
            elif _Q8_PATTERN.search(name_lower) and q8_model is None:
                q8_model = name
                logger.info(f"Found Q8 variant: {name}")

        both_available = q4_model is not None and q8_model is not None
        result: Dict[str, Any] = {
            "base_model": base_model,
            "q4_model": q4_model,
            "q8_model": q8_model,
            "both_available": both_available,
        }

        if not both_available:
            missing = []
            if q4_model is None:
                missing.append("Q4")
            if q8_model is None:
                missing.append("Q8")
            logger.warn(
                f"Missing {', '.join(missing)} variant(s) for {base_model}. "
                f"Available: q4={q4_model}, q8={q8_model}"
            )

        return result

    @keyword("Run Quantization Comparison")
    def run_quantization_comparison(
        self,
        q4_model: str,
        q8_model: str,
        prompts: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """Run the same prompts against Q4 and Q8 variants and compute deltas.

        Switches the model for each prompt, grades both responses, and
        computes the accuracy delta.

        Args:
            q4_model: The Q4 quantization model name.
            q8_model: The Q8 quantization model name.
            prompts: List of dicts with 'question' and 'expected' keys.

        Returns:
            Dict with q4_scores, q8_scores, q4_avg, q8_avg, delta,
            degradation_pct, prompt_details.
        """
        logger.info(
            f"Running quantization comparison: {q4_model} vs {q8_model} "
            f"({len(prompts)} prompts)"
        )
        original_model = self.client.model

        q4_scores: List[float] = []
        q8_scores: List[float] = []
        prompt_details: List[Dict[str, Any]] = []

        for i, prompt_data in enumerate(prompts):
            question = prompt_data["question"]
            expected = prompt_data["expected"]

            # Run Q4
            self.client.model = q4_model
            raw_q4 = self.client.generate(question)
            resp_q4, _ = parse_thinking(raw_q4, strip_unclosed=True)
            grade_q4 = self.grader.grade(question, expected, resp_q4)
            q4_scores.append(grade_q4.score)

            # Run Q8
            self.client.model = q8_model
            raw_q8 = self.client.generate(question)
            resp_q8, _ = parse_thinking(raw_q8, strip_unclosed=True)
            grade_q8 = self.grader.grade(question, expected, resp_q8)
            q8_scores.append(grade_q8.score)

            prompt_details.append(
                {
                    "question": question,
                    "expected": expected,
                    "q4_response": resp_q4,
                    "q8_response": resp_q8,
                    "q4_score": grade_q4.score,
                    "q8_score": grade_q8.score,
                    "delta": grade_q4.score - grade_q8.score,
                }
            )

            logger.info(
                f"Prompt {i + 1}/{len(prompts)}: "
                f"Q4={grade_q4.score:.2f} Q8={grade_q8.score:.2f} "
                f"delta={grade_q4.score - grade_q8.score:+.2f}"
            )

        # Restore original model
        self.client.model = original_model

        q4_avg = sum(q4_scores) / len(q4_scores) if q4_scores else 0.0
        q8_avg = sum(q8_scores) / len(q8_scores) if q8_scores else 0.0
        delta = q4_avg - q8_avg
        degradation_pct = (
            ((q8_avg - q4_avg) / q8_avg * 100.0) if q8_avg > 0 else 0.0
        )

        # Emit structured data for DB archiving
        emit_rfc_data("score", str(round(q4_avg, 2)))
        emit_rfc_data(
            "grading_reason",
            f"Q4={q4_avg:.2f} Q8={q8_avg:.2f} "
            f"delta={delta:+.2f} degradation={degradation_pct:.1f}%",
        )
        emit_rfc_data("quant_delta", str(round(delta, 4)))
        emit_rfc_data("quant_degradation_pct", str(round(degradation_pct, 2)))

        result: Dict[str, Any] = {
            "q4_model": q4_model,
            "q8_model": q8_model,
            "q4_scores": q4_scores,
            "q8_scores": q8_scores,
            "q4_avg": q4_avg,
            "q8_avg": q8_avg,
            "delta": delta,
            "degradation_pct": degradation_pct,
            "prompt_details": prompt_details,
        }

        logger.info(
            f"Quantization comparison complete: "
            f"Q4 avg={q4_avg:.2f}, Q8 avg={q8_avg:.2f}, "
            f"delta={delta:+.2f}, degradation={degradation_pct:.1f}%"
        )
        return result

    @keyword("Assert Acceptable Degradation")
    def assert_acceptable_degradation(
        self, result: Dict[str, Any], max_degradation_pct: float = 20.0
    ) -> None:
        """Assert Q4 degradation vs Q8 is within acceptable bounds.

        Args:
            result: The result dict from Run Quantization Comparison.
            max_degradation_pct: Maximum acceptable degradation percentage.

        Raises:
            AssertionError: If degradation exceeds the threshold.
        """
        max_degradation_pct = float(max_degradation_pct)
        pct = result.get("degradation_pct", 0.0)
        if pct > max_degradation_pct:
            q4_avg = result.get("q4_avg", 0.0)
            q8_avg = result.get("q8_avg", 0.0)
            raise AssertionError(
                f"Quantization degradation exceeds threshold: "
                f"{pct:.1f}% > {max_degradation_pct:.1f}%\n"
                f"Q4 avg={q4_avg:.2f}, Q8 avg={q8_avg:.2f}"
            )
        logger.info(
            f"Degradation acceptable: {pct:.1f}% <= {max_degradation_pct:.1f}%"
        )

    @keyword("Log Quantization Delta")
    def log_quantization_delta(self, result: Dict[str, Any]) -> None:
        """Emit RFC_DATA for quantization delta metrics.

        Logs Q4/Q8 averages, delta, and degradation percentage for
        Superset dashboard trend visualisation.

        Args:
            result: The result dict from Run Quantization Comparison.
        """
        emit_rfc_data("quant_q4_avg", str(round(result.get("q4_avg", 0.0), 4)))
        emit_rfc_data("quant_q8_avg", str(round(result.get("q8_avg", 0.0), 4)))
        emit_rfc_data("quant_delta", str(round(result.get("delta", 0.0), 4)))
        emit_rfc_data(
            "quant_degradation_pct",
            str(round(result.get("degradation_pct", 0.0), 2)),
        )
        emit_rfc_data("quant_q4_model", result.get("q4_model", ""))
        emit_rfc_data("quant_q8_model", result.get("q8_model", ""))
        logger.info(
            f"Quantization delta logged: "
            f"Q4={result.get('q4_avg', 0):.2f} "
            f"Q8={result.get('q8_avg', 0):.2f} "
            f"delta={result.get('delta', 0):+.2f}"
        )
