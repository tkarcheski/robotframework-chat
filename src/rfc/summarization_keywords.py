"""Robot Framework keywords for grading LLM summarization quality.

Summarization is graded deterministically (Tier 1, verify:python) by three
signals: keyword coverage (did the summary retain the required key facts?),
forbidden-fact violations (did the summary fabricate or include disallowed
content?), and length compliance (did the summary respect the requested
word range?). All graders use word-boundary regex matching so substrings
like ``cat`` do not falsely match ``catalog``.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from robot.api import logger
from robot.api.deco import keyword

from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data
from .thinking import parse_thinking

_FORBIDDEN_PENALTY = 0.3
_LENGTH_PENALTY = 0.7
_PASS_COVERAGE_THRESHOLD = 0.7


def _phrase_to_pattern(phrase: str) -> str:
    """Convert a phrase like 'Apollo 11' into a word-boundary regex."""
    cleaned = phrase.strip()
    if not cleaned:
        return ""
    # Treat internal whitespace as flexible whitespace; escape the rest.
    tokens = [re.escape(tok) for tok in cleaned.split()]
    return r"\b" + r"\s+".join(tokens) + r"\b"


def _group_to_pattern(group: str) -> Optional[re.Pattern[str]]:
    """Convert ``'CEO|chief executive'`` into a compiled alternation regex."""
    alternatives = [alt.strip() for alt in group.split("|") if alt.strip()]
    patterns = [_phrase_to_pattern(alt) for alt in alternatives]
    patterns = [p for p in patterns if p]
    if not patterns:
        return None
    return re.compile("|".join(patterns), re.IGNORECASE)


class SummarizationKeywords:
    """Robot Framework keywords for grading summarization output."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(self, timeout: Optional[int] = None, max_retries: int = 2):
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))

    @keyword("Check Keyword Coverage")
    def check_keyword_coverage(
        self, text: str, keyword_groups: list[str]
    ) -> tuple[float, list[str]]:
        """Score how many keyword groups are present in ``text``.

        Each group is a string; alternatives within a group are separated by
        ``|`` (e.g. ``'CEO|chief executive'``). A group counts as matched if
        any alternative appears as a whole-word match (case-insensitive).

        Args:
            text: Text to inspect (typically an LLM-generated summary).
            keyword_groups: List of required keyword groups.

        Returns:
            ``(coverage_score, missing_groups)`` where ``coverage_score`` is
            in [0.0, 1.0] and ``missing_groups`` lists every input group that
            failed to match.
        """
        if not keyword_groups:
            return 1.0, []
        if not text:
            return 0.0, list(keyword_groups)

        missing: list[str] = []
        matched = 0
        for group in keyword_groups:
            pattern = _group_to_pattern(group)
            if pattern is None:
                # An empty group is vacuously present — skip it from scoring.
                continue
            if pattern.search(text):
                matched += 1
            else:
                missing.append(group)

        scorable = len(keyword_groups) - sum(
            1 for g in keyword_groups if _group_to_pattern(g) is None
        )
        if scorable == 0:
            return 1.0, []
        coverage = matched / scorable
        return coverage, missing

    @keyword("Check Forbidden Facts")
    def check_forbidden_facts(self, text: str, forbidden_facts: list[str]) -> list[str]:
        """Return forbidden phrases that appear in ``text`` as whole words.

        Matching is case-insensitive and uses word boundaries so ``die``
        does not falsely match ``died``.
        """
        if not text or not forbidden_facts:
            return []
        violations: list[str] = []
        for phrase in forbidden_facts:
            pattern = _group_to_pattern(phrase)
            if pattern is None:
                continue
            if pattern.search(text):
                violations.append(phrase)
        return violations

    @keyword("Check Length Compliance")
    def check_length_compliance(
        self, text: str, min_words: int, max_words: int
    ) -> dict[str, Any]:
        """Check that ``text`` falls within ``[min_words, max_words]``."""
        min_words = int(min_words)
        max_words = int(max_words)
        word_count = len(text.split()) if text else 0
        within_bounds = min_words <= word_count <= max_words
        return {
            "word_count": word_count,
            "within_bounds": within_bounds,
            "min_words": min_words,
            "max_words": max_words,
        }

    @keyword("Score Summary")
    def score_summary(
        self,
        summary: str,
        required_keywords: list[str],
        forbidden_facts: list[str],
        min_words: int,
        max_words: int,
    ) -> dict[str, Any]:
        """Grade a summary on coverage, forbidden facts, and length.

        Returns a dict with:
          - ``coverage_score``: fraction of required keyword groups present
          - ``missing_keywords``: groups not found in the summary
          - ``forbidden_found``: forbidden phrases that appeared
          - ``length_ok``: whether word count is within bounds
          - ``word_count``: number of whitespace-delimited tokens
          - ``total_score``: penalised aggregate in [0.0, 1.0]
          - ``pass``: True iff coverage >= threshold AND no forbidden AND length_ok

        Forbidden hits multiply the score by ``_FORBIDDEN_PENALTY`` (0.3) and
        length violations multiply by ``_LENGTH_PENALTY`` (0.7), so a clean
        full-coverage summary scores 1.0.
        """
        coverage, missing = self.check_keyword_coverage(summary, required_keywords)
        forbidden_found = self.check_forbidden_facts(summary, forbidden_facts)
        length = self.check_length_compliance(summary, min_words, max_words)

        total = coverage
        if forbidden_found:
            total *= _FORBIDDEN_PENALTY
        if not length["within_bounds"]:
            total *= _LENGTH_PENALTY

        passed = (
            coverage >= _PASS_COVERAGE_THRESHOLD
            and not forbidden_found
            and length["within_bounds"]
        )

        emit_rfc_data("score", f"{total:.4f}")
        emit_rfc_data("coverage_score", f"{coverage:.4f}")
        emit_rfc_data("word_count", str(length["word_count"]))
        emit_rfc_data("length_ok", "true" if length["within_bounds"] else "false")
        emit_rfc_data("missing_keywords", ", ".join(missing))
        emit_rfc_data("forbidden_found", ", ".join(forbidden_found))
        emit_rfc_data("pass", "true" if passed else "false")

        logger.info(
            f"Summary grading: coverage={coverage:.2f}, "
            f"forbidden={forbidden_found}, length_ok={length['within_bounds']}, "
            f"total={total:.2f}, pass={passed}"
        )

        return {
            "coverage_score": coverage,
            "missing_keywords": missing,
            "forbidden_found": forbidden_found,
            "length_ok": length["within_bounds"],
            "word_count": length["word_count"],
            "total_score": total,
            "pass": passed,
        }

    @keyword("Ask And Score Summary")
    def ask_and_score_summary(
        self,
        source_text: str,
        instruction: str,
        required_keywords: list[str],
        forbidden_facts: list[str],
        min_words: int,
        max_words: int,
    ) -> dict[str, Any]:
        """Ask the LLM to summarize ``source_text`` and score the result.

        The prompt is built as ``instruction`` + the source passage. The
        response is run through ``parse_thinking`` so reasoning blocks do
        not skew word counts or coverage signals.
        """
        prompt = f"{instruction}\n\nText:\n{source_text}"
        logger.info(f"Asking LLM to summarize ({len(source_text)} char source)")
        raw_response = self.client.generate(prompt)
        clean_summary, _thinking = parse_thinking(raw_response, strip_unclosed=True)
        emit_rfc_data("actual_answer", clean_summary)
        return self.score_summary(
            summary=clean_summary,
            required_keywords=required_keywords,
            forbidden_facts=forbidden_facts,
            min_words=min_words,
            max_words=max_words,
        )
