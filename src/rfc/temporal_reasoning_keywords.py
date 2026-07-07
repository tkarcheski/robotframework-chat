"""Robot Framework keywords for temporal reasoning evaluation.

Tests whether an LLM can correctly perform date arithmetic, duration
calculations, and identify earliest events from historical knowledge.
These are Tier 1 tests: the LLM's numeric or letter answer is extracted
deterministically from the first line of its response.
"""

import re
from typing import Any, Dict, Optional

from robot.api import logger
from robot.api.deco import keyword

from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data

_DATE_ARITHMETIC_PROMPT = """\
Answer the following date arithmetic question.
Write the integer answer (digits only, no units, no explanation) on the very first line.

Question: {question}

Integer answer:"""

_DURATION_PROMPT = """\
Calculate the answer to the following duration question.
Write the integer answer (digits only, no units, no explanation) on the very first line.

Question: {question}

Integer answer:"""

_EVENT_ORDERING_PROMPT = """\
Four historical events are listed below with labels A, B, C, D.
Identify which event happened EARLIEST — furthest in the past.

{labeled_events}

Write the single letter (A, B, C, or D) of the earliest event on the very first line, \
then briefly explain.

Answer:"""

# Anchored to the start of the first non-empty line; optional label prefix allowed.
_LETTER_RE = re.compile(r"^\s*([A-Da-d])\b")


def _extract_first_integer(text: str) -> Optional[int]:
    """Return the first standalone integer on the first non-empty line, or None.

    First-line-only enforces the format contract (answer on line 1) and prevents
    coincidental numbers on later prose lines from producing false passes.
    """
    if not text:
        return None
    for line in text.strip().splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Comma-grouped format (e.g. 1,440) is tried before plain digits so
        # four-digit answers with thousands separators aren't truncated.
        m = re.search(r"(?<![.\d])(\d{1,3}(?:,\d{3})+|\d+)(?![.\d])", stripped)
        return int(m.group(1).replace(",", "")) if m else None
    return None


def _extract_letter(text: str) -> Optional[str]:
    """Return the letter A-D from the first non-empty line, or None."""
    if not text:
        return None
    for line in text.strip().splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        m = _LETTER_RE.match(stripped)
        if m:
            return m.group(1).upper()
        # First non-empty line had no anchored letter — stop searching.
        return None
    return None


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

    @keyword("Evaluate Date Arithmetic")
    def evaluate_date_arithmetic(
        self,
        question: str,
        expected_answer: int,
        tolerance: int = 0,
    ) -> Dict[str, Any]:
        """Ask the LLM a date arithmetic question and verify the numeric answer."""
        expected_answer = int(expected_answer)
        tolerance = int(tolerance)

        prompt = _DATE_ARITHMETIC_PROMPT.format(question=question)
        logger.info(f"Date arithmetic prompt:\n{prompt}")
        response = self.client.generate(prompt)
        logger.info(f"Response: {response}")
        emit_rfc_data("response", response)

        extracted = _extract_first_integer(response)
        emit_rfc_data("extracted_answer", str(extracted))
        emit_rfc_data("expected_answer", str(expected_answer))

        correct = (
            extracted is not None and abs(extracted - expected_answer) <= tolerance
        )
        emit_rfc_data("correct", str(correct))

        return {
            "response": response,
            "extracted_answer": extracted,
            "expected": expected_answer,
            "correct": correct,
        }

    @keyword("Evaluate Duration Calculation")
    def evaluate_duration_calculation(
        self,
        question: str,
        expected_answer: int,
        tolerance: int = 0,
    ) -> Dict[str, Any]:
        """Ask the LLM a duration conversion question and verify the answer."""
        expected_answer = int(expected_answer)
        tolerance = int(tolerance)

        prompt = _DURATION_PROMPT.format(question=question)
        logger.info(f"Duration calculation prompt:\n{prompt}")
        response = self.client.generate(prompt)
        logger.info(f"Response: {response}")
        emit_rfc_data("response", response)

        extracted = _extract_first_integer(response)
        emit_rfc_data("extracted_answer", str(extracted))
        emit_rfc_data("expected_answer", str(expected_answer))

        correct = (
            extracted is not None and abs(extracted - expected_answer) <= tolerance
        )
        emit_rfc_data("correct", str(correct))

        return {
            "response": response,
            "extracted_answer": extracted,
            "expected": expected_answer,
            "correct": correct,
        }

    @keyword("Check Earliest Event")
    def check_earliest_event(
        self,
        event_a: str,
        event_b: str,
        event_c: str,
        event_d: str,
        expected_letter: str,
    ) -> Dict[str, Any]:
        """Ask the LLM to identify the earliest of four historical events (A–D)."""
        expected_letter = expected_letter.strip().upper()
        if expected_letter not in {"A", "B", "C", "D"}:
            raise ValueError(
                f"expected_letter must be A, B, C, or D; got {expected_letter!r}"
            )

        labeled = f"A) {event_a}\nB) {event_b}\nC) {event_c}\nD) {event_d}"
        prompt = _EVENT_ORDERING_PROMPT.format(labeled_events=labeled)
        logger.info(f"Event ordering prompt:\n{prompt}")
        response = self.client.generate(prompt)
        logger.info(f"Response: {response}")
        emit_rfc_data("response", response)

        chosen = _extract_letter(response)
        emit_rfc_data("chosen_letter", str(chosen))
        emit_rfc_data("expected_letter", expected_letter)

        correct = chosen == expected_letter
        emit_rfc_data("correct", str(correct))

        return {
            "response": response,
            "chosen_letter": chosen,
            "expected": expected_letter,
            "correct": correct,
        }
