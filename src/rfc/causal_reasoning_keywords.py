"""Robot Framework keywords for causal reasoning tests."""

from typing import Any, Dict, Optional

from robot.api import logger
from robot.api.deco import keyword

from .causal_reasoning_grader import CausalGradeResult, CausalReasoningGrader
from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data
from .thinking import parse_thinking


class CausalReasoningKeywords:
    """Robot Framework keywords for testing LLM causal reasoning ability.

    Covers five question types:
    - cause_id: identify the root cause in a scenario
    - effect_pred: predict the downstream effect of an intervention
    - counterfactual: reason about what would have happened otherwise
    - correlation_vs_causation: distinguish causal from correlational relationships
    - causal_chain: trace a multi-hop A→B→C chain back to the initiating cause
    """

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    PASS_THRESHOLD = 0.5

    def __init__(self, timeout: Optional[int] = None, max_retries: int = 2) -> None:
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))
        self.grader = CausalReasoningGrader(self.client)

    @keyword("Ask And Grade Causal Response")
    def ask_and_grade_causal_response(
        self,
        scenario: str,
        question: str,
        expected: str,
        question_type: str,
    ) -> CausalGradeResult:
        """Send a causal reasoning prompt to the LLM and grade the response.

        Args:
            scenario: Context text describing the causal situation.
            question: The specific causal reasoning question to ask.
            expected: The correct answer or grading criteria.
            question_type: One of cause_id, effect_pred, counterfactual,
                           correlation_vs_causation, causal_chain.

        Returns:
            CausalGradeResult with score, reason, and question_type.
        """
        prompt = f"{scenario}\n\n{question}"
        logger.info(f"Causal reasoning prompt ({question_type}): {prompt[:120]}...")

        raw_response = self.client.generate(prompt)
        clean_answer, _thinking = parse_thinking(raw_response, strip_unclosed=True)

        logger.info(f"LLM response: {clean_answer[:200]}...")

        emit_rfc_data("actual_answer", clean_answer)
        emit_rfc_data("question_type", question_type)

        result = self.grader.grade(
            scenario=scenario,
            question=question,
            expected=expected,
            actual=clean_answer,
            question_type=question_type,
        )

        emit_rfc_data("score", str(result.score))
        emit_rfc_data("grading_reason", result.reason)
        emit_rfc_data("passed", str(result.passed))

        logger.info(
            f"Causal grade: score={result.score}, passed={result.passed}, "
            f"reason={result.reason}"
        )
        return result

    @keyword("Assert Causal Grade Passes")
    def assert_causal_grade_passes(
        self,
        result: CausalGradeResult,
        threshold: float = PASS_THRESHOLD,
    ) -> None:
        """Assert that a causal grade result meets the passing threshold.

        Args:
            result: CausalGradeResult from Ask And Grade Causal Response.
            threshold: Minimum score required to pass (default 0.5).

        Raises:
            AssertionError: If score < threshold.
        """
        threshold = float(threshold)
        if result.score < threshold:
            raise AssertionError(
                f"Causal reasoning FAILED: score={result.score:.2f} < {threshold:.2f}. "
                f"Question type: {result.question_type}. "
                f"Reason: {result.reason}"
            )
        logger.info(
            f"Causal reasoning PASSED: score={result.score:.2f} >= {threshold:.2f}"
        )

    @keyword("Ask And Assert Causal Reasoning")
    def ask_and_assert_causal_reasoning(
        self,
        scenario: str,
        question: str,
        expected: str,
        question_type: str,
        threshold: float = PASS_THRESHOLD,
    ) -> CausalGradeResult:
        """Convenience keyword: ask the LLM, grade, and assert pass in one step.

        Args:
            scenario: Context text describing the causal situation.
            question: The specific causal reasoning question to ask.
            expected: The correct answer or grading criteria.
            question_type: One of cause_id, effect_pred, counterfactual,
                           correlation_vs_causation, causal_chain.
            threshold: Minimum score required to pass (default 0.5).

        Returns:
            CausalGradeResult on success.

        Raises:
            AssertionError: If the grade does not meet the threshold.
        """
        result = self.ask_and_grade_causal_response(
            scenario=scenario,
            question=question,
            expected=expected,
            question_type=question_type,
        )
        self.assert_causal_grade_passes(result, threshold=threshold)
        return result

    @keyword("Ask And Check Causal JSON Structure")
    def ask_and_check_causal_json_structure(
        self,
        prompt: str,
    ) -> Dict[str, Any]:
        """Ask the LLM for structured causal JSON output and verify its structure.

        Instructs the model to respond with {"cause": "...", "effect": "..."}
        and deterministically validates the output (Tier 1).

        Args:
            prompt: The causal reasoning prompt. A JSON formatting instruction
                    is appended automatically.

        Returns:
            Dict with has_cause, has_effect, is_valid, cause, effect.
        """
        structured_prompt = (
            f"{prompt}\n\n"
            "Respond ONLY with valid JSON in this exact format:\n"
            '{"cause": "<cause>", "effect": "<effect>"}\n'
            "No markdown, no extra text."
        )
        logger.info(f"Asking for structured causal JSON: {prompt[:80]}...")
        raw_response = self.client.generate(structured_prompt)
        clean_answer, _thinking = parse_thinking(raw_response, strip_unclosed=True)

        emit_rfc_data("actual_answer", clean_answer)

        check_result = self.grader.check_causal_json_structure(clean_answer)

        emit_rfc_data("causal_json_valid", str(check_result["is_valid"]))
        if check_result["cause"]:
            emit_rfc_data("extracted_cause", str(check_result["cause"]))
        if check_result["effect"]:
            emit_rfc_data("extracted_effect", str(check_result["effect"]))

        logger.info(
            f"JSON structure check: valid={check_result['is_valid']}, "
            f"cause={check_result['cause']!r}, effect={check_result['effect']!r}"
        )
        return check_result
