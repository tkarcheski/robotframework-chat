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
    def test_extracts_urls(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
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
    def test_extracts_dois(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
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
        result = kw.ask_and_check_citations(
            "Cite the paper.", ["https://known.com"]
        )
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
        mock_client.generate.return_value = (
            "The paper is at https://fake-url.com/paper"
        )
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
        assert "fake fact here" in call_args[0][0] or "fake fact here" in str(
            call_args
        )


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
        assert result["is_clean"] is True

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
