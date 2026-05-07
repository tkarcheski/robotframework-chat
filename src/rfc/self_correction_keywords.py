"""Self-correction and error-detection keywords for Robot Framework.

Tests LLM ability to identify errors in provided content (math, code, logic)
and to produce corrected versions.

Tier 1 tests use deterministic substring checks — the correct value or fix
must appear in the response.  Tier 2 tests use an LLM judge to evaluate
explanations of logical flaws or the quality of a rewritten solution.
"""

from typing import Any, Dict, List, Optional

from robot.api import logger
from robot.api.deco import keyword

from .grader import Grader
from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data


def _any_marker_found(response: str, markers: List[str]) -> bool:
    """Return True when at least one marker string appears (case-insensitive)."""
    response_lower = response.lower()
    return any(m.lower() in response_lower for m in markers)


class SelfCorrectionKeywords:
    """Robot Framework keywords for error detection and self-correction evaluation."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_retries: int = 2,
    ) -> None:
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))
        self.grader = Grader(self.client)

    @keyword("Run Error Detection Test")
    def run_error_detection_test(
        self,
        prompt: str,
        detection_markers: List[str],
    ) -> Dict[str, Any]:
        """Present flawed content and check whether the model detects the error.

        Tier 1 — deterministic check.  At least one string from
        *detection_markers* must appear in the model's response.

        Args:
            prompt:            The prompt describing the flawed content and asking
                               the model to identify the error.
            detection_markers: List of strings indicating the error was found
                               (e.g. ["136", "wrong", "incorrect"]).

        Returns:
            Dict with keys: score (0.0 or 1.0), response, markers_found, passed.

        Raises:
            ValueError: If prompt is empty or detection_markers is empty.
        """
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        if not detection_markers:
            raise ValueError("detection_markers must not be empty")

        logger.info(f"Error detection prompt: {prompt[:80]}...")
        response = self.client.generate(prompt)
        logger.info(f"LLM response: {response}")

        passed = _any_marker_found(response, detection_markers)
        score = 1.0 if passed else 0.0
        found = [m for m in detection_markers if m.lower() in response.lower()]

        emit_rfc_data("score", str(score))
        emit_rfc_data("expected_answer", f"contains one of: {detection_markers}")
        emit_rfc_data("actual_answer", response)
        emit_rfc_data(
            "grading_reason",
            f"found markers {found}" if passed else "no detection marker found",
        )

        return {
            "score": score,
            "response": response,
            "markers_found": found,
            "passed": passed,
        }

    @keyword("Run Error Correction Test")
    def run_error_correction_test(
        self,
        prompt: str,
        expected: str,
        min_score: float = 0.5,
    ) -> Dict[str, Any]:
        """Ask the model to correct flawed content and grade the corrected output.

        Tier 2 — LLM judge evaluates whether the correction is complete,
        accurate, and well-explained.

        Args:
            prompt:    The prompt containing the flawed content plus instruction
                       to correct it.
            expected:  Description of what a correct fix must contain.
            min_score: Minimum passing score (default 0.5).

        Returns:
            Dict with keys: score, response, reason, passed.

        Raises:
            ValueError: If prompt is empty.
        """
        if not prompt.strip():
            raise ValueError("prompt must not be empty")

        logger.info(f"Error correction prompt: {prompt[:80]}...")
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

    @keyword("Run Logical Flaw Test")
    def run_logical_flaw_test(
        self,
        argument: str,
        expected: str,
        min_score: float = 0.5,
    ) -> Dict[str, Any]:
        """Ask the model to identify a logical flaw in a given argument.

        Tier 2 — LLM judge evaluates whether the model correctly names the
        fallacy type and explains why the argument fails.

        Args:
            argument:  The flawed argument text.
            expected:  Key elements the response must address (fallacy name +
                       explanation).
            min_score: Minimum passing score (default 0.5).

        Returns:
            Dict with keys: score, response, reason, passed.

        Raises:
            ValueError: If argument is empty.
        """
        if not argument.strip():
            raise ValueError("argument must not be empty")

        prompt = (
            f"Identify the logical flaw in the following argument and explain "
            f"why it is invalid:\n\n{argument}"
        )

        logger.info(f"Logical flaw argument: {argument[:80]}...")
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
