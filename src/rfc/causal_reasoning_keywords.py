"""Causal reasoning keywords for Robot Framework.

Tests LLM ability to distinguish correlation from causation, identify
confounding variables, evaluate counterfactuals, and reason about
causal interventions.

All tests use a single LLM judge (tier 2) because correct answers require
nuanced reasoning that cannot be verified by substring matching alone.
"""

from typing import Any, Dict, Optional

from robot.api import logger
from robot.api.deco import keyword

from .grader import Grader
from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data


class CausalReasoningKeywords:
    """Robot Framework keywords for causal reasoning evaluation."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_retries: int = 2,
    ) -> None:
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))
        self.grader = Grader(self.client)

    @keyword("Run Causal Discrimination Test")
    def run_causal_discrimination_test(
        self,
        scenario: str,
        expected: str,
        min_score: float = 0.5,
    ) -> Dict[str, Any]:
        """Present a scenario and ask the LLM whether the relationship is causal.

        Tier 2 — LLM judge evaluates whether the model correctly identifies
        the relationship type (correlation vs. causation) and names the key
        mechanism (confound, common cause, reverse causation, etc.).

        Args:
            scenario:  The scenario describing an observed association.
            expected:  What a correct answer must convey (relationship type +
                       mechanism).
            min_score: Minimum passing score (default 0.5).

        Returns:
            Dict with keys: score, response, reason, passed.

        Raises:
            ValueError: If scenario is empty.
        """
        if not scenario.strip():
            raise ValueError("scenario must not be empty")

        prompt = (
            f"{scenario}\n\n"
            "Does this represent a causal relationship or merely a correlation? "
            "Explain the mechanism behind the observed association."
        )

        logger.info(f"Causal discrimination scenario: {scenario[:80]}...")
        response = self.client.generate(prompt)
        logger.info(f"LLM response: {response}")

        grade = self.grader.grade(prompt, expected, response)

        emit_rfc_data("score", str(grade.score))
        emit_rfc_data("expected_answer", expected)
        emit_rfc_data("actual_answer", response)
        emit_rfc_data("grading_reason", grade.reason)

        return {
            "score": grade.score,
            "response": response,
            "reason": grade.reason,
            "passed": grade.score >= float(min_score),
        }

    @keyword("Run Counterfactual Test")
    def run_counterfactual_test(
        self,
        scenario: str,
        expected: str,
        min_score: float = 0.5,
    ) -> Dict[str, Any]:
        """Ask the LLM to reason about a counterfactual historical or scientific scenario.

        Tier 2 — evaluates plausibility of counterfactual reasoning, not
        factual correctness (which is undefined for counterfactuals).

        Args:
            scenario:  The counterfactual premise (e.g. "If antibiotics had not
                       been discovered...").
            expected:  Key elements the response should address.
            min_score: Minimum passing score (default 0.5).

        Returns:
            Dict with keys: score, response, reason, passed.

        Raises:
            ValueError: If scenario is empty.
        """
        if not scenario.strip():
            raise ValueError("scenario must not be empty")

        logger.info(f"Counterfactual scenario: {scenario[:80]}...")
        response = self.client.generate(scenario)
        logger.info(f"LLM response: {response}")

        grade = self.grader.grade(scenario, expected, response)

        emit_rfc_data("score", str(grade.score))
        emit_rfc_data("expected_answer", expected)
        emit_rfc_data("actual_answer", response)
        emit_rfc_data("grading_reason", grade.reason)

        return {
            "score": grade.score,
            "response": response,
            "reason": grade.reason,
            "passed": grade.score >= float(min_score),
        }

    @keyword("Run Intervention Test")
    def run_intervention_test(
        self,
        scenario: str,
        expected: str,
        min_score: float = 0.5,
    ) -> Dict[str, Any]:
        """Ask the LLM to evaluate a proposed causal intervention.

        Tier 2 — tests whether the model can distinguish valid causal
        interventions from ones that exploit merely correlational data.

        Args:
            scenario:  Description of the observation and the proposed action.
            expected:  What a correct evaluation must address.
            min_score: Minimum passing score (default 0.5).

        Returns:
            Dict with keys: score, response, reason, passed.

        Raises:
            ValueError: If scenario is empty.
        """
        if not scenario.strip():
            raise ValueError("scenario must not be empty")

        prompt = (
            f"{scenario}\n\n"
            "Is this a reasonable causal intervention? "
            "Explain your reasoning, including any potential confounds or "
            "alternative explanations."
        )

        logger.info(f"Intervention scenario: {scenario[:80]}...")
        response = self.client.generate(prompt)
        logger.info(f"LLM response: {response}")

        grade = self.grader.grade(prompt, expected, response)

        emit_rfc_data("score", str(grade.score))
        emit_rfc_data("expected_answer", expected)
        emit_rfc_data("actual_answer", response)
        emit_rfc_data("grading_reason", grade.reason)

        return {
            "score": grade.score,
            "response": response,
            "reason": grade.reason,
            "passed": grade.score >= float(min_score),
        }
