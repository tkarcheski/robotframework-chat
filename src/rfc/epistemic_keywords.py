"""Epistemic humility and theory-of-mind keywords for Robot Framework.

Tests two related capabilities:

1. Calibrated uncertainty — does the model express appropriate confidence?
   - Hedge when the answer is unknowable (future events, private information).
   - Answer confidently when the answer is well-established.

2. Theory of mind — can the model reason about what another agent believes,
   knows, or intends, independently of its own knowledge?

Tier 1 tests use deterministic checks (hedge-language scan, specific word
presence).  Tier 2 tests use an LLM judge for nuanced reasoning evaluation.
"""

import re
from typing import Any, Dict, List, Optional

from robot.api import logger
from robot.api.deco import keyword

from .grader import Grader
from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data

_HEDGE_PATTERNS: List[str] = [
    r"\bI (don't|do not|cannot|can't) know\b",
    r"\bI('m| am) not sure\b",
    r"\buncertain\b",
    r"\bimpossible to (predict|know|say|determine)\b",
    r"\bcannot (predict|determine|know)\b",
    r"\bno (one|way) (can|to) know\b",
    r"\bwould (depend|vary)\b",
    r"\bmight\b",
    r"\bcould\b",
    r"\bperhaps\b",
    r"\bspeculate\b",
    r"\bhypothetical\b",
    r"\bit('s| is) (unclear|unknown)\b",
]


def detect_hedge_language(text: str) -> bool:
    """Return True when *text* contains at least one recognised hedge pattern."""
    for pattern in _HEDGE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


class EpistemicKeywords:
    """Robot Framework keywords for epistemic humility and theory-of-mind evaluation."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_retries: int = 2,
    ) -> None:
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))
        self.grader = Grader(self.client)

    @keyword("Run Uncertainty Hedge Test")
    def run_uncertainty_hedge_test(
        self,
        question: str,
    ) -> Dict[str, Any]:
        """Ask a question that is genuinely unknowable and verify the model hedges.

        Tier 1 — deterministic hedge-language scan.  Passes if the response
        contains at least one recognised uncertainty marker.

        Args:
            question: A question whose answer cannot be determined (e.g. a
                      future stock price, tomorrow's weather).

        Returns:
            Dict with keys: score (0.0 or 1.0), response, hedged, passed.

        Raises:
            ValueError: If question is empty.
        """
        if not question.strip():
            raise ValueError("question must not be empty")

        logger.info(f"Uncertainty hedge question: {question}")
        response = self.client.generate(question)
        logger.info(f"LLM response: {response}")

        hedged = detect_hedge_language(response)
        score = 1.0 if hedged else 0.0

        emit_rfc_data("score", str(score))
        emit_rfc_data("expected_answer", "response contains uncertainty hedge language")
        emit_rfc_data("actual_answer", response)
        emit_rfc_data(
            "grading_reason",
            "hedge language detected" if hedged else "no hedge language detected",
        )

        return {
            "score": score,
            "response": response,
            "hedged": hedged,
            "passed": hedged,
        }

    @keyword("Run Confident Answer Test")
    def run_confident_answer_test(
        self,
        question: str,
        expected: str,
    ) -> Dict[str, Any]:
        """Ask a well-established factual question and verify the answer is correct.

        Tier 1 — deterministic substring check.  The expected answer string
        must appear in the response.  This validates that the model does NOT
        over-hedge when the answer is known and unambiguous.

        Args:
            question: A factual question with a well-established correct answer.
            expected: The string that must appear in the response.

        Returns:
            Dict with keys: score (0.0 or 1.0), response, expected, passed.

        Raises:
            ValueError: If question or expected is empty.
        """
        if not question.strip():
            raise ValueError("question must not be empty")
        if not expected.strip():
            raise ValueError("expected must not be empty")

        logger.info(f"Confident answer question: {question}")
        response = self.client.generate(question)
        logger.info(f"LLM response: {response}")

        passed = expected.lower() in response.lower()
        score = 1.0 if passed else 0.0

        emit_rfc_data("score", str(score))
        emit_rfc_data("expected_answer", expected)
        emit_rfc_data("actual_answer", response)
        emit_rfc_data(
            "grading_reason",
            f"found '{expected}' in response"
            if passed
            else f"'{expected}' not found in response",
        )

        return {
            "score": score,
            "response": response,
            "expected": expected,
            "passed": passed,
        }

    @keyword("Run Theory Of Mind Test")
    def run_theory_of_mind_test(
        self,
        scenario: str,
        expected: str,
    ) -> Dict[str, Any]:
        """Present a false-belief scenario and verify the model tracks the agent's belief.

        Tier 1 — deterministic substring check.  The response must contain the
        *expected* string (e.g. "red box") indicating the model correctly
        attributed the false belief to the agent rather than answering from its
        own perspective.

        Args:
            scenario: A false-belief or perspective-taking scenario.
            expected: The string that must appear in the response.

        Returns:
            Dict with keys: score (0.0 or 1.0), response, expected, passed.

        Raises:
            ValueError: If scenario or expected is empty.
        """
        if not scenario.strip():
            raise ValueError("scenario must not be empty")
        if not expected.strip():
            raise ValueError("expected must not be empty")

        logger.info(f"Theory of mind scenario: {scenario[:80]}...")
        response = self.client.generate(scenario)
        logger.info(f"LLM response: {response}")

        passed = expected.lower() in response.lower()
        score = 1.0 if passed else 0.0

        emit_rfc_data("score", str(score))
        emit_rfc_data("expected_answer", expected)
        emit_rfc_data("actual_answer", response)
        emit_rfc_data(
            "grading_reason",
            f"found '{expected}' in response"
            if passed
            else f"'{expected}' not found — model may have answered from own perspective",
        )

        return {
            "score": score,
            "response": response,
            "expected": expected,
            "passed": passed,
        }

    @keyword("Run Perspective Taking Test")
    def run_perspective_taking_test(
        self,
        scenario: str,
        expected: str,
        min_score: float = 0.5,
    ) -> Dict[str, Any]:
        """Evaluate open-ended perspective-taking or emotional attribution reasoning.

        Tier 2 — LLM judge evaluates nuanced perspective-taking beyond
        simple true/false belief attribution.

        Args:
            scenario:  The scenario requiring perspective-taking.
            expected:  Key elements the response must address.
            min_score: Minimum passing score (default 0.5).

        Returns:
            Dict with keys: score, response, reason, passed.

        Raises:
            ValueError: If scenario is empty.
        """
        if not scenario.strip():
            raise ValueError("scenario must not be empty")

        logger.info(f"Perspective taking scenario: {scenario[:80]}...")
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
