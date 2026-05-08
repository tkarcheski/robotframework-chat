"""Temporal reasoning evaluation keywords for Robot Framework.

Tests whether an LLM can order historical events chronologically, perform
date/duration arithmetic, resolve relative time expressions, and reason
about multi-step timelines — a well-documented weak spot for LLMs.
"""

import re
from typing import Any, Dict, List, Optional

from robot.api import logger
from robot.api.deco import keyword

from .grader import Grader
from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data

# Regex: one word-boundary-delimited single letter (any case).
# Using A-Z rather than A-D so that responses with extra out-of-range labels
# (e.g. "E") are detected and counted, causing _extract_order_letters to
# return None rather than silently ignoring surplus letters.
_ORDER_RE = re.compile(r"\b([A-Za-z])\b")

# Regex: first integer on a line
_INT_RE = re.compile(r"\b(\d+)\b")

# Regex: a single letter at the very start of the first non-empty line,
# optionally preceded by whitespace, followed by a word boundary
# (handles "A)", "A.", "A ", bare "A", etc.)
_LETTER_RE = re.compile(r"^\s*([A-Za-z])\b")

_ORDER_PROMPT = """\
Below are {n} events labeled {labels}. Order them chronologically from earliest \
to latest.

{events_text}

IMPORTANT: Your FIRST line must contain ONLY the {n} letters in chronological \
order, separated by commas. Example first line for 4 events: A, C, B, D
Then explain your reasoning briefly.

Chronological order:"""

_DURATION_PROMPT = """\
{question}

IMPORTANT: Your FIRST line must contain ONLY the integer answer (the number alone, \
no units, no other text). Then explain briefly on subsequent lines.

Answer:"""

_RELATIVE_TIME_PROMPT = """\
{question}

Choose the single best answer:
{choices_text}

IMPORTANT: Write just the letter (A, B, C, …) on the VERY FIRST LINE. \
Then explain briefly.

Answer:"""

