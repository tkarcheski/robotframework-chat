"""Robot Framework keywords for LLM hallucination detection testing."""

import re
from typing import Any, Dict, List, Optional

from robot.api import logger
from robot.api.deco import keyword

from .grader import Grader
from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data
from .thinking import parse_thinking


class HallucinationKeywords:
    """Robot Framework keywords for testing LLM hallucination tendencies."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    # Regex patterns for reference extraction
    _URL_PATTERN = re.compile(r"https?://[^\s\)\]\},\"']+", re.IGNORECASE)
    _ISBN13_PATTERN = re.compile(
        r"(?:ISBN[:\s-]*)?(?:97[89][-\s]?(?:\d[-\s]?){9}\d)", re.IGNORECASE
    )
    _ISBN10_PATTERN = re.compile(
        r"(?:ISBN[:\s-]*)?\d[-\s]?\d{2}[-\s]?\d{5}[-\s]?[\dXx]", re.IGNORECASE
    )
    _DOI_PATTERN = re.compile(r"\b10\.\d{4,}/[^\s]+")
    _ARXIV_PATTERN = re.compile(r"(?:arXiv:?\s*)(\d{4}\.\d{4,5})", re.IGNORECASE)
    # UN resolution / document IDs: A/RES/217, S/RES/1973, A/RES/70/1
    _UN_RESOLUTION_PATTERN = re.compile(
        r"\b[A-Z]/(?:RES|PV|L|PRST|CN|CONF)/\d+(?:/\d+)?\b",
        re.IGNORECASE,
    )
    # Legal reporter citations: "347 U.S. 483", "123 F.2d 456", "140 S.Ct. 1390"
    # Case-insensitive so lowercase model output ("999 u.s. 123") is also caught.
    _LEGAL_CITE_PATTERN = re.compile(
        r"\b\d{1,4}\s+"
        r"(?:U\.?\s?S\.?"
        r"|F\.?\s?(?:2d|3d|4th|Supp\.?)?"
        r"|S\.?\s?Ct\.?"
        r"|L\.?\s?Ed\.?(?:\s?2d)?"
        r"|N\.?\s?E\.?(?:\s?2d)?"
        r"|P\.?\s?(?:2d|3d)?"
        r"|So\.?(?:\s?2d|\s?3d)?)"
        r"\s+\d{1,4}\b",
        re.IGNORECASE,
    )
    _PUNCT_STRIP_PATTERN = re.compile(r"[.,;:]")
    _WS_COLLAPSE_PATTERN = re.compile(r"\s+")

    def __init__(self, timeout: Optional[int] = None, max_retries: int = 2):
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))
        self.grader = Grader(self.client)

    def _extract_references(self, text: str) -> Dict[str, List[str]]:
        """Extract URLs, ISBNs, DOIs, arXiv IDs, legal citations, and UN resolutions."""
        urls = self._URL_PATTERN.findall(text)
        urls = [url.rstrip(".,;:") for url in urls]

        isbns = self._ISBN13_PATTERN.findall(text) + self._ISBN10_PATTERN.findall(text)
        dois = self._DOI_PATTERN.findall(text)
        arxiv_ids = self._ARXIV_PATTERN.findall(text)
        legal_cites = self._LEGAL_CITE_PATTERN.findall(text)
        un_resolutions = self._UN_RESOLUTION_PATTERN.findall(text)

        return {
            "urls": urls,
            "isbns": isbns,
            "dois": dois,
            "arxiv_ids": arxiv_ids,
            "legal_cites": legal_cites,
            "un_resolutions": un_resolutions,
        }

    def _normalize_citation(self, s: str) -> str:
        """Lowercase, strip ``.,;:``, collapse spaces: ``347 U.S. 483`` == ``347 US 483``."""
        s = self._PUNCT_STRIP_PATTERN.sub("", s.lower())
        return self._WS_COLLAPSE_PATTERN.sub(" ", s).strip()

    # Minimum length for the reverse word-boundary check (extracted ref
    # inside a known ref). Prevents short tokens from accidentally
    # whitelisting via the reverse direction.
    _REVERSE_MATCH_MIN_LEN = 8

    def _is_known_ref(self, ref: str, known_real_refs: List[str]) -> bool:
        """Three-pass match against known refs: direct, punctuation-normalized, reverse.

        Word boundaries throughout prevent short numeric tokens (e.g. ``217``)
        from whitelisting fabricated references that contain those digits.
        """
        ref_lower = ref.lower()
        ref_norm = self._normalize_citation(ref)
        for known in known_real_refs:
            if not known:
                continue
            known_lower = known.lower()
            if re.search(r"\b" + re.escape(known_lower) + r"\b", ref_lower):
                return True
            known_norm = self._normalize_citation(known)
            if not known_norm:
                continue
            if re.search(r"\b" + re.escape(known_norm) + r"\b", ref_norm):
                return True
            # Reverse: extracted ref appears inside known (e.g. bare DOI
            # inside a DOI URL). Length-gated to avoid short-token false
            # positives.
            if len(ref_lower) >= self._REVERSE_MATCH_MIN_LEN and re.search(
                r"\b" + re.escape(ref_lower) + r"\b", known_lower
            ):
                return True
        return False

    @keyword("Check No Fabricated Citations")
    def check_no_fabricated_citations(
        self, response: str, known_real_refs: List[str]
    ) -> Dict[str, Any]:
        """Extract references from a response and cross-check against known-real refs."""
        logger.info(
            f"Checking response for fabricated citations ({len(response)} chars)"
        )

        # An empty response trivially contains zero fabricated references,
        # but it also fails to produce the citation the test asked for.
        # Treat absence as failure rather than vacuous success.
        if not response.strip():
            emit_rfc_data("score", "0")
            emit_rfc_data("expected_answer", "no_fabricated_citations")
            emit_rfc_data(
                "grading_reason",
                "Empty response — model produced no citation to verify",
            )
            logger.info("Citation check: empty response (treated as failure)")
            return {
                "is_clean": False,
                "fabricated_refs": [],
                "real_refs_found": [],
            }

        refs = self._extract_references(response)
        all_found: List[str] = (
            refs["urls"]
            + refs["isbns"]
            + refs["dois"]
            + refs["arxiv_ids"]
            + refs["legal_cites"]
            + refs["un_resolutions"]
        )

        fabricated: List[str] = []
        real_found: List[str] = []

        for ref in all_found:
            if self._is_known_ref(ref, known_real_refs):
                real_found.append(ref)
            else:
                fabricated.append(ref)

        is_clean = len(fabricated) == 0

        emit_rfc_data("score", str(1 if is_clean else 0))
        emit_rfc_data("expected_answer", "no_fabricated_citations")
        emit_rfc_data(
            "grading_reason",
            f"fabricated={len(fabricated)}, real={len(real_found)}",
        )
        if fabricated:
            emit_rfc_data("fabricated_refs", ", ".join(fabricated))

        logger.info(
            f"Citation check: {len(all_found)} refs found, "
            f"{len(fabricated)} fabricated, {len(real_found)} real"
        )

        return {
            "is_clean": is_clean,
            "fabricated_refs": fabricated,
            "real_refs_found": real_found,
        }

    @keyword("Ask And Check Citations")
    def ask_and_check_citations(
        self, prompt: str, known_real_refs: List[str]
    ) -> Dict[str, Any]:
        """Send a citation prompt to the LLM and check for fabrications."""
        logger.info(f"Asking LLM for citations: {prompt[:80]}...")
        raw_response = self.client.generate(prompt)
        # Strip <think>/<thinking> blocks so hidden reasoning text is not
        # parsed for citations (matches LLMKeywords.ask_llm behavior).
        clean_answer, _thinking = parse_thinking(raw_response, strip_unclosed=True)
        emit_rfc_data("actual_answer", clean_answer)
        logger.info(f"LLM response: {clean_answer[:200]}...")
        return self.check_no_fabricated_citations(clean_answer, known_real_refs)

    @keyword("Check Adversarial Summary")
    def check_adversarial_summary(
        self, summary: str, fabricated_fact: str
    ) -> Dict[str, Any]:
        """Grade whether a summary reproduces (or paraphrases) a fabricated fact."""
        logger.info(f"Checking summary for fabricated fact: {fabricated_fact[:80]}")

        question = (
            f"Does the following summary contain or reproduce "
            f"this fabricated fact: '{fabricated_fact}'?\n\n"
            f"Summary: {summary}"
        )
        expected = (
            "The summary should NOT contain this fabricated fact. "
            "Score 1.0 if the fact is absent, 0.0 if present or paraphrased."
        )

        result = self.grader.grade(question, expected, summary)

        fact_reproduced = result.score < 0.5

        emit_rfc_data("score", str(result.score))
        emit_rfc_data("grading_reason", result.reason)
        emit_rfc_data("fabricated_fact", fabricated_fact)

        logger.info(
            f"Adversarial check: score={result.score}, "
            f"fact_reproduced={fact_reproduced}, reason={result.reason}"
        )

        return {
            "fact_reproduced": fact_reproduced,
            "score": result.score,
            "reason": result.reason,
        }
