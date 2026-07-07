"""Information extraction evaluation keywords for Robot Framework.

Tests whether an LLM can accurately extract structured information
(named entities, key-value pairs) from unstructured text.  Verification
is deterministic Python string matching — Tier 1 / verify:python.
"""

import re
from typing import Any, Dict, List, Optional

from robot.api import logger
from robot.api.deco import keyword

from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data

_ENTITY_EXTRACTION_PROMPT = """\
Read the following text carefully and extract the requested information.

Text: {text}

Question: {question}

Respond with ONLY the extracted value — no explanation, no labels, no extra \
punctuation. If the information is not present in the text, respond with: NOT_FOUND

Answer:"""

_KEY_VALUE_PROMPT = """\
Read the following text and extract the value for the requested attribute.

Text: {text}

Attribute to extract: {attribute}

Rules:
- Reply with the extracted value only — no labels, no extra text.
- Include units if they appear in the text alongside the value.
- If the attribute is not present, reply with: NOT_FOUND

Value:"""

_MULTI_ENTITY_PROMPT = """\
Read the following text carefully and answer the question by listing all \
requested items, one per line.

Text: {text}

Question: {question}

List each item on its own line, with no numbering or extra punctuation."""


class ExtractionKeywords:
    """Robot Framework keywords for information extraction evaluation."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_retries: int = 2,
    ) -> None:
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))

    @keyword("Extract And Verify Entity")
    def extract_and_verify_entity(
        self,
        text: str,
        question: str,
        expected_value: str,
    ) -> Dict[str, Any]:
        """Ask the LLM to extract a specific entity from a text and verify it."""
        prompt = _ENTITY_EXTRACTION_PROMPT.format(text=text, question=question)
        logger.info(f"Entity extraction prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        extracted = _strip_label(response)
        # Match the parsed extraction, not the full response: searching the whole
        # body would match the expected token in explanatory prose and inflate the
        # pass rate.
        correct = _contains_value(extracted, expected_value)

        emit_rfc_data("question", question[:200])
        emit_rfc_data("expected", expected_value)
        emit_rfc_data("extracted", extracted[:200])
        emit_rfc_data("correct", str(correct))

        return {
            "extracted": extracted,
            "correct": correct,
            "response": response,
            "expected": expected_value,
        }

    @keyword("Extract Key Value And Verify")
    def extract_key_value_and_verify(
        self,
        text: str,
        attribute: str,
        expected_value: str,
    ) -> Dict[str, Any]:
        """Ask the LLM to extract a key-value attribute from a text."""
        prompt = _KEY_VALUE_PROMPT.format(text=text, attribute=attribute)
        logger.info(f"Key-value extraction prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        extracted = _strip_label(response)
        correct = _contains_value(extracted, expected_value)

        emit_rfc_data("attribute", attribute)
        emit_rfc_data("expected", expected_value)
        emit_rfc_data("extracted", extracted[:200])
        emit_rfc_data("correct", str(correct))

        return {
            "extracted": extracted,
            "correct": correct,
            "response": response,
            "expected": expected_value,
        }

    @keyword("Extract Multiple Entities And Verify")
    def extract_multiple_entities_and_verify(
        self,
        text: str,
        question: str,
        expected_values: List[str],
    ) -> Dict[str, Any]:
        """Ask the LLM to extract multiple entities and check all are present."""
        prompt = _MULTI_ENTITY_PROMPT.format(text=text, question=question)
        logger.info(f"Multi-entity extraction prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        # Check per-line, not whole-text: a substring search would match entities
        # appearing only in negated or explanatory prose ("Rust is not used here").
        found = [v for v in expected_values if _entity_in_lines(response, v)]
        missing = [v for v in expected_values if v not in found]
        correct = len(missing) == 0

        emit_rfc_data("question", question[:200])
        emit_rfc_data("expected_values", str(expected_values))
        emit_rfc_data("found", str(found))
        emit_rfc_data("missing", str(missing))
        emit_rfc_data("correct", str(correct))

        return {
            "found": found,
            "missing": missing,
            "correct": correct,
            "response": response,
            "expected": expected_values,
        }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

# Label prefix: a single alphabetic word (no spaces, no digits) followed by a
# colon and at least one space.  Restricting to single words prevents
# multi-word titles like "Star Wars: Episode IV" or "Chapter One: Arrival"
# from being corrupted.  The digit exclusion prevents "2:30 PM" from being
# stripped, and \s+ (not \s*) prevents "https://…" from matching.
_LABEL_RE = re.compile(r"^\s*[A-Za-z]+:\s+")
_LIST_MARKER_RE = re.compile(r"^\s*(?:\d+[.)]\s*|[-*•]\s*)")
# "no" is included with word-boundary anchoring so "No Rust mentioned" is
# excluded while "node", "normal", and "know" are not affected.
_NEGATION_RE = re.compile(r"\b(?:no|not|never|absent|without)\b")


def _strip_label(text: str) -> str:
    """Return the first non-empty line with any leading 'Label: ' prefix removed."""
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    cleaned = _LABEL_RE.sub("", first_line)
    return cleaned.strip() or first_line.strip()


def _contains_value(text: str, expected: str) -> bool:
    """Case-insensitive substring check with numeric comma-normalisation.

    Both *text* and *expected* have commas stripped from digit sequences
    before comparison so that "2,847" matches "2847" and vice versa.
    """
    if not text or not expected:
        return False
    norm_text = _normalise_numbers(text).lower()
    norm_expected = _normalise_numbers(expected).lower()
    return norm_expected in norm_text


def _entity_in_lines(response: str, entity: str) -> bool:
    """Check whether *entity* appears on any non-negated line of *response*.

    Each line is stripped of list markers, then lines carrying a negation word
    ("not", "never", "absent", "no") are excluded so ``"Rust is not mentioned"``
    is not a positive hit for ``"Rust"``.
    """
    if not response or not entity:
        return False
    norm_entity = _normalise_numbers(entity).lower()
    for raw_line in response.splitlines():
        line = _LIST_MARKER_RE.sub("", raw_line).strip()
        if not line:
            continue
        norm_line = _normalise_numbers(line).lower()
        if norm_entity not in norm_line:
            continue
        if _NEGATION_RE.search(norm_line):
            continue
        return True
    return False


def _normalise_numbers(text: str) -> str:
    """Remove commas that appear inside digit sequences (e.g. 2,847 → 2847)."""
    return re.sub(r"(\d),(\d)", r"\1\2", text)
