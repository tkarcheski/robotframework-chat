"""IFEval (Instruction Following Evaluation) keyword library.

Deterministic constraint checkers for verifying that LLM responses
follow strict formatting and structural instructions.  All checks
are pure Python — no LLM judge is involved in grading.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from robot.api.deco import keyword  # type: ignore[import-untyped]

from .llm_client import LLMProvider, create_provider, resolve_timeout
from .rfc_data import emit_rfc_data
from .thinking import parse_thinking

# Regex for splitting text into sentences on sentence-ending punctuation.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# Regex for detecting bullet-point lines (dash, asterisk, or unicode bullet).
_BULLET_PATTERN = re.compile(r"^\s*[-*\u2022]\s+")

# Regex for detecting numbered-list lines like "1." or "1)".
_NUMBERED_PATTERN = re.compile(r"^\s*(\d+)[.)]\s+")


class IFEvalKeywords:
    """Robot Framework keyword library for instruction-following evaluation.

    All constraint checks are static methods (pure functions) so they can be
    unit-tested without mocking.  The high-level keywords combine an LLM call
    with constraint verification and structured data emission.
    """

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_retries: int = 2,
    ) -> None:
        resolved = resolve_timeout(timeout)
        self.client: LLMProvider = create_provider(
            timeout=resolved, max_retries=int(max_retries)
        )

    # ------------------------------------------------------------------
    # High-level Robot keywords
    # ------------------------------------------------------------------

    @keyword("Ask And Check Constraint")
    def ask_and_check_constraint(
        self,
        prompt: str,
        constraint: str,
        expected_value: str = "",
    ) -> Dict[str, Any]:
        """Send *prompt* to the LLM, then verify *constraint* on the response.

        Strips ``<think>`` tags before checking.  Emits RFC_DATA for the
        database listener.

        Returns a result dict with keys ``passed``, ``constraint``,
        ``reason``, and ``response``.
        """
        raw_response = self.client.generate(prompt)
        answer, _ = parse_thinking(raw_response, strip_unclosed=True)
        answer = answer.strip()

        result = self.check_ifeval_constraint(answer, constraint, expected_value)

        emit_rfc_data("actual_answer", answer)
        emit_rfc_data("score", "1" if result["passed"] else "0")
        emit_rfc_data(
            "expected_answer", f"constraint:{constraint}={expected_value or 'true'}"
        )
        emit_rfc_data("grading_reason", result["reason"])

        return result

    @keyword("Check IFEval Constraint")
    def check_ifeval_constraint(
        self,
        response: str,
        constraint: str,
        expected_value: str = "",
    ) -> Dict[str, Any]:
        """Check a single *constraint* against *response*.

        The *expected_value* is interpreted per-constraint (e.g. an integer
        for ``sentence_count``, a letter for ``forbidden_letter``).

        Returns:
            ``{"passed": bool, "constraint": str, "reason": str,
              "response": str}``

        Raises:
            ValueError: If *constraint* is not recognised.
        """
        dispatch: Dict[str, Any] = {
            "sentence_count": lambda: self.check_sentence_count(
                response, int(expected_value)
            ),
            "all_caps": lambda: self.check_all_caps(response),
            "bullet_points": lambda: self.check_bullet_points(
                response, int(expected_value)
            ),
            "word_count": lambda: self.check_word_count(
                response, int(expected_value)
            ),
            "numbered_list": lambda: self.check_numbered_list(
                response, int(expected_value)
            ),
            "paragraph_count": lambda: self.check_paragraph_count(
                response, int(expected_value)
            ),
            "forbidden_letter": lambda: self.check_forbidden_letter(
                response, expected_value
            ),
            "sentence_start": lambda: self.check_sentence_start(
                response, expected_value
            ),
            "ends_with_word": lambda: self.check_ends_with_word(
                response, expected_value
            ),
            "all_lowercase": lambda: self.check_all_lowercase(response),
            "no_digits": lambda: self.check_no_digits(response),
        }

        if constraint not in dispatch:
            raise ValueError(
                f"Unknown constraint: {constraint!r}.  "
                f"Supported: {sorted(dispatch)}"
            )

        passed, reason = dispatch[constraint]()
        return {
            "passed": passed,
            "constraint": constraint,
            "reason": reason,
            "response": response,
        }

    @keyword("Assert IFEval Passed")
    def assert_ifeval_passed(self, result: Dict[str, Any]) -> None:
        """Raise ``AssertionError`` if the constraint check failed."""
        if not result["passed"]:
            raise AssertionError(
                f"IFEval constraint {result['constraint']!r} failed: "
                f"{result['reason']}"
            )

    # ------------------------------------------------------------------
    # Static constraint checkers — pure functions
    # ------------------------------------------------------------------

    @staticmethod
    def check_sentence_count(response: str, expected: int) -> Tuple[bool, str]:
        """Check that *response* contains exactly *expected* sentences."""
        text = response.strip()
        if not text:
            return False, f"Expected {expected} sentences, found 0 (empty response)"
        sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
        actual = len(sentences)
        if actual == expected:
            return True, f"Found {actual} sentences as expected"
        return False, f"Expected {expected} sentences, found {actual}"

    @staticmethod
    def check_all_caps(response: str) -> Tuple[bool, str]:
        """Check that every alphabetic character is uppercase."""
        alpha = [c for c in response if c.isalpha()]
        if not alpha:
            return True, "No alphabetic characters to check"
        if all(c.isupper() for c in alpha):
            return True, "All alphabetic characters are uppercase"
        return False, "Response contains lowercase alphabetic characters"

    @staticmethod
    def check_bullet_points(response: str, expected: int) -> Tuple[bool, str]:
        """Check that all non-empty lines are bullet points and count matches."""
        lines = [ln for ln in response.split("\n") if ln.strip()]
        non_bullet = [ln for ln in lines if not _BULLET_PATTERN.match(ln)]
        if non_bullet:
            return False, (
                f"Non-bullet line(s) found: {non_bullet[0]!r}"
            )
        actual = len(lines)
        if actual == expected:
            return True, f"Found {actual} bullet points as expected"
        return False, f"Expected {expected} bullet points, found {actual}"

    @staticmethod
    def check_word_count(response: str, expected: int) -> Tuple[bool, str]:
        """Check that *response* contains exactly *expected* words."""
        words = response.strip().split()
        actual = len(words)
        if actual == expected:
            return True, f"Found {actual} words as expected"
        return False, f"Expected {expected} words, found {actual}"

    @staticmethod
    def check_numbered_list(response: str, expected: int) -> Tuple[bool, str]:
        """Check that *response* is a numbered list 1..*expected*."""
        lines = [ln for ln in response.split("\n") if ln.strip()]
        numbers: list[int] = []
        for ln in lines:
            m = _NUMBERED_PATTERN.match(ln)
            if not m:
                return False, f"Non-numbered line found: {ln!r}"
            numbers.append(int(m.group(1)))
        if len(numbers) != expected:
            return False, (
                f"Expected {expected} numbered items, found {len(numbers)}"
            )
        expected_seq = list(range(1, expected + 1))
        if numbers != expected_seq:
            return False, (
                f"Expected sequence {expected_seq}, got {numbers}"
            )
        return True, f"Found numbered list 1..{expected} as expected"

    @staticmethod
    def check_paragraph_count(response: str, expected: int) -> Tuple[bool, str]:
        """Check that *response* contains exactly *expected* paragraphs."""
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", response) if p.strip()]
        actual = len(paragraphs)
        if actual == expected:
            return True, f"Found {actual} paragraphs as expected"
        return False, f"Expected {expected} paragraphs, found {actual}"

    @staticmethod
    def check_forbidden_letter(response: str, letter: str) -> Tuple[bool, str]:
        """Check that *letter* does not appear in *response* (case-insensitive)."""
        if letter.lower() in response.lower():
            return False, f"Forbidden letter {letter!r} found in response"
        return True, f"Letter {letter!r} not found in response"

    @staticmethod
    def check_sentence_start(response: str, word: str) -> Tuple[bool, str]:
        """Check that every sentence starts with *word* (case-sensitive)."""
        text = response.strip()
        if not text:
            return False, "Empty response"
        sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
        for i, sentence in enumerate(sentences, 1):
            if not sentence.startswith(word):
                return False, (
                    f"Sentence {i} starts with {sentence.split()[0]!r}, "
                    f"expected {word!r}"
                )
        return True, f"All {len(sentences)} sentences start with {word!r}"

    @staticmethod
    def check_ends_with_word(response: str, word: str) -> Tuple[bool, str]:
        """Check that the last word of *response* is *word*."""
        text = response.strip().rstrip(".,;:!?")
        if not text:
            return False, "Empty response"
        last_word = text.split()[-1]
        if last_word == word:
            return True, f"Response ends with {word!r} as expected"
        return False, f"Response ends with {last_word!r}, expected {word!r}"

    @staticmethod
    def check_all_lowercase(response: str) -> Tuple[bool, str]:
        """Check that every alphabetic character is lowercase."""
        alpha = [c for c in response if c.isalpha()]
        if not alpha:
            return True, "No alphabetic characters to check"
        if all(c.islower() for c in alpha):
            return True, "All alphabetic characters are lowercase"
        return False, "Response contains uppercase alphabetic characters"

    @staticmethod
    def check_no_digits(response: str) -> Tuple[bool, str]:
        """Check that *response* contains no digit characters."""
        if any(c.isdigit() for c in response):
            return False, "Response contains digit characters"
        return True, "No digits found in response"
