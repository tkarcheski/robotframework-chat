"""IFEval (Instruction Following Evaluation) keyword library.

Deterministic constraint checkers for verifying that LLM responses
follow strict formatting and structural instructions.  All checks
are pure Python — no LLM judge is involved in grading.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from robot.api.deco import keyword, not_keyword  # type: ignore[import-untyped]

from .llm_client import LLMProvider, create_provider, resolve_timeout
from .rfc_data import emit_rfc_data
from .thinking import parse_thinking

# Regex for splitting text into sentences on sentence-ending punctuation.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# Regex for detecting bullet-point lines (dash, asterisk, or unicode bullet).
_BULLET_PATTERN = re.compile(r"^\s*[-*\u2022]\s+")

# Regex for detecting numbered-list lines like "1." or "1)".
_NUMBERED_PATTERN = re.compile(r"^\s*(\d+)[.)]\s+")

# Characters that LLMs commonly wrap around words for emphasis or quoting:
# markdown bold/italic (* _), parentheses, brackets, ASCII and curly quotes.
# Stripped from the edges of a token before a literal-word comparison so
# that a semantically compliant response (e.g. "**END**") is not graded as
# a failure for cosmetic formatting.
_WORD_WRAPPER_CHARS = "*_`~()[]{}\"'\u2018\u2019\u201c\u201d"

# Paragraph divider used by the official google/IFEval ParagraphChecker.
_IFEVAL_PARAGRAPH_SPLIT = re.compile(r"\s?\*\*\*\s?")

# Bullet-line patterns per the official IFEval BulletListChecker.
_IFEVAL_STAR_BULLET = re.compile(r"^\s*\*[^*].*$", re.MULTILINE)
_IFEVAL_DASH_BULLET = re.compile(r"^\s*-.*$", re.MULTILINE)

# <<title>> per the official IFEval TitleChecker.
_IFEVAL_TITLE = re.compile(r"<<[^\n]+>>")

# *highlighted section* per the official IFEval HighlightSectionChecker.
_IFEVAL_HIGHLIGHT = re.compile(r"\*[^\n*]+\*")
_IFEVAL_DOUBLE_HIGHLIGHT = re.compile(r"\*\*[^\n*]+\*\*")

# [placeholder] per the official IFEval PlaceholderChecker.
_IFEVAL_PLACEHOLDER = re.compile(r"\[.*?\]")

# Official google/IFEval instruction ids this library can grade.  The HF
# importer (scripts/import_hf_benchmark.py) only commits dataset items whose
# instructions are ALL in this set, so committed data is always gradable.
SUPPORTED_INSTRUCTIONS: frozenset = frozenset(
    {
        "change_case:capital_word_frequency",
        "change_case:english_capital",
        "change_case:english_lowercase",
        "combination:repeat_prompt",
        "detectable_content:number_placeholders",
        "detectable_content:postscript",
        "detectable_format:number_bullet_lists",
        "detectable_format:number_highlighted_sections",
        "detectable_format:title",
        "keywords:existence",
        "keywords:forbidden_words",
        "keywords:frequency",
        "keywords:letter_frequency",
        "length_constraints:number_paragraphs",
        "length_constraints:number_sentences",
        "length_constraints:number_words",
        "punctuation:no_comma",
        "startend:end_checker",
        "startend:quotation",
    }
)


def _check_relation(actual: int, expected: int, relation: str) -> bool:
    """IFEval comparison: ``at least`` (default) or ``less than``."""
    if relation == "less than":
        return actual < expected
    return actual >= expected


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
        """Send *prompt* to the LLM, then verify *constraint* on the response."""
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

        *expected_value* is interpreted per-constraint (e.g. an integer for
        ``sentence_count``, a letter for ``forbidden_letter``); an unrecognised
        constraint raises ``ValueError``.
        """
        dispatch: Dict[str, Any] = {
            "sentence_count": lambda: self.check_sentence_count(
                response, int(expected_value)
            ),
            "all_caps": lambda: self.check_all_caps(response),
            "bullet_points": lambda: self.check_bullet_points(
                response, int(expected_value)
            ),
            "word_count": lambda: self.check_word_count(response, int(expected_value)),
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
                f"Unknown constraint: {constraint!r}.  Supported: {sorted(dispatch)}"
            )

        constraints_requiring_value = {
            "sentence_count",
            "bullet_points",
            "word_count",
            "numbered_list",
            "paragraph_count",
            "forbidden_letter",
            "sentence_start",
            "ends_with_word",
        }
        if constraint in constraints_requiring_value and not expected_value:
            raise ValueError(
                f"Constraint {constraint!r} requires a non-empty expected_value"
            )

        # An empty/whitespace-only response cannot satisfy any positive
        # ifeval constraint. Surface the reason here so reports show
        # "empty response" rather than a generic constraint-mismatch.
        if not response.strip():
            return {
                "passed": False,
                "constraint": constraint,
                "reason": "Empty response — model returned no content",
                "response": response,
            }

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
                f"IFEval constraint {result['constraint']!r} failed: {result['reason']}"
            )

    # ------------------------------------------------------------------
    # Static constraint checkers — pure functions
    # ------------------------------------------------------------------

    @staticmethod
    @not_keyword
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
    @not_keyword
    def check_all_caps(response: str) -> Tuple[bool, str]:
        """Check that every alphabetic character is uppercase."""
        if not response.strip():
            return False, "Empty response"
        alpha = [c for c in response if c.isalpha()]
        if not alpha:
            return False, "Response contains no alphabetic characters"
        if all(c.isupper() for c in alpha):
            return True, "All alphabetic characters are uppercase"
        return False, "Response contains lowercase alphabetic characters"

    @staticmethod
    @not_keyword
    def check_bullet_points(response: str, expected: int) -> Tuple[bool, str]:
        """Check that all non-empty lines are bullet points and count matches."""
        if not response.strip():
            return False, "Empty response"
        lines = [ln for ln in response.split("\n") if ln.strip()]
        non_bullet = [ln for ln in lines if not _BULLET_PATTERN.match(ln)]
        if non_bullet:
            return False, (f"Non-bullet line(s) found: {non_bullet[0]!r}")
        actual = len(lines)
        if actual == expected:
            return True, f"Found {actual} bullet points as expected"
        return False, f"Expected {expected} bullet points, found {actual}"

    @staticmethod
    @not_keyword
    def check_word_count(response: str, expected: int) -> Tuple[bool, str]:
        """Check that *response* contains exactly *expected* words."""
        if not response.strip():
            return False, "Empty response"
        words = response.strip().split()
        actual = len(words)
        if actual == expected:
            return True, f"Found {actual} words as expected"
        return False, f"Expected {expected} words, found {actual}"

    @staticmethod
    @not_keyword
    def check_numbered_list(response: str, expected: int) -> Tuple[bool, str]:
        """Check that *response* is a numbered list 1..*expected*."""
        if not response.strip():
            return False, "Empty response"
        lines = [ln for ln in response.split("\n") if ln.strip()]
        numbers: list[int] = []
        for ln in lines:
            m = _NUMBERED_PATTERN.match(ln)
            if not m:
                return False, f"Non-numbered line found: {ln!r}"
            numbers.append(int(m.group(1)))
        if len(numbers) != expected:
            return False, (f"Expected {expected} numbered items, found {len(numbers)}")
        expected_seq = list(range(1, expected + 1))
        if numbers != expected_seq:
            return False, (f"Expected sequence {expected_seq}, got {numbers}")
        return True, f"Found numbered list 1..{expected} as expected"

    @staticmethod
    @not_keyword
    def check_paragraph_count(response: str, expected: int) -> Tuple[bool, str]:
        """Check that *response* contains exactly *expected* paragraphs."""
        if not response.strip():
            return False, "Empty response"
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", response) if p.strip()]
        actual = len(paragraphs)
        if actual == expected:
            return True, f"Found {actual} paragraphs as expected"
        return False, f"Expected {expected} paragraphs, found {actual}"

    @staticmethod
    @not_keyword
    def check_forbidden_letter(response: str, letter: str) -> Tuple[bool, str]:
        """Check that *letter* does not appear in *response* (case-insensitive)."""
        if not response.strip():
            return False, "Empty response"
        if letter.lower() in response.lower():
            return False, f"Forbidden letter {letter!r} found in response"
        return True, f"Letter {letter!r} not found in response"

    @staticmethod
    @not_keyword
    def check_sentence_start(response: str, word: str) -> Tuple[bool, str]:
        """Check that every sentence starts with *word* (case-sensitive)."""
        text = response.strip()
        if not text:
            return False, "Empty response"
        sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
        for i, sentence in enumerate(sentences, 1):
            unwrapped = sentence.lstrip(_WORD_WRAPPER_CHARS)
            if not unwrapped.startswith(word):
                return False, (
                    f"Sentence {i} starts with {sentence.split()[0]!r}, "
                    f"expected {word!r}"
                )
        return True, f"All {len(sentences)} sentences start with {word!r}"

    @staticmethod
    @not_keyword
    def check_ends_with_word(response: str, word: str) -> Tuple[bool, str]:
        """Check that the last word of *response* is *word*."""
        text = response.strip().rstrip(".,;:!?")
        if not text:
            return False, "Empty response"
        last_token = text.split()[-1]
        last_word = last_token.strip(_WORD_WRAPPER_CHARS)
        if last_word == word:
            return True, f"Response ends with {word!r} as expected"
        return False, f"Response ends with {last_token!r}, expected {word!r}"

    @staticmethod
    @not_keyword
    def check_all_lowercase(response: str) -> Tuple[bool, str]:
        """Check that every alphabetic character is lowercase."""
        if not response.strip():
            return False, "Empty response"
        alpha = [c for c in response if c.isalpha()]
        if not alpha:
            return False, "Response contains no alphabetic characters"
        if all(c.islower() for c in alpha):
            return True, "All alphabetic characters are lowercase"
        return False, "Response contains uppercase alphabetic characters"

    @staticmethod
    @not_keyword
    def check_no_digits(response: str) -> Tuple[bool, str]:
        """Check that *response* contains no digit characters."""
        if not response.strip():
            return False, "Empty response"
        if any(c.isdigit() for c in response):
            return False, "Response contains digit characters"
        return True, "No digits found in response"

    # ------------------------------------------------------------------
    # Official google/IFEval instruction checkers (HF dataset import)
    # ------------------------------------------------------------------

    @keyword("Run IFEval Dataset Item")
    def run_ifeval_dataset_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Run one imported google/IFEval dataset item end to end.

        Strict prompt-level accuracy: every instruction in the item must pass.
        """
        prompt = item["prompt"]
        raw_response = self.client.generate(prompt)
        answer, _ = parse_thinking(raw_response, strip_unclosed=True)
        answer = answer.strip()

        failures = []
        for instruction in item["instructions"]:
            passed, reason = self.check_instruction(
                answer, instruction["id"], instruction.get("kwargs") or {}
            )
            if not passed:
                failures.append(f"{instruction['id']}: {reason}")

        all_passed = not failures
        instruction_ids = ", ".join(i["id"] for i in item["instructions"])
        reason = "; ".join(failures) if failures else "All instructions satisfied"

        emit_rfc_data("actual_answer", answer)
        emit_rfc_data("score", "1" if all_passed else "0")
        emit_rfc_data("expected_answer", f"ifeval:{instruction_ids}")
        emit_rfc_data("grading_reason", reason)

        return {
            "passed": all_passed,
            "key": item.get("key"),
            "constraint": instruction_ids,
            "reason": reason,
            "response": answer,
        }

    @staticmethod
    @keyword("Check IFEval Instruction")
    def check_instruction(
        response: str, instruction_id: str, kwargs: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """Check one official IFEval *instruction_id* against *response*.

        ``None`` values in *kwargs* are ignored; an ``instruction_id`` not in
        :data:`SUPPORTED_INSTRUCTIONS` raises ``ValueError``.
        """
        if instruction_id not in SUPPORTED_INSTRUCTIONS:
            raise ValueError(
                f"Unknown instruction: {instruction_id!r}. "
                f"Supported: {sorted(SUPPORTED_INSTRUCTIONS)}"
            )
        kw = {k: v for k, v in kwargs.items() if v is not None}
        checker = getattr(
            IFEvalKeywords,
            "_instr_" + instruction_id.replace(":", "__"),
        )
        result: Tuple[bool, str] = checker(response, kw)
        return result

    @staticmethod
    def _instr_punctuation__no_comma(
        response: str, kw: Dict[str, Any]
    ) -> Tuple[bool, str]:
        if "," in response:
            return False, "Response contains a comma"
        return True, "No commas in response"

    @staticmethod
    def _instr_change_case__english_capital(
        response: str, kw: Dict[str, Any]
    ) -> Tuple[bool, str]:
        return IFEvalKeywords.check_all_caps(response)

    @staticmethod
    def _instr_change_case__english_lowercase(
        response: str, kw: Dict[str, Any]
    ) -> Tuple[bool, str]:
        return IFEvalKeywords.check_all_lowercase(response)

    @staticmethod
    def _instr_change_case__capital_word_frequency(
        response: str, kw: Dict[str, Any]
    ) -> Tuple[bool, str]:
        expected = int(kw["capital_frequency"])
        relation = kw.get("capital_relation", "at least")
        words = [w for w in response.split() if any(c.isalpha() for c in w)]
        actual = sum(1 for w in words if w.isupper())
        if _check_relation(actual, expected, relation):
            return True, f"Found {actual} all-caps words ({relation} {expected})"
        return False, f"Expected {relation} {expected} all-caps words, found {actual}"

    @staticmethod
    def _instr_length_constraints__number_words(
        response: str, kw: Dict[str, Any]
    ) -> Tuple[bool, str]:
        expected = int(kw["num_words"])
        relation = kw.get("relation", "at least")
        actual = len(response.split())
        if _check_relation(actual, expected, relation):
            return True, f"Found {actual} words ({relation} {expected})"
        return False, f"Expected {relation} {expected} words, found {actual}"

    @staticmethod
    def _instr_length_constraints__number_sentences(
        response: str, kw: Dict[str, Any]
    ) -> Tuple[bool, str]:
        expected = int(kw["num_sentences"])
        relation = kw.get("relation", "at least")
        text = response.strip()
        sentences = (
            [s for s in _SENTENCE_SPLIT.split(text) if s.strip()] if text else []
        )
        actual = len(sentences)
        if _check_relation(actual, expected, relation):
            return True, f"Found {actual} sentences ({relation} {expected})"
        return False, f"Expected {relation} {expected} sentences, found {actual}"

    @staticmethod
    def _instr_length_constraints__number_paragraphs(
        response: str, kw: Dict[str, Any]
    ) -> Tuple[bool, str]:
        expected = int(kw["num_paragraphs"])
        paragraphs = _IFEVAL_PARAGRAPH_SPLIT.split(response)
        count = len(paragraphs)
        for index, paragraph in enumerate(paragraphs):
            if paragraph.strip():
                continue
            if index in (0, len(paragraphs) - 1):
                count -= 1
            else:
                return False, f"Empty paragraph at *** divider position {index}"
        if count == expected:
            return True, f"Found {count} ***-separated paragraphs as expected"
        return False, f"Expected {expected} ***-separated paragraphs, found {count}"

    @staticmethod
    def _instr_detectable_format__number_bullet_lists(
        response: str, kw: Dict[str, Any]
    ) -> Tuple[bool, str]:
        expected = int(kw["num_bullets"])
        actual = len(_IFEVAL_STAR_BULLET.findall(response)) + len(
            _IFEVAL_DASH_BULLET.findall(response)
        )
        if actual == expected:
            return True, f"Found {actual} bullet points as expected"
        return False, f"Expected {expected} bullet points, found {actual}"

    @staticmethod
    def _instr_detectable_format__title(
        response: str, kw: Dict[str, Any]
    ) -> Tuple[bool, str]:
        if _IFEVAL_TITLE.search(response):
            return True, "Found a <<title>>"
        return False, "No <<title>> found in response"

    @staticmethod
    def _instr_detectable_format__number_highlighted_sections(
        response: str, kw: Dict[str, Any]
    ) -> Tuple[bool, str]:
        expected = int(kw["num_highlights"])
        actual = 0
        for match in _IFEVAL_HIGHLIGHT.findall(response):
            if match.strip("*").strip():
                actual += 1
        for match in _IFEVAL_DOUBLE_HIGHLIGHT.findall(response):
            if match.strip("*").strip():
                actual += 1
        if actual >= expected:
            return True, f"Found {actual} highlighted sections (at least {expected})"
        return False, (
            f"Expected at least {expected} *highlighted* sections, found {actual}"
        )

    @staticmethod
    def _instr_keywords__existence(
        response: str, kw: Dict[str, Any]
    ) -> Tuple[bool, str]:
        keywords = kw["keywords"]
        missing = [
            k
            for k in keywords
            if not re.search(rf"\b{re.escape(k)}\b", response, flags=re.IGNORECASE)
        ]
        if missing:
            return False, f"Missing keyword(s): {', '.join(missing)}"
        return True, f"All {len(keywords)} keywords present"

    @staticmethod
    def _instr_keywords__forbidden_words(
        response: str, kw: Dict[str, Any]
    ) -> Tuple[bool, str]:
        found = [
            w
            for w in kw["forbidden_words"]
            if re.search(rf"\b{re.escape(w)}\b", response, flags=re.IGNORECASE)
        ]
        if found:
            return False, f"Forbidden word(s) present: {', '.join(found)}"
        return True, "No forbidden words present"

    @staticmethod
    def _instr_keywords__frequency(
        response: str, kw: Dict[str, Any]
    ) -> Tuple[bool, str]:
        word = kw["keyword"]
        expected = int(kw["frequency"])
        relation = kw.get("relation", "at least")
        actual = len(
            re.findall(rf"\b{re.escape(word)}\b", response, flags=re.IGNORECASE)
        )
        if _check_relation(actual, expected, relation):
            return True, f"Keyword {word!r} appears {actual}x ({relation} {expected})"
        return False, (
            f"Expected keyword {word!r} {relation} {expected}x, found {actual}x"
        )

    @staticmethod
    def _instr_keywords__letter_frequency(
        response: str, kw: Dict[str, Any]
    ) -> Tuple[bool, str]:
        letter = kw["letter"].lower()
        expected = int(kw["let_frequency"])
        relation = kw.get("let_relation", "at least")
        actual = response.lower().count(letter)
        if _check_relation(actual, expected, relation):
            return True, f"Letter {letter!r} appears {actual}x ({relation} {expected})"
        return False, (
            f"Expected letter {letter!r} {relation} {expected}x, found {actual}x"
        )

    @staticmethod
    def _instr_startend__end_checker(
        response: str, kw: Dict[str, Any]
    ) -> Tuple[bool, str]:
        end_phrase = kw["end_phrase"].strip().lower()
        value = response.strip().strip('"').lower()
        if value.endswith(end_phrase):
            return True, f"Response ends with {kw['end_phrase']!r}"
        return False, f"Response does not end with {kw['end_phrase']!r}"

    @staticmethod
    def _instr_startend__quotation(
        response: str, kw: Dict[str, Any]
    ) -> Tuple[bool, str]:
        value = response.strip()
        if len(value) > 1 and value.startswith('"') and value.endswith('"'):
            return True, "Response is wrapped in double quotation marks"
        return False, "Response is not wrapped in double quotation marks"

    @staticmethod
    def _instr_detectable_content__number_placeholders(
        response: str, kw: Dict[str, Any]
    ) -> Tuple[bool, str]:
        expected = int(kw["num_placeholders"])
        actual = len(_IFEVAL_PLACEHOLDER.findall(response))
        if actual >= expected:
            return True, f"Found {actual} [placeholders] (at least {expected})"
        return False, f"Expected at least {expected} [placeholders], found {actual}"

    @staticmethod
    def _instr_detectable_content__postscript(
        response: str, kw: Dict[str, Any]
    ) -> Tuple[bool, str]:
        marker = kw["postscript_marker"]
        value = response.lower()
        if marker == "P.P.S":
            pattern = r"\s*p\.\s?p\.\s?s.*$"
        elif marker == "P.S.":
            pattern = r"\s*p\.\s?s\..*$"
        else:
            pattern = r"\s*" + re.escape(marker.lower()) + r".*$"
        if re.search(pattern, value, flags=re.MULTILINE):
            return True, f"Postscript marker {marker!r} found"
        return False, f"Postscript marker {marker!r} not found"

    @staticmethod
    def _instr_combination__repeat_prompt(
        response: str, kw: Dict[str, Any]
    ) -> Tuple[bool, str]:
        prompt_to_repeat = kw["prompt_to_repeat"].strip().lower()
        if response.strip().lower().startswith(prompt_to_repeat):
            return True, "Response begins by repeating the prompt"
        return False, "Response does not begin with the repeated prompt"
