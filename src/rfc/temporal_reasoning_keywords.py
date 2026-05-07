"""Temporal reasoning keywords for Robot Framework.

Tests LLM ability to perform date arithmetic, duration calculation,
day-of-week inference, and event sequencing — all areas where models
commonly regress and where correct answers are verifiable by Python.

Tier 1 tests use deterministic substring matching against a precomputed
expected answer.  Tier 2 tests use an LLM judge for open-ended sequencing
questions.
"""

from typing import Any, Dict, Optional

from robot.api import logger
from robot.api.deco import keyword

from .grader import Grader
from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data


def _response_contains(response: str, expected: str) -> bool:
    """Return True when *expected* appears verbatim (case-insensitive) in *response*."""
    return expected.lower() in response.lower()


class TemporalReasoningKeywords:
    """Robot Framework keywords for temporal reasoning evaluation."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_retries: int = 2,
    ) -> None:
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))
        self.grader = Grader(self.client)

    @keyword("Run Temporal Exact Match Test")
    def run_temporal_exact_match_test(
        self,
        question: str,
        expected: str,
    ) -> Dict[str, Any]:
        """Ask the LLM a temporal question and verify the answer via substring match.

        Tier 1 — deterministic Python check.  The *expected* string (e.g. a date
        or a number) must appear anywhere in the model's response.

        Args:
            question: The temporal question to ask.
            expected:  The string that must appear in the response (e.g. "March 31").

        Returns:
            Dict with keys: score (0.0 or 1.0), response, expected, passed.

        Raises:
            ValueError: If question or expected is empty.
        """
        if not question.strip():
            raise ValueError("question must not be empty")
        if not expected.strip():
            raise ValueError("expected must not be empty")

        logger.info(f"Temporal question: {question}")
        response = self.client.generate(question)
        logger.info(f"LLM response: {response}")

        passed = _response_contains(response, expected)
        score = 1.0 if passed else 0.0
        reason = (
            f"found '{expected}' in response"
            if passed
            else f"'{expected}' not found in response"
        )

        emit_rfc_data("score", str(score))
        emit_rfc_data("expected_answer", expected)
        emit_rfc_data("actual_answer", response)
        emit_rfc_data("grading_reason", reason)

        return {
            "score": score,
            "response": response,
            "expected": expected,
            "passed": passed,
        }

    @keyword("Run Temporal Graded Test")
    def run_temporal_graded_test(
        self,
        question: str,
        expected: str,
        min_score: float = 0.5,
    ) -> Dict[str, Any]:
        """Ask the LLM a temporal reasoning question and evaluate with an LLM judge.

        Tier 2 — used for questions with correct but non-trivially matchable
        answers (event sequencing, relative duration comparisons, calendar inference
        requiring multi-step reasoning).

        Args:
            question:  The temporal reasoning question.
            expected:  Description of the correct answer for the grader.
            min_score: Minimum score to consider the test passed (default 0.5).

        Returns:
            Dict with keys: score, response, reason, passed.

        Raises:
            ValueError: If question is empty.
        """
        if not question.strip():
            raise ValueError("question must not be empty")

        logger.info(f"Temporal graded question: {question}")
        response = self.client.generate(question)
        logger.info(f"LLM response: {response}")

        grade = self.grader.grade(question, expected, response)

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
