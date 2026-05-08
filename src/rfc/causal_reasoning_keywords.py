"""Causal reasoning evaluation keywords for Robot Framework.

Tests whether an LLM can distinguish genuine causation from correlation,
detect logical fallacies in causal arguments, and reason counterfactually.
"""

import re
from typing import Any, Dict, Optional

from robot.api import logger
from robot.api.deco import keyword

from .grader import Grader
from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data

# Anchored to the start of the first line; an optional single-word label
# (e.g. "Verdict:") is allowed before the token.  This prevents "causal"
# used as an adjective mid-sentence from being mistaken for a verdict.
_VERDICT_RE = re.compile(r"^\s*(?:\w+:\s*)?(NOT[_\s-]CAUSAL|CAUSAL)\b", re.IGNORECASE)
_LETTER_RE = re.compile(r"^\s*([A-Da-d])\b")

_CAUSAL_VERDICT_PROMPT = """\
Analyze the following scenario and causal claim. Decide whether the claim \
describes a genuine causal relationship.

Scenario: {scenario}
Claim: {claim}

Respond with exactly one of these verdicts on the first line:
  CAUSAL       — the claim is a genuine, direct causal relationship
  NOT_CAUSAL   — the claim is spurious, confounded, reversed, or coincidental

Then explain your reasoning in 2–3 sentences.

Verdict:"""

_FALLACY_PROMPT = """\
Identify the logical fallacy present in the following causal argument.

Argument: {argument}

Choose the single best answer:
  A) Post hoc ergo propter hoc — X happened before Y, so X must have caused Y
  B) Confounding variable — a third factor Z explains both X and Y independently
  C) Reverse causation — Y actually causes X, not X causing Y
  D) No fallacy — this is a genuine causal relationship

Write the letter (A, B, C, or D) on the very first line, then briefly explain.

Answer:"""

_COUNTERFACTUAL_PROMPT = """\
Consider the following counterfactual question carefully.

{question}

Reason through what would plausibly be different in a world where the stated \
condition had not occurred. Give a logically consistent, well-reasoned answer."""


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

    # ------------------------------------------------------------------
    # Tier 1: deterministic verdict extraction
    # ------------------------------------------------------------------

    @keyword("Evaluate Causal Claim")
    def evaluate_causal_claim(
        self,
        scenario: str,
        claim: str,
        expected_verdict: str,
    ) -> Dict[str, Any]:
        """Ask the LLM whether a claim is CAUSAL or NOT_CAUSAL and verify.

        Args:
            scenario: Background context describing the observed relationship.
            claim: The causal claim to evaluate.
            expected_verdict: ``"CAUSAL"`` or ``"NOT_CAUSAL"``.

        Returns:
            Dict with keys: verdict, correct, response, expected.

        Raises:
            ValueError: If expected_verdict is not one of the allowed values.
        """
        expected_verdict = expected_verdict.strip().upper().replace(" ", "_")
        allowed = {"CAUSAL", "NOT_CAUSAL"}
        if expected_verdict not in allowed:
            raise ValueError(
                f"expected_verdict must be one of {allowed}, got {expected_verdict!r}"
            )

        prompt = _CAUSAL_VERDICT_PROMPT.format(scenario=scenario, claim=claim)
        logger.info(f"Causal claim prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        verdict = _extract_verdict(response)

        correct = verdict == expected_verdict

        emit_rfc_data("scenario", scenario[:200])
        emit_rfc_data("claim", claim[:200])
        emit_rfc_data("expected_verdict", expected_verdict)
        emit_rfc_data("actual_verdict", verdict or "UNKNOWN")
        emit_rfc_data("correct", str(correct))

        return {
            "verdict": verdict,
            "correct": correct,
            "response": response,
            "expected": expected_verdict,
        }

    @keyword("Check Fallacy Detection")
    def check_fallacy_detection(
        self,
        argument: str,
        expected_letter: str,
    ) -> Dict[str, Any]:
        """Ask the LLM to identify the fallacy in a causal argument.

        Presents a multiple-choice question (A–D) and checks whether the LLM
        selects the correct option.

        Args:
            argument: The causal argument containing a logical error.
            expected_letter: Expected answer letter: ``"A"``, ``"B"``, ``"C"``,
                or ``"D"``.

        Returns:
            Dict with keys: chosen_letter, correct, response, expected.

        Raises:
            ValueError: If expected_letter is not A–D.
        """
        expected_letter = expected_letter.strip().upper()
        if expected_letter not in {"A", "B", "C", "D"}:
            raise ValueError(f"expected_letter must be A–D, got {expected_letter!r}")

        prompt = _FALLACY_PROMPT.format(argument=argument)
        logger.info(f"Fallacy detection prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        chosen = _extract_letter(response)
        correct = chosen == expected_letter

        emit_rfc_data("argument", argument[:200])
        emit_rfc_data("expected_letter", expected_letter)
        emit_rfc_data("chosen_letter", chosen or "UNKNOWN")
        emit_rfc_data("correct", str(correct))

        return {
            "chosen_letter": chosen,
            "correct": correct,
            "response": response,
            "expected": expected_letter,
        }

    # ------------------------------------------------------------------
    # Tier 2: LLM-graded counterfactual reasoning
    # ------------------------------------------------------------------

    @keyword("Grade Counterfactual")
    def grade_counterfactual(
        self,
        question: str,
        expected_elements: str,
        min_score: float = 0.5,
    ) -> Dict[str, Any]:
        """Ask the LLM a counterfactual question and grade the response.

        Args:
            question: A counterfactual question ("If X had not happened…").
            expected_elements: Key elements a correct answer should contain.
            min_score: Minimum passing score (0.0–1.0).

        Returns:
            Dict with keys: score, reason, response, passed.
        """
        prompt = _COUNTERFACTUAL_PROMPT.format(question=question)
        logger.info(f"Counterfactual prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        grade = self.grader.grade(question, expected_elements, response)
        passed = grade.score >= float(min_score)

        emit_rfc_data("question", question[:200])
        emit_rfc_data("expected_elements", expected_elements[:200])
        emit_rfc_data("score", str(grade.score))
        emit_rfc_data("passed", str(passed))
        emit_rfc_data("grading_reason", grade.reason)

        return {
            "score": grade.score,
            "reason": grade.reason,
            "response": response,
            "passed": passed,
        }


# ------------------------------------------------------------------
# Private helpers
# ------------------------------------------------------------------


def _extract_verdict(response: str) -> Optional[str]:
    """Extract CAUSAL or NOT_CAUSAL from the first non-empty line only.

    The prompt instructs the model to place the verdict on the first line.
    Searching the full body risks matching the word "causal" in explanatory
    prose (e.g. "there is no causal link"), which would silently convert a
    non-compliant response into a false verdict.  Non-compliant responses
    return ``None``; callers should treat that as a test failure.
    """
    first_line = response.strip().splitlines()[0] if response.strip() else ""
    m = _VERDICT_RE.search(first_line)
    if m:
        raw = m.group(1).upper().replace(" ", "_")
        return "NOT_CAUSAL" if "NOT" in raw else "CAUSAL"
    return None


def _extract_letter(response: str) -> Optional[str]:
    """Extract the answer letter A–D from the first line of a response."""
    first_line = response.strip().splitlines()[0] if response.strip() else ""
    m = _LETTER_RE.search(first_line)
    if m:
        return m.group(1).upper()
    return None
