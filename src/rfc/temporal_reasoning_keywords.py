"""Robot Framework keywords for temporal reasoning evaluation.

Tests whether an LLM can correctly reason about time — ordering events
chronologically, performing date arithmetic, and sequencing multi-step
timelines.

Temporal reasoning is a growing LLM use-case (scheduling assistants,
document timeline analysis, project planning) and a known failure mode:
models often confuse event order, miscalculate date spans, or hallucinate
historical dates.

Grading:
  - Tier 1 (ordering, sequence):  structured verdict extracted from the
    first response line; verified deterministically in Python.
  - Tier 1 (date arithmetic):     numeric answer extracted from the first
    response line; compared to a known-correct integer.
"""

import re
from typing import Any, Dict, List, Optional

from robot.api import logger
from robot.api.deco import keyword

from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data

# ── Verdict regex ──────────────────────────────────────────────────────────
# Matches BEFORE or AFTER as the leading token on the first non-blank line.
# Optional label prefix (e.g. "Verdict:") is allowed.
_ORDER_RE = re.compile(r"^\s*(?:\w+:\s*)?(BEFORE|AFTER)\b", re.IGNORECASE)

# Matches the first integer (possibly with commas or surrounding text) in a line.
_INT_RE = re.compile(r"\b(\d[\d,]*)\b")

# Finds standalone event-label letters A–C (word-boundary anchored) on the
# first non-blank line.  A valid sequence must contain exactly 3 matches.
_SEQUENCE_LETTER_RE = re.compile(r"(?<!\w)([A-Ca-c])(?!\w)")

# ── Prompt templates ───────────────────────────────────────────────────────

_ORDER_PROMPT = """\
Determine which of the two events occurred FIRST chronologically.

Event A: {event_a}
Event B: {event_b}

Respond with exactly one of these verdicts on the very first line:
  BEFORE — Event A occurred before Event B
  AFTER  — Event A occurred after Event B

Then briefly explain your reasoning in 1–2 sentences.

Verdict:"""

_DATE_CALC_PROMPT = """\
Answer the following date or time calculation question with a single integer.

Question: {question}

Write only the integer answer on the very first line (no units, no comma \
separators).  Then briefly explain your reasoning.

Answer:"""

_SEQUENCE_PROMPT = """\
Order the following events from EARLIEST to LATEST based on when they \
historically occurred.

A: {event_a}
B: {event_b}
C: {event_c}

Write the three letters separated by commas on the very first line \
(e.g. "A, B, C" for earliest to latest).  Then briefly explain.

Order:"""


# ── Private helpers ────────────────────────────────────────────────────────


def _extract_order_verdict(response: str) -> Optional[str]:
    """Extract BEFORE or AFTER from the first non-blank line of *response*.

    Returns the uppercase verdict string, or ``None`` if no verdict is found.
    """
    first_line = response.strip().splitlines()[0] if response.strip() else ""
    m = _ORDER_RE.match(first_line)
    if m:
        return m.group(1).upper()
    return None


def _extract_integer(response: str) -> Optional[int]:
    """Extract the first integer from the first non-blank line of *response*.

    Strips commas from numbers like "1,000".
    Returns ``None`` if no integer is found.
    """
    first_line = response.strip().splitlines()[0] if response.strip() else ""
    m = _INT_RE.search(first_line)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def _extract_sequence(response: str) -> Optional[List[str]]:
    """Extract the A/B/C sequence from the first non-blank line of *response*.

    Uses word-boundary matching so letters embedded in words (e.g. the 'C'
    in "Correct:") are not treated as event labels.  Returns a list of
    uppercase letters only when exactly 3 are found; otherwise returns
    ``None``.
    """
    first_line = response.strip().splitlines()[0] if response.strip() else ""
    letters = [m.group(1).upper() for m in _SEQUENCE_LETTER_RE.finditer(first_line)]
    return letters if len(letters) == 3 else None  # noqa: PLR2004


# ── Keyword class ──────────────────────────────────────────────────────────


