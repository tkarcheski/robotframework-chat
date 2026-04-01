"""Robot Framework keywords for validating LLM output format compliance.

Provides keywords to validate structured output (JSON, YAML, CSV),
count sentences and words, and check for forbidden words in responses.
All keywords emit RFC_DATA for database capture.
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

import yaml
from robot.api.deco import keyword

from .rfc_data import emit_rfc_data

# Common abbreviations that should not be treated as sentence endings.
_ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs",
                  "etc", "inc", "ltd", "corp", "approx", "e.g", "i.e"}

# Splits on sentence-ending punctuation followed by whitespace or end of string.
_SENTENCE_SPLIT = re.compile(r"[.!?](?:\s|$)")

# Markdown code-fence pattern for extracting content.
_CODE_FENCE = re.compile(r"```\w*\s*\n?(.*?)```", re.DOTALL)


def _strip_code_fences(text: str) -> str:
    """Extract content from markdown code fences if present."""
    match = _CODE_FENCE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def _parse_expected_keys(expected_keys: str) -> list[str]:
    """Split comma-separated key string, stripping whitespace."""
    return [k.strip() for k in expected_keys.split(",") if k.strip()]


def _compute_key_score(
    parsed: dict[str, Any], expected: list[str]
) -> tuple[float, list[str]]:
    """Compute partial-credit score based on key presence.

    Returns (score, missing_keys) where score ranges from 0.0 to 1.0.
    Parse credit (0.5) + key fraction credit (0.5 * keys_found/keys_expected).
    """
    if not expected:
        return 1.0, []
    present = [k for k in expected if k in parsed]
    missing = [k for k in expected if k not in parsed]
    key_ratio = len(present) / len(expected)
    score = 0.5 + 0.5 * key_ratio
    return score, missing


class FormatKeywords:
    """Keywords for validating LLM output format compliance."""

    @keyword("Validate JSON Response")
    def validate_json_response(
        self, response: str, expected_keys: str
    ) -> float:
        """Parse JSON from response and validate expected keys.

        Supports JSON objects and arrays (validates keys of first element).
        Extracts JSON from markdown code fences if present.

        Args:
            response: Raw LLM response that should contain JSON.
            expected_keys: Comma-separated list of expected keys.

        Returns:
            Score from 0.0 to 1.0. Partial credit: 0.5 for valid parse
            but missing keys, 1.0 for all keys present.
        """
        keys = _parse_expected_keys(expected_keys)
        text = _strip_code_fences(response)
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            emit_rfc_data("score", "0.0000")
            emit_rfc_data("parse_valid", "false")
            emit_rfc_data("missing_keys", ",".join(keys))
            return 0.0

        emit_rfc_data("parse_valid", "true")

        # For arrays, validate against first element
        target: dict[str, Any]
        if isinstance(parsed, list):
            if not parsed or not isinstance(parsed[0], dict):
                score = 0.5  # Valid JSON array but no dict elements
                emit_rfc_data("score", f"{score:.4f}")
                emit_rfc_data("missing_keys", ",".join(keys))
                return score
            target = parsed[0]
        elif isinstance(parsed, dict):
            target = parsed
        else:
            score = 0.5  # Valid JSON but not a dict/list
            emit_rfc_data("score", f"{score:.4f}")
            emit_rfc_data("missing_keys", ",".join(keys))
            return score

        score, missing = _compute_key_score(target, keys)
        emit_rfc_data("score", f"{score:.4f}")
        emit_rfc_data("missing_keys", ",".join(missing))
        return score

    @keyword("Validate YAML Response")
    def validate_yaml_response(
        self, response: str, expected_keys: str
    ) -> float:
        """Parse YAML from response and validate expected keys.

        Args:
            response: Raw LLM response that should contain YAML.
            expected_keys: Comma-separated list of expected top-level keys.

        Returns:
            Score from 0.0 to 1.0.
        """
        keys = _parse_expected_keys(expected_keys)
        text = _strip_code_fences(response)
        try:
            parsed = yaml.safe_load(text)
        except yaml.YAMLError:
            emit_rfc_data("score", "0.0000")
            emit_rfc_data("parse_valid", "false")
            emit_rfc_data("missing_keys", ",".join(keys))
            return 0.0

        if not isinstance(parsed, dict):
            emit_rfc_data("score", "0.0000")
            emit_rfc_data("parse_valid", "false")
            emit_rfc_data("missing_keys", ",".join(keys))
            return 0.0

        emit_rfc_data("parse_valid", "true")
        score, missing = _compute_key_score(parsed, keys)
        emit_rfc_data("score", f"{score:.4f}")
        emit_rfc_data("missing_keys", ",".join(missing))
        return score

    @keyword("Validate CSV Response")
    def validate_csv_response(
        self,
        response: str,
        expected_columns: int,
        min_rows: int = 1,
    ) -> float:
        """Parse CSV from response and validate structure.

        Args:
            response: Raw LLM response that should contain CSV.
            expected_columns: Expected number of columns.
            min_rows: Minimum number of data rows (excluding header).

        Returns:
            Score from 0.0 to 1.0. Partial credit for parseable but
            wrong structure.
        """
        expected_columns = int(expected_columns)
        min_rows = int(min_rows)
        text = _strip_code_fences(response)

        if not text.strip():
            emit_rfc_data("score", "0.0000")
            emit_rfc_data("parse_valid", "false")
            emit_rfc_data("actual_columns", "0")
            emit_rfc_data("actual_rows", "0")
            return 0.0

        try:
            reader = csv.reader(io.StringIO(text))
            rows = list(reader)
        except csv.Error:
            emit_rfc_data("score", "0.0000")
            emit_rfc_data("parse_valid", "false")
            emit_rfc_data("actual_columns", "0")
            emit_rfc_data("actual_rows", "0")
            return 0.0

        if not rows:
            emit_rfc_data("score", "0.0000")
            emit_rfc_data("parse_valid", "false")
            emit_rfc_data("actual_columns", "0")
            emit_rfc_data("actual_rows", "0")
            return 0.0

        emit_rfc_data("parse_valid", "true")

        # Header is first row; data rows are the rest
        actual_columns = len(rows[0])
        data_rows = len(rows) - 1  # exclude header

        emit_rfc_data("actual_columns", str(actual_columns))
        emit_rfc_data("actual_rows", str(data_rows))

        # Score: 0.5 for parseable, +0.25 for column match, +0.25 for row match
        score = 0.5
        if actual_columns == expected_columns:
            score += 0.25
        if data_rows >= min_rows:
            score += 0.25

        # Full score only when both match
        if actual_columns == expected_columns and data_rows >= min_rows:
            score = 1.0

        emit_rfc_data("score", f"{score:.4f}")
        return score

    @keyword("Count Sentences")
    def count_sentences(self, text: str) -> int:
        """Count sentences in text using punctuation splitting.

        Handles common abbreviations (Mr., Dr., etc.) to avoid
        false splits. Text without trailing punctuation counts as
        one sentence if non-empty.

        Args:
            text: Text to count sentences in.

        Returns:
            Number of sentences (0 for empty text).
        """
        if not text or not text.strip():
            emit_rfc_data("sentence_count", "0")
            return 0

        # Find all positions where sentence-ending punctuation occurs
        count = 0
        for match in _SENTENCE_SPLIT.finditer(text):
            pos = match.start()
            # Check if the period is preceded by an abbreviation
            prefix = text[:pos].rstrip()
            last_word = prefix.split()[-1].lower().rstrip(".") if prefix.split() else ""
            if text[pos] == "." and last_word in _ABBREVIATIONS:
                continue
            count += 1

        # If text has content but no sentence-ending punctuation, count as 1
        if count == 0 and text.strip():
            count = 1

        emit_rfc_data("sentence_count", str(count))
        return count

    @keyword("Count Words")
    def count_words(self, text: str) -> int:
        """Count words in text using whitespace splitting.

        Args:
            text: Text to count words in.

        Returns:
            Word count (0 for empty or whitespace-only text).
        """
        if not text or not text.strip():
            emit_rfc_data("word_count", "0")
            return 0
        count = len(text.split())
        emit_rfc_data("word_count", str(count))
        return count

    @keyword("Check Forbidden Words")
    def check_forbidden_words(
        self, response: str, forbidden_words: str
    ) -> list[str]:
        """Check for forbidden words in response using word-boundary matching.

        Case-insensitive. Uses ``\\b`` word boundaries to avoid matching
        substrings (e.g. 'show' does not match forbidden word 'how').

        Args:
            response: LLM response text to check.
            forbidden_words: Comma-separated list of forbidden words.

        Returns:
            List of forbidden words found (empty if none).
        """
        words = _parse_expected_keys(forbidden_words)
        if not words or not response:
            emit_rfc_data("violations", "")
            emit_rfc_data("violation_count", "0")
            return []

        violations: list[str] = []
        for word in words:
            pattern = rf"\b{re.escape(word)}\b"
            if re.search(pattern, response, re.IGNORECASE):
                violations.append(word)

        emit_rfc_data("violations", ",".join(violations))
        emit_rfc_data("violation_count", str(len(violations)))
        return violations
