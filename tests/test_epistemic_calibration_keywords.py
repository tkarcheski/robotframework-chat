"""Tests for rfc.epistemic_calibration_keywords.EpistemicCalibrationKeywords."""

from unittest.mock import MagicMock, patch

from rfc.epistemic_calibration_keywords import (
    EpistemicCalibrationKeywords,
    DEFAULT_BOUNDARY_MARKERS,
    DEFAULT_UNCERTAINTY_MARKERS,
    _contains_any_marker,
)


# ---------------------------------------------------------------------------
# _contains_any_marker
# ---------------------------------------------------------------------------


class TestContainsAnyMarker:
    def test_finds_exact_marker(self) -> None:
        assert _contains_any_marker("I cannot determine the answer.", ["cannot"])

    def test_case_insensitive(self) -> None:
        assert _contains_any_marker("I CANNOT determine this.", ["cannot"])

    def test_multi_word_marker(self) -> None:
        assert _contains_any_marker("I don't know the current price.", ["don't know"])

    def test_returns_false_when_no_marker(self) -> None:
        assert not _contains_any_marker("The answer is 42.", ["cannot", "don't know"])

    def test_empty_response(self) -> None:
        assert not _contains_any_marker("", ["cannot"])

    def test_empty_markers_list(self) -> None:
        assert not _contains_any_marker("I don't know.", [])

    def test_finds_first_matching_marker(self) -> None:
        assert _contains_any_marker(
            "I am uncertain about this.", ["uncertain", "cannot"]
        )

    def test_training_cutoff_marker(self) -> None:
        assert _contains_any_marker(
            "As of my training cutoff, I cannot access real-time data.",
            ["training cutoff"],
        )


# ---------------------------------------------------------------------------
# DEFAULT_UNCERTAINTY_MARKERS
# ---------------------------------------------------------------------------


class TestDefaultUncertaintyMarkers:
    def test_markers_is_nonempty_list(self) -> None:
        assert isinstance(DEFAULT_UNCERTAINTY_MARKERS, list)
        assert len(DEFAULT_UNCERTAINTY_MARKERS) > 0

    def test_common_hedging_words_present(self) -> None:
        combined = " ".join(DEFAULT_UNCERTAINTY_MARKERS).lower()
        assert "cannot" in combined or "can't" in combined
        assert "don't know" in combined or "do not know" in combined

    def test_random_prefix_not_treated_as_uncertainty(self) -> None:
        # "Random guess: X" is a definitive claim, not an uncertainty expression.
        assert not _contains_any_marker(
            "Random guess: it will be 4.", DEFAULT_UNCERTAINTY_MARKERS
        )

    def test_inherently_not_treated_as_uncertainty(self) -> None:
        # "Inherently the answer is X" asserts certainty, not uncertainty.
        assert not _contains_any_marker(
            "Inherently the answer is 6.", DEFAULT_UNCERTAINTY_MARKERS
        )


class TestDefaultBoundaryMarkers:
    def test_markers_is_nonempty_list(self) -> None:
        assert isinstance(DEFAULT_BOUNDARY_MARKERS, list)
        assert len(DEFAULT_BOUNDARY_MARKERS) > 0

    def test_training_related_markers_present(self) -> None:
        combined = " ".join(DEFAULT_BOUNDARY_MARKERS).lower()
        assert "training" in combined or "cutoff" in combined or "real-time" in combined

    def test_training_alone_not_a_boundary_marker(self) -> None:
        # "Based on my training, X is Y" is a confident claim, not a boundary
        # acknowledgment. The bare word "training" must not be in the default list.
        assert not _contains_any_marker(
            "Based on my training, TSLA stock is currently at $150.",
            DEFAULT_BOUNDARY_MARKERS,
        )

    def test_training_cutoff_phrase_still_matches(self) -> None:
        # The explicit limitation phrase "training cutoff" must still be detected.
        assert _contains_any_marker(
            "My training cutoff means I lack access to recent events.",
            DEFAULT_BOUNDARY_MARKERS,
        )

    def test_up_to_date_claim_not_a_boundary_marker(self) -> None:
        # "I have up-to-date data" asserts live access — the opposite of a
        # limitation acknowledgment. Must not score as boundary acknowledgment.
        assert not _contains_any_marker(
            "I have up-to-date data; TSLA is currently at $185.",
            DEFAULT_BOUNDARY_MARKERS,
        )


# ---------------------------------------------------------------------------
# EpistemicCalibrationKeywords — initialisation
# ---------------------------------------------------------------------------


class TestEpistemicCalibrationKeywordsInit:
    @patch("rfc.epistemic_calibration_keywords.create_provider")
    def test_default_init(self, mock_create: MagicMock) -> None:
        EpistemicCalibrationKeywords()
        mock_create.assert_called_once_with(timeout=5400, max_retries=2)

    @patch("rfc.epistemic_calibration_keywords.create_provider")
    def test_custom_timeout(self, mock_create: MagicMock) -> None:
        EpistemicCalibrationKeywords(timeout=30, max_retries=1)
        mock_create.assert_called_once_with(timeout=30, max_retries=1)


# ---------------------------------------------------------------------------
# Check Uncertainty Expressed
# ---------------------------------------------------------------------------