class TemporalReasoningKeywords:
    """Robot Framework keywords for temporal reasoning evaluation."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_retries: int = 2,
    ) -> None:
        timeout = resolve_timeout(timeout)
        self.client: Any = create_provider(
            timeout=timeout, max_retries=int(max_retries)
        )

    # ── Tier 1: chronological ordering ────────────────────────────────────

    @keyword("Evaluate Temporal Order")
    def evaluate_temporal_order(
        self,
        event_a: str,
        event_b: str,
        expected_verdict: str,
    ) -> Dict[str, Any]:
        """Ask the LLM whether Event A occurred BEFORE or AFTER Event B.

        Args:
            event_a: Description of the first event (including approximate date).
            event_b: Description of the second event (including approximate date).
            expected_verdict: ``"BEFORE"`` or ``"AFTER"``.

        Returns:
            Dict with keys: verdict, expected, correct, response.

        Raises:
            ValueError: If expected_verdict is not BEFORE or AFTER.
        """
        expected_verdict = expected_verdict.strip().upper()
        if expected_verdict not in ("BEFORE", "AFTER"):
            raise ValueError(
                f"expected_verdict must be 'BEFORE' or 'AFTER', got {expected_verdict!r}"
            )

        prompt = _ORDER_PROMPT.format(event_a=event_a, event_b=event_b)
        logger.info(f"Temporal order prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"Response:\n{response}")

        verdict = _extract_order_verdict(response)
        correct = verdict == expected_verdict

        if verdict is None:
            logger.warn(
                "Could not extract BEFORE/AFTER verdict from response first line"
            )

        emit_rfc_data("temporal_verdict", str(verdict))
        emit_rfc_data("temporal_expected", expected_verdict)
        emit_rfc_data("temporal_correct", str(correct))

        return {
            "verdict": verdict,
            "expected": expected_verdict,
            "correct": correct,
            "response": response,
        }

    # ── Tier 1: date / time arithmetic ────────────────────────────────────

    @keyword("Evaluate Date Calculation")
    def evaluate_date_calculation(
        self,
        question: str,
        expected_answer: int,
    ) -> Dict[str, Any]:
        """Ask the LLM a date-arithmetic question and verify the integer answer.

        Args:
            question: A date/time calculation question with a single integer answer.
            expected_answer: The correct integer result.

        Returns:
            Dict with keys: calculated, expected, correct, response.
        """
        expected_answer = int(expected_answer)
        prompt = _DATE_CALC_PROMPT.format(question=question)
        logger.info(f"Date calculation prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"Response:\n{response}")

        calculated = _extract_integer(response)
        correct = calculated == expected_answer

        if calculated is None:
            logger.warn("Could not extract integer from response first line")

        emit_rfc_data("date_calculated", str(calculated))
        emit_rfc_data("date_expected", str(expected_answer))
        emit_rfc_data("date_correct", str(correct))

        return {
            "calculated": calculated,
            "expected": expected_answer,
            "correct": correct,
            "response": response,
        }

    # ── Tier 1: event sequence ordering ───────────────────────────────────

    @keyword("Evaluate Event Sequence")
    def evaluate_event_sequence(
        self,
        event_a: str,
        event_b: str,
        event_c: str,
        expected_sequence: str,
    ) -> Dict[str, Any]:
        """Ask the LLM to order three events from earliest to latest.

        Args:
            event_a: Description of Event A.
            event_b: Description of Event B.
            event_c: Description of Event C.
            expected_sequence: Correct order as a comma-separated string of
                letters, e.g. ``"A, B, C"`` or ``"C, A, B"``.

        Returns:
            Dict with keys: sequence, expected, correct, response.

        Raises:
            ValueError: If expected_sequence does not contain exactly 3 letters.
        """
        expected_letters = [
            c.upper() for c in re.findall(r"[A-Ca-c]", expected_sequence)
        ]
        if len(expected_letters) != 3:  # noqa: PLR2004
            raise ValueError(
                f"expected_sequence must contain exactly 3 letters A–C, "
                f"got {expected_sequence!r}"
            )

        prompt = _SEQUENCE_PROMPT.format(
            event_a=event_a, event_b=event_b, event_c=event_c
        )
        logger.info(f"Sequence prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"Response:\n{response}")

        sequence = _extract_sequence(response)
        correct = sequence == expected_letters if sequence is not None else False

        if sequence is None:
            logger.warn("Could not extract letter sequence from response first line")

        emit_rfc_data("sequence_got", str(sequence))
        emit_rfc_data("sequence_expected", str(expected_letters))
        emit_rfc_data("sequence_correct", str(correct))

        return {
            "sequence": sequence,
            "expected": expected_letters,
            "correct": correct,
            "response": response,
        }
