"""Tests for rfc.hallucination_keywords.HallucinationKeywords."""

import os
from unittest.mock import MagicMock, patch

from rfc.hallucination_keywords import HallucinationKeywords


class TestHallucinationKeywordsInit:
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_default_init(self, MockGrader: MagicMock, mock_create: MagicMock) -> None:
        HallucinationKeywords()
        mock_create.assert_called_once_with(timeout=5400, max_retries=2)
        MockGrader.assert_called_once_with(mock_create.return_value)

    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_custom_timeout(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        HallucinationKeywords(timeout=60, max_retries=1)
        mock_create.assert_called_once_with(timeout=60, max_retries=1)

    @patch.dict(os.environ, {"OLLAMA_TIMEOUT": "300"})
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_default_timeout_from_env(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        HallucinationKeywords()
        mock_create.assert_called_once_with(timeout=300, max_retries=2)


class TestExtractReferences:
    """Test the static reference extraction logic."""

    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_extracts_urls(self, MockGrader: MagicMock, mock_create: MagicMock) -> None:
        kw = HallucinationKeywords()
        text = "See https://example.com/paper and http://test.org/doc for details."
        refs = kw._extract_references(text)
        assert "https://example.com/paper" in refs["urls"]
        assert "http://test.org/doc" in refs["urls"]

    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_extracts_isbn13(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = HallucinationKeywords()
        text = "ISBN: 978-0-13-468599-1"
        refs = kw._extract_references(text)
        assert any("978-0-13-468599-1" in isbn for isbn in refs["isbns"])

    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_extracts_isbn10(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = HallucinationKeywords()
        text = "ISBN 0-13-468599-7"
        refs = kw._extract_references(text)
        assert len(refs["isbns"]) >= 1

    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_extracts_dois(self, MockGrader: MagicMock, mock_create: MagicMock) -> None:
        kw = HallucinationKeywords()
        text = "DOI: 10.1038/nature12373"
        refs = kw._extract_references(text)
        assert "10.1038/nature12373" in refs["dois"]

    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_no_references_found(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = HallucinationKeywords()
        text = "This text has no citations at all."
        refs = kw._extract_references(text)
        assert refs["urls"] == []
        assert refs["isbns"] == []
        assert refs["dois"] == []

    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_extracts_arxiv_ids(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = HallucinationKeywords()
        text = "See arXiv:1706.03762 for the original paper."
        refs = kw._extract_references(text)
        assert "1706.03762" in refs["arxiv_ids"]

    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_extracts_us_reports_legal_citation(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = HallucinationKeywords()
        text = "The ruling in 347 U.S. 483 was unanimous."
        refs = kw._extract_references(text)
        assert any("347" in c and "483" in c for c in refs["legal_cites"])

    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_extracts_federal_reporter_citation(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = HallucinationKeywords()
        text = "See 123 F.2d 456 for the ruling."
        refs = kw._extract_references(text)
        assert any("123" in c and "456" in c for c in refs["legal_cites"])

    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_extracts_supreme_court_reporter(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = HallucinationKeywords()
        text = "Cited as 140 S.Ct. 1390."
        refs = kw._extract_references(text)
        assert len(refs["legal_cites"]) >= 1

    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_extracts_un_resolution(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = HallucinationKeywords()
        text = "See UN doc A/RES/217 adopted in 1948."
        refs = kw._extract_references(text)
        assert "A/RES/217" in refs["un_resolutions"]

    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_extracts_security_council_resolution(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = HallucinationKeywords()
        text = "Security Council resolution S/RES/1973 authorized action."
        refs = kw._extract_references(text)
        assert "S/RES/1973" in refs["un_resolutions"]

    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_extracts_un_resolution_lowercase(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = HallucinationKeywords()
        # Mixed-case / lowercase model output must still be extracted.
        text = "The model wrote a/res/999 instead of the canonical form."
        refs = kw._extract_references(text)
        assert len(refs["un_resolutions"]) == 1
        assert "999" in refs["un_resolutions"][0]

    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_extracts_lowercase_legal_citation(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = HallucinationKeywords()
        # Lowercase reporter output must still be extracted.
        text = "Cited as 999 u.s. 123 in the brief."
        refs = kw._extract_references(text)
        assert len(refs["legal_cites"]) >= 1
        assert any("999" in c and "123" in c for c in refs["legal_cites"])


class TestUNResolutionFabrication:
    """UN resolution IDs (non-URL citation identifiers) must be validated."""

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_fabricated_un_resolution_detected(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        kw = HallucinationKeywords()
        # Model fabricates an unrelated UN resolution identifier.
        response = "The UDHR was adopted in resolution A/RES/999."
        known_real = ["A/RES/217"]
        result = kw.check_no_fabricated_citations(response, known_real)
        assert result["is_clean"] is False
        assert any("999" in r for r in result["fabricated_refs"])

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_real_un_resolution_clean(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        kw = HallucinationKeywords()
        response = "The UDHR is UN resolution A/RES/217."
        known_real = ["A/RES/217"]
        result = kw.check_no_fabricated_citations(response, known_real)
        assert result["is_clean"] is True

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_lowercase_un_resolution_fabrication_detected(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        kw = HallucinationKeywords()
        # Lowercase fabricated UN resolution must still be detected.
        response = "The declaration is in resolution a/res/999 from the assembly."
        known_real = ["A/RES/217"]
        result = kw.check_no_fabricated_citations(response, known_real)
        assert result["is_clean"] is False
        assert any("999" in r for r in result["fabricated_refs"])


class TestCitationNormalization:
    """Punctuation/spacing variants of the same citation must match."""

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_legal_cite_without_periods_matches_canonical(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        kw = HallucinationKeywords()
        # Model writes "347 US 483" but known canonical form is "347 U.S. 483".
        response = "Brown v. Board of Education, 347 US 483, was decided in 1954."
        known_real = ["347 U.S. 483"]
        result = kw.check_no_fabricated_citations(response, known_real)
        assert result["is_clean"] is True

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_canonical_form_matches_no_periods_known(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        kw = HallucinationKeywords()
        response = "Cited as 347 U.S. 483 by the court."
        known_real = ["347 US 483"]
        result = kw.check_no_fabricated_citations(response, known_real)
        assert result["is_clean"] is True

    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_normalize_strips_punctuation(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = HallucinationKeywords()
        assert kw._normalize_citation("347 U.S. 483") == "347 us 483"
        assert kw._normalize_citation("347 US 483") == "347 us 483"
        assert kw._normalize_citation("  347  U.S.  483  ") == "347 us 483"


class TestLowercaseLegalCitationFabrication:
    """Lowercase legal citations must trigger fabrication detection."""

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_lowercase_fabricated_legal_citation_detected(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        kw = HallucinationKeywords()
        response = "Smith v. Anderson, 999 u.s. 123, was decided in 2019."
        result = kw.check_no_fabricated_citations(response, [])
        assert result["is_clean"] is False
        assert any("999" in r for r in result["fabricated_refs"])


class TestDOIURLReconciliation:
    """A bare DOI extracted from a DOI URL must match the URL in known refs."""

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_doi_url_reconciles_with_bare_doi(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        kw = HallucinationKeywords()
        # Response uses a DOI URL; extractor pulls both the URL and the
        # bare DOI as separate tokens. Known list only has the URL form —
        # both must be marked clean via the reverse-match pass.
        response = "See https://doi.org/10.1038/nature12373 for the paper."
        known_real = ["https://doi.org/10.1038/nature12373"]
        result = kw.check_no_fabricated_citations(response, known_real)
        assert result["is_clean"] is True


class TestURLHostMatching:
    """Dot-containing URL host fragments must still match canonical URLs."""

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_known_host_path_matches_full_url_with_subdomain(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        kw = HallucinationKeywords()
        # Known ref is a host+path fragment; model returns full URL with
        # www subdomain. Dots in the host must be preserved.
        response = (
            "See https://www.un.org/en/about-us/universal-declaration-of-human-rights"
        )
        known_real = ["un.org/en/about-us/universal-declaration-of-human-rights"]
        result = kw.check_no_fabricated_citations(response, known_real)
        assert result["is_clean"] is True

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_known_url_matches_exact_url(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        kw = HallucinationKeywords()
        response = "Reference: https://real.com/paper"
        known_real = ["https://real.com/paper"]
        result = kw.check_no_fabricated_citations(response, known_real)
        assert result["is_clean"] is True


class TestCheckNoFabricatedCitations:
    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_clean_response_with_known_refs(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        kw = HallucinationKeywords()
        response = "See https://example.com for details."
        known_real = ["https://example.com"]
        result = kw.check_no_fabricated_citations(response, known_real)
        assert result["is_clean"] is True
        assert result["fabricated_refs"] == []

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_fabricated_url_detected(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        kw = HallucinationKeywords()
        response = "See https://fake-journal.com/paper123 for more info."
        known_real = ["https://real-journal.com/paper"]
        result = kw.check_no_fabricated_citations(response, known_real)
        assert result["is_clean"] is False
        assert "https://fake-journal.com/paper123" in result["fabricated_refs"]

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_known_ref_substring_match(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        kw = HallucinationKeywords()
        response = "The case is 347 U.S. 483. See https://example.com/page."
        known_real = ["347 U.S. 483", "example.com"]
        result = kw.check_no_fabricated_citations(response, known_real)
        assert result["is_clean"] is True

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_emits_rfc_data(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        kw = HallucinationKeywords()
        kw.check_no_fabricated_citations("No refs here.", [])
        info_calls = [str(c) for c in mock_rfc_logger.info.call_args_list]
        rfc_score = [c for c in info_calls if "RFC_DATA:score:" in c]
        assert len(rfc_score) >= 1

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_no_refs_in_response_is_clean(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        kw = HallucinationKeywords()
        result = kw.check_no_fabricated_citations(
            "The ruling was landmark.", ["347 U.S. 483"]
        )
        assert result["is_clean"] is True
        assert result["fabricated_refs"] == []


class TestAskAndCheckCitations:
    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_ask_and_check_calls_generate(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_client.generate.return_value = "See https://known.com for details."
        mock_create.return_value = mock_client
        kw = HallucinationKeywords()
        result = kw.ask_and_check_citations("Cite the paper.", ["https://known.com"])
        mock_client.generate.assert_called_once_with("Cite the paper.")
        assert result["is_clean"] is True

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_ask_and_check_detects_fabrication(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_client.generate.return_value = "The paper is at https://fake-url.com/paper"
        mock_create.return_value = mock_client
        kw = HallucinationKeywords()
        result = kw.ask_and_check_citations("Cite it.", ["https://real.com"])
        assert result["is_clean"] is False


class TestCheckAdversarialSummary:
    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_fact_not_reproduced(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        mock_grader = MockGrader.return_value
        mock_grader.grade.return_value = MagicMock(
            score=1.0, reason="Fabricated fact not found in summary."
        )
        kw = HallucinationKeywords()
        result = kw.check_adversarial_summary(
            "The internet was developed over decades.",
            "TCP/IP was standardized in 1995",
        )
        assert result["fact_reproduced"] is False
        assert result["score"] == 1.0

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_fact_reproduced(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        mock_grader = MockGrader.return_value
        mock_grader.grade.return_value = MagicMock(
            score=0.0, reason="Summary repeats the fabricated claim."
        )
        kw = HallucinationKeywords()
        result = kw.check_adversarial_summary(
            "TCP/IP was standardized in 1995 and the internet grew.",
            "TCP/IP was standardized in 1995",
        )
        assert result["fact_reproduced"] is True
        assert result["score"] == 0.0

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_emits_rfc_data(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        mock_grader = MockGrader.return_value
        mock_grader.grade.return_value = MagicMock(score=1.0, reason="clean")
        kw = HallucinationKeywords()
        kw.check_adversarial_summary("summary text", "fake fact")
        info_calls = [str(c) for c in mock_rfc_logger.info.call_args_list]
        rfc_score = [c for c in info_calls if "RFC_DATA:score:" in c]
        rfc_fact = [c for c in info_calls if "RFC_DATA:fabricated_fact:" in c]
        assert len(rfc_score) >= 1
        assert len(rfc_fact) >= 1

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_grader_called_with_correct_args(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        mock_grader = MockGrader.return_value
        mock_grader.grade.return_value = MagicMock(score=1.0, reason="ok")
        kw = HallucinationKeywords()
        kw.check_adversarial_summary("A good summary.", "fake fact here")
        mock_grader.grade.assert_called_once()
        call_args = mock_grader.grade.call_args
        # The question should mention the fabricated fact
        assert "fake fact here" in call_args[0][0] or "fake fact here" in str(call_args)


class TestLegalCitationFabrication:
    """Legal-style citations (e.g. '123 U.S. 456') must be parsed and checked."""

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_fabricated_legal_citation_detected(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        kw = HallucinationKeywords()
        # Model fabricates a reporter citation for a nonexistent case.
        response = "Smith v. Anderson (2019), 999 U.S. 123, held that..."
        known_real = ["347 U.S. 483"]
        result = kw.check_no_fabricated_citations(response, known_real)
        assert result["is_clean"] is False
        assert any("999" in r for r in result["fabricated_refs"])

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_real_legal_citation_clean(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        kw = HallucinationKeywords()
        response = "Brown v. Board of Education, 347 U.S. 483 (1954)."
        known_real = ["347 U.S. 483"]
        result = kw.check_no_fabricated_citations(response, known_real)
        assert result["is_clean"] is True


class TestThinkingTagStripping:
    """Reasoning-model thinking blocks must be stripped before citation checks."""

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_ask_and_check_ignores_thinking_block(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        # LLM hides an unrelated URL inside a <think> block; the visible
        # answer contains only known-real references.
        mock_client.generate.return_value = (
            "<think>maybe https://scratch-pad.example/foo?</think>"
            "The citation is https://real.com/paper."
        )
        mock_create.return_value = mock_client
        kw = HallucinationKeywords()
        result = kw.ask_and_check_citations("Cite it.", ["https://real.com/paper"])
        # Thinking content must not count as fabrication.
        assert result["is_clean"] is True
        assert all("scratch-pad" not in r for r in result["fabricated_refs"])


class TestKnownRefWordBoundary:
    """Short known refs must not accidentally whitelist fabricated refs."""

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_short_numeric_known_ref_does_not_whitelist_doi(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        kw = HallucinationKeywords()
        # Known ref "217" should NOT match a fabricated DOI containing 217
        # as an internal substring.
        response = "See DOI: 10.1038/217abcxyz for details."
        known_real = ["217"]
        result = kw.check_no_fabricated_citations(response, known_real)
        assert result["is_clean"] is False
        assert any("217abcxyz" in r for r in result["fabricated_refs"])

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_known_ref_word_boundary_match(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        kw = HallucinationKeywords()
        # "347 U.S. 483" appears at a word boundary inside an extracted
        # legal citation — should be recognized as known.
        response = "The case 347 U.S. 483 (1954) was landmark."
        known_real = ["347 U.S. 483"]
        result = kw.check_no_fabricated_citations(response, known_real)
        assert result["is_clean"] is True


class TestCheckNoFabricatedCitationsEdgeCases:
    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_mixed_real_and_fake_refs(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        kw = HallucinationKeywords()
        response = (
            "See https://real.com/paper and https://fabricated.org/fake "
            "and DOI: 10.1234/fake.doi"
        )
        known_real = ["https://real.com/paper"]
        result = kw.check_no_fabricated_citations(response, known_real)
        assert result["is_clean"] is False
        assert len(result["fabricated_refs"]) >= 1
        assert "https://real.com/paper" not in result["fabricated_refs"]

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_empty_response(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        kw = HallucinationKeywords()
        result = kw.check_no_fabricated_citations("", [])
        # An empty response is non-substantive: it contributed no
        # citations, but it also failed to produce the citation the
        # test asked for. is_clean must be False.
        assert result["is_clean"] is False

    @patch("rfc.hallucination_keywords.logger")
    @patch("rfc.rfc_data.logger")
    @patch("rfc.hallucination_keywords.create_provider")
    @patch("rfc.hallucination_keywords.Grader")
    def test_case_insensitive_known_ref_match(
        self,
        MockGrader: MagicMock,
        mock_create: MagicMock,
        mock_rfc_logger: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        kw = HallucinationKeywords()
        response = "See HTTPS://EXAMPLE.COM/Paper for details."
        known_real = ["https://example.com/paper"]
        result = kw.check_no_fabricated_citations(response, known_real)
        assert result["is_clean"] is True