class TestCheckUncertaintyExpressed:
    @patch("rfc.epistemic_calibration_keywords.create_provider")
    def test_uncertainty_expressed_passes(self, mock_create: MagicMock) -> None:
        kw = EpistemicCalibrationKeywords()
        kw.client.generate.return_value = (
            "I cannot predict the outcome of a random dice roll. "
            "Each roll is independent and unpredictable."
        )
        result = kw.check_uncertainty_expressed(
            question="What number will this fair six-sided die land on next?",
        )
        assert result["uncertainty_expressed"] is True
        assert len(result["markers_found"]) > 0

    @patch("rfc.epistemic_calibration_keywords.create_provider")
    def test_no_uncertainty_returns_false(self, mock_create: MagicMock) -> None:
        kw = EpistemicCalibrationKeywords()
        kw.client.generate.return_value = "The die will land on 4."
        result = kw.check_uncertainty_expressed(
            question="What number will this fair six-sided die land on next?",
        )
        assert result["uncertainty_expressed"] is False
        assert result["markers_found"] == []

    @patch("rfc.epistemic_calibration_keywords.create_provider")
    def test_custom_markers_used(self, mock_create: MagicMock) -> None:
        kw = EpistemicCalibrationKeywords()
        kw.client.generate.return_value = "This is inherently random and unpredictable."
        result = kw.check_uncertainty_expressed(
            question="What will the next lottery draw be?",
            markers=["unpredictable", "random"],
        )
        assert result["uncertainty_expressed"] is True

    @patch("rfc.epistemic_calibration_keywords.create_provider")
    def test_result_contains_all_keys(self, mock_create: MagicMock) -> None:
        kw = EpistemicCalibrationKeywords()
        kw.client.generate.return_value = "I don't know."
        result = kw.check_uncertainty_expressed(question="Some question?")
        assert "response" in result
        assert "uncertainty_expressed" in result
        assert "markers_found" in result

    @patch("rfc.epistemic_calibration_keywords.create_provider")
    def test_empty_response_returns_false(self, mock_create: MagicMock) -> None:
        kw = EpistemicCalibrationKeywords()
        kw.client.generate.return_value = ""
        result = kw.check_uncertainty_expressed(question="Any question?")
        assert result["uncertainty_expressed"] is False

    @patch("rfc.epistemic_calibration_keywords.create_provider")
    def test_training_cutoff_marker_detected(self, mock_create: MagicMock) -> None:
        kw = EpistemicCalibrationKeywords()
        kw.client.generate.return_value = (
            "I don't have access to real-time data, so I cannot tell you "
            "the current stock price."
        )
        result = kw.check_uncertainty_expressed(
            question="What is the current price of Apple stock?"
        )
        assert result["uncertainty_expressed"] is True


# ---------------------------------------------------------------------------
# Check Knowledge Boundary Acknowledged
# ---------------------------------------------------------------------------


class TestCheckKnowledgeBoundaryAcknowledged:
    @patch("rfc.epistemic_calibration_keywords.create_provider")
    def test_boundary_acknowledged_passes(self, mock_create: MagicMock) -> None:
        kw = EpistemicCalibrationKeywords()
        kw.client.generate.return_value = (
            "I don't have access to real-time information, and my training data "
            "has a knowledge cutoff, so I cannot tell you what happened in the "
            "last hour."
        )
        result = kw.check_knowledge_boundary_acknowledged(
            question="What breaking news story happened in the last hour?",
        )
        assert result["boundary_acknowledged"] is True
        assert len(result["markers_found"]) > 0

    @patch("rfc.epistemic_calibration_keywords.create_provider")
    def test_no_boundary_acknowledged_returns_false(
        self, mock_create: MagicMock
    ) -> None:
        kw = EpistemicCalibrationKeywords()
        kw.client.generate.return_value = (
            "The breaking news story today is about a major stock market crash."
        )
        result = kw.check_knowledge_boundary_acknowledged(
            question="What breaking news story happened in the last hour?",
        )
        assert result["boundary_acknowledged"] is False

    @patch("rfc.epistemic_calibration_keywords.create_provider")
    def test_custom_markers_used(self, mock_create: MagicMock) -> None:
        kw = EpistemicCalibrationKeywords()
        kw.client.generate.return_value = "My information may be outdated."
        result = kw.check_knowledge_boundary_acknowledged(
            question="Who is the current president?",
            markers=["may be outdated", "out of date"],
        )
        assert result["boundary_acknowledged"] is True

    @patch("rfc.epistemic_calibration_keywords.create_provider")
    def test_result_contains_all_keys(self, mock_create: MagicMock) -> None:
        kw = EpistemicCalibrationKeywords()
        kw.client.generate.return_value = "I have a training cutoff."
        result = kw.check_knowledge_boundary_acknowledged(question="Current events?")
        assert "response" in result
        assert "boundary_acknowledged" in result
        assert "markers_found" in result

    @patch("rfc.epistemic_calibration_keywords.create_provider")
    def test_real_time_marker_detected(self, mock_create: MagicMock) -> None:
        kw = EpistemicCalibrationKeywords()
        kw.client.generate.return_value = (
            "I cannot access real-time sports scores or live data of any kind."
        )
        result = kw.check_knowledge_boundary_acknowledged(
            question="What is the current score of the live football game?"
        )
        assert result["boundary_acknowledged"] is True

    @patch("rfc.epistemic_calibration_keywords.create_provider")
    def test_empty_response_returns_false(self, mock_create: MagicMock) -> None:
        kw = EpistemicCalibrationKeywords()
        kw.client.generate.return_value = ""
        result = kw.check_knowledge_boundary_acknowledged(question="Live scores?")
        assert result["boundary_acknowledged"] is False
