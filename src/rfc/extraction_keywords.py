"""Robot Framework keywords for LLM information extraction tests."""

import re
from typing import Any, Dict, List, Optional, Tuple

from robot.api import logger
from robot.api.deco import keyword

from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data
from .thinking import parse_thinking


class ExtractionKeywords:
    """Keywords for testing LLM information extraction accuracy.

    Grades deterministically by checking whether expected entities or
    values appear in the LLM response (Tier 1 — no secondary LLM grader).
    """

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(self, timeout: Optional[int] = None, max_retries: int = 2) -> None:
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _recall(
        self, response: str, expected: List[str]
    ) -> Tuple[float, List[str], List[str]]:
        """Return (recall_score, found_list, missing_list) for *expected* items."""
        response_lower = response.lower()
        found = [e for e in expected if e.lower() in response_lower]
        missing = [e for e in expected if e.lower() not in response_lower]
        score = len(found) / len(expected) if expected else 0.0
        return score, found, missing

    @staticmethod
    def _strip_commas(value: str) -> str:
        """Remove comma thousand-separators for numeric comparison."""
        return re.sub(r"(?<=\d),(?=\d{3})", "", value)

    # ------------------------------------------------------------------
    # Public keywords
    # ------------------------------------------------------------------

    @keyword("Ask And Extract Named Entities")
    def ask_and_extract_named_entities(
        self,
        context: str,
        expected_entities: List[str],
        entity_type: str = "person",
        min_score: float = 1.0,
    ) -> Dict[str, Any]:
        """Ask the LLM to extract named entities from text and check recall.

        The LLM is asked to list all entities of *entity_type* found in
        *context*.  The grade is the fraction of *expected_entities* that
        appear anywhere in the response.

        Args:
            context: Source text to extract entities from.
            expected_entities: Entities that must appear in the response.
            entity_type: Label used in the prompt (``person``, ``organization``, …).
            min_score: Minimum recall required to pass (0.0–1.0).

        Returns:
            Dict with ``score``, ``found``, ``missing``, ``passed``.
        """
        prompt = (
            f"Extract all {entity_type} names from the text below. "
            f"List each name on its own line. Do not add commentary.\n\n"
            f"Text:\n{context}"
        )
        logger.info(f"Entity extraction ({entity_type}): {context[:120]}")
        raw = self.client.generate(prompt)
        clean, _ = parse_thinking(raw, strip_unclosed=True)
        emit_rfc_data("actual_answer", clean[:800])

        score, found, missing = self._recall(clean, expected_entities)
        passed = score >= min_score
        reason = (
            f"recall={score:.2f} ({len(found)}/{len(expected_entities)}), "
            f"found={found}, missing={missing}"
        )
        emit_rfc_data("score", f"{score:.2f}")
        emit_rfc_data("expected_answer", ", ".join(expected_entities))
        emit_rfc_data("grading_reason", reason)
        logger.info(f"Entity extraction grading: {reason}")
        return {"score": score, "found": found, "missing": missing, "passed": passed}

    @keyword("Ask And Extract Numeric Fact")
    def ask_and_extract_numeric_fact(
        self,
        context: str,
        question: str,
        expected_value: str,
    ) -> Dict[str, Any]:
        """Ask the LLM to find a specific numeric fact inside a passage.

        The expected value is compared after stripping units and
        comma thousand-separators so ``1,234`` matches ``1234``.

        Args:
            context: Text passage that contains the numeric fact.
            question: Specific question to answer from the passage.
            expected_value: Correct numeric value as a string.

        Returns:
            Dict with ``passed``, ``actual_value``, ``reason``.
        """
        prompt = (
            f"Read the following text, then answer the question.\n\n"
            f"Text:\n{context}\n\n"
            f"Question: {question}\n\n"
            f"Answer with only the number. No units, no explanation."
        )
        logger.info(f"Numeric extraction: {question[:120]}")
        raw = self.client.generate(prompt)
        clean, _ = parse_thinking(raw, strip_unclosed=True)
        emit_rfc_data("actual_answer", clean[:200])

        # Normalise: strip non-numeric characters except . and -, then trim
        # leading/trailing dots that are punctuation rather than decimals.
        actual_norm = re.sub(r"[^\d.\-]", "", clean.strip()).strip(".")
        # Remove comma thousands-separators
        actual_no_comma = self._strip_commas(actual_norm)
        expected_norm = re.sub(r"[^\d.\-]", "", expected_value.strip()).strip(".")
        expected_no_comma = self._strip_commas(expected_norm)

        passed = actual_no_comma == expected_no_comma or actual_norm == expected_norm
        reason = f"actual={actual_norm!r}, expected={expected_norm!r}"
        emit_rfc_data("score", str(1 if passed else 0))
        emit_rfc_data("expected_answer", expected_value)
        emit_rfc_data("grading_reason", reason)
        logger.info(f"Numeric extraction grading: {reason}, passed={passed}")
        return {"passed": passed, "actual_value": actual_norm, "reason": reason}

    @keyword("Ask And Extract Key Value Pairs")
    def ask_and_extract_key_value_pairs(
        self,
        context: str,
        expected_pairs: List[str],
        min_score: float = 1.0,
    ) -> Dict[str, Any]:
        """Ask the LLM to extract specific key:value pairs from text.

        Each element of *expected_pairs* is a short string that must appear
        verbatim (case-insensitive) in the LLM response — e.g.
        ``"CEO: Alice Johnson"`` or ``"founded: 1994"``.

        Args:
            context: Source text.
            expected_pairs: Strings that must appear in the response.
            min_score: Minimum fraction to pass.

        Returns:
            Dict with ``score``, ``found``, ``missing``, ``passed``.
        """
        prompt = (
            f"Extract all factual key-value pairs from the text below. "
            f"Format each as 'Key: Value' on its own line.\n\n"
            f"Text:\n{context}"
        )
        logger.info(f"Key-value extraction: {context[:120]}")
        raw = self.client.generate(prompt)
        clean, _ = parse_thinking(raw, strip_unclosed=True)
        emit_rfc_data("actual_answer", clean[:800])

        score, found, missing = self._recall(clean, expected_pairs)
        passed = score >= min_score
        reason = (
            f"recall={score:.2f} ({len(found)}/{len(expected_pairs)}), "
            f"found={found}, missing={missing}"
        )
        emit_rfc_data("score", f"{score:.2f}")
        emit_rfc_data("expected_answer", ", ".join(expected_pairs))
        emit_rfc_data("grading_reason", reason)
        logger.info(f"Key-value extraction grading: {reason}")
        return {"score": score, "found": found, "missing": missing, "passed": passed}

    @keyword("Assert Extraction Passed")
    def assert_extraction_passed(
        self, result: Dict[str, Any], label: str = "extraction"
    ) -> None:
        """Assert that an extraction result has ``passed=True``.

        Args:
            result: Dict returned by an ``Ask And Extract *`` keyword.
            label: Human-readable label for the error message.

        Raises:
            AssertionError: If ``result['passed']`` is falsy.
        """
        if not result.get("passed"):
            raise AssertionError(
                f"{label} failed: {result.get('reason', 'no reason')}"
            )