_TIMELINE_PROMPT = """\
Consider the following sequence of events:

{scenario}

Describe the events in chronological order and analyse what this timeline \
suggests about the underlying situation or trajectory."""


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

    # ------------------------------------------------------------------
    # Tier 1: event ordering (deterministic letter-sequence extraction)
    # ------------------------------------------------------------------

    @keyword("Check Event Order")
    def check_event_order(
        self,
        events: Dict[str, str],
        expected_order: str,
    ) -> Dict[str, Any]:
        """Ask the LLM to sort labeled events chronologically and verify.

        Args:
            events: Mapping of label → description, e.g.
                    ``{"A": "Moon landing (1969)", "B": "WW2 ends (1945)"}``.
            expected_order: Space- or comma-separated labels in the correct
                            chronological order, e.g. ``"B A C D"``.

        Returns:
            Dict with keys: order (str|None), correct (bool), response (str),
            expected (str).
        """
        labels = sorted(events.keys())
        n = len(labels)
        events_text = "\n".join(f"{lbl}) {events[lbl]}" for lbl in labels)
        labels_str = ", ".join(labels)

        prompt = _ORDER_PROMPT.format(
            n=n,
            labels=labels_str,
            events_text=events_text,
        )
        logger.info(f"Event order prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        extracted = _extract_order_letters(response, n)
        order_str = " ".join(extracted) if extracted is not None else None

        # Normalise expected: strip commas/extra spaces, uppercase, join with spaces
        normalised_expected = " ".join(
            re.sub(r"[^A-Za-z]", " ", expected_order).upper().split()
        )

        correct = order_str == normalised_expected

        emit_rfc_data("expected_order", normalised_expected)
        emit_rfc_data("actual_order", order_str or "UNKNOWN")
        emit_rfc_data("correct", str(correct))

        return {
            "order": order_str,
            "correct": correct,
            "response": response,
            "expected": normalised_expected,
        }

    # ------------------------------------------------------------------
    # Tier 1: duration arithmetic (exact integer extraction)
    # ------------------------------------------------------------------

    @keyword("Check Duration Answer")
    def check_duration_answer(
        self,
        question: str,
        expected_days: int,
        tolerance: int = 0,
    ) -> Dict[str, Any]:
        """Ask the LLM a duration/date-arithmetic question and verify the answer.

        The question should have a single integer answer (days, weeks, hours,
        etc.).  The LLM is instructed to place only that integer on its first
        line so extraction is deterministic.

        Args:
            question: The arithmetic question, e.g.
                      "How many days between Jan 1 and Mar 1 in a non-leap year?".
            expected_days: The correct integer answer.
            tolerance: Accepted absolute difference (default 0 = exact match).

        Returns:
            Dict with keys: answer (int|None), correct (bool), response (str),
            expected (int).
        """
        prompt = _DURATION_PROMPT.format(question=question)
        logger.info(f"Duration prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        answer = _extract_first_integer(response)
        expected_days = int(expected_days)
        tolerance = int(tolerance)

        if answer is not None:
            correct = abs(answer - expected_days) <= tolerance
        else:
            correct = False

        emit_rfc_data("question", question[:200])
        emit_rfc_data("expected_days", str(expected_days))
        emit_rfc_data("actual_answer", str(answer) if answer is not None else "UNKNOWN")
        emit_rfc_data("tolerance", str(tolerance))
        emit_rfc_data("correct", str(correct))

        return {
            "answer": answer,
            "correct": correct,
            "response": response,
            "expected": expected_days,
        }

    # ------------------------------------------------------------------
    # Tier 1: relative time / multiple-choice (letter extraction)
    # ------------------------------------------------------------------

    @keyword("Check Relative Time")
    def check_relative_time(
        self,
        question: str,
        choices: List[str],
        expected_letter: str,
    ) -> Dict[str, Any]:
        """Ask the LLM a multiple-choice relative-time question and verify.

        Args:
            question: The temporal question to pose.
            choices: List of answer strings, e.g. ``["A) John first", "B) Sarah first"]``.
            expected_letter: The correct answer letter (A, B, C, …).

        Returns:
            Dict with keys: chosen_letter (str|None), correct (bool),
            response (str), expected (str).

        Raises:
            ValueError: If expected_letter is empty or not a single letter A–Z.
        """
        expected_letter = expected_letter.strip().upper()
        # Derive valid letters from the first character of each choice label
        valid_letters = {
            c.strip()[0].upper()
            for c in choices
            if c.strip() and c.strip()[0].isalpha()
        }
        if expected_letter not in valid_letters:
            raise ValueError(
                f"expected_letter must be one of {sorted(valid_letters)}, "
                f"got {expected_letter!r}"
            )

        choices_text = "\n".join(choices)
        prompt = _RELATIVE_TIME_PROMPT.format(
            question=question, choices_text=choices_text
        )
        logger.info(f"Relative time prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        chosen = _extract_letter(response)
        correct = chosen == expected_letter

        emit_rfc_data("question", question[:200])
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
    # Tier 2: LLM-graded timeline reasoning
    # ------------------------------------------------------------------

    @keyword("Grade Timeline Reasoning")
    def grade_timeline_reasoning(
        self,
        scenario: str,
        expected_elements: str,
        min_score: float = 0.5,
    ) -> Dict[str, Any]:
        """Ask the LLM to analyse a multi-step timeline and grade the response.

        Args:
            scenario: A description of events in a timeline (may be ordered or
                      deliberately scrambled to test the LLM's sequencing).
            expected_elements: Key ideas a correct analysis should mention.
            min_score: Minimum passing score (0.0–1.0).

        Returns:
            Dict with keys: score (float), reason (str), response (str),
            passed (bool).
        """
        prompt = _TIMELINE_PROMPT.format(scenario=scenario)
        logger.info(f"Timeline prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        grade = self.grader.grade(scenario, expected_elements, response)
        passed = grade.score >= float(min_score)

        emit_rfc_data("scenario", scenario[:200])
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


def _extract_order_letters(text: str, n: int) -> Optional[List[str]]:
    """Extract exactly n unique event-label letters from the first non-empty line.

    Handles formats like "B, D, A, C", "B D A C", "B → D → A → C".
    Returns None when the first line does not contain exactly n unique letters
    from the expected set, so non-compliant responses fail rather than silently
    producing a wrong grade.
    """
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    found = [m.upper() for m in _ORDER_RE.findall(first_line)]
    unique = list(dict.fromkeys(found))  # deduplicate while preserving order
    if len(unique) != n:
        return None
    return unique


def _extract_first_integer(text: str) -> Optional[int]:
    """Extract the first integer from the first non-empty line of a response."""
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    m = _INT_RE.search(first_line)
    if m:
        return int(m.group(1))
    return None


def _extract_letter(text: str) -> Optional[str]:
    """Extract the first letter from the first non-empty line of a response.

    The prompt instructs the model to place only its answer letter on the
    first line.  Searching the full body risks picking up option labels in
    the quoted choices.
    """
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    m = _LETTER_RE.search(first_line)
    if m:
        return m.group(1).upper()
    return None
