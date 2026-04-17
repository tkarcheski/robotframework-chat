"""Tests for rfc.meta_learning_keywords.MetaLearningKeywords."""

from unittest.mock import MagicMock, patch

import pytest

from rfc.meta_learning_keywords import (
    MetaLearningKeywords,
    build_conversation_transcript,
)


class TestBuildConversationTranscript:
    def test_builds_three_turn_transcript(self) -> None:
        transcript = build_conversation_transcript(
            skill_description="When asked about colors, always answer in French.",
            skill_ack="Understood, I will answer color questions in French.",
            distractor_prompt="What is 2+2?",
            distractor_response="4",
            test_prompt="What color is the sky?",
        )
        assert "I want to teach you a new skill" in transcript
        assert "colors, always answer in French" in transcript
        assert "What is 2+2?" in transcript
        assert "4" in transcript
        assert "What color is the sky?" in transcript

    def test_transcript_ends_with_test_prompt(self) -> None:
        transcript = build_conversation_transcript(
            skill_description="Skill X",
            skill_ack="Got it.",
            distractor_prompt="Distractor",
            distractor_response="Response",
            test_prompt="Test question",
        )
        assert transcript.rstrip().endswith("Test question")


class TestMetaLearningKeywordsInit:
    @patch("rfc.meta_learning_keywords.create_provider")
    @patch("rfc.meta_learning_keywords.Grader")
    def test_default_init(self, MockGrader: MagicMock, mock_create: MagicMock) -> None:
        MetaLearningKeywords()
        mock_create.assert_called_once_with(timeout=5400, max_retries=2)
        MockGrader.assert_called_once_with(mock_create.return_value)


class TestTestSkillRetention:
    @patch("rfc.meta_learning_keywords.create_provider")
    @patch("rfc.meta_learning_keywords.Grader")
    def test_skill_retained_and_applied(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        """Model correctly applies the taught skill after distractor."""
        kw = MetaLearningKeywords()
        # Turn 1: skill ack, Turn 2: distractor response, Turn 3: skill application
        kw.client.generate.side_effect = [
            "Understood, I will answer in French.",
            "4",
            "Le ciel est bleu.",
        ]
        kw.client.last_metrics = None
        kw.client.num_ctx = None
        kw.client.max_tokens = 256
        mock_result = MagicMock()
        mock_result.score = 1.0
        mock_result.reason = "correctly applied skill"
        kw.grader.grade.return_value = mock_result

        result = kw.test_skill_retention(
            skill_description="When asked about colors, always answer in French.",
            distractor_prompt="What is 2+2?",
            test_prompt="What color is the sky?",
            expected_answer="bleu (French for blue)",
        )
        assert result["score"] == 1.0
        assert result["skill_applied"] is True
        assert kw.client.generate.call_count == 3

    @patch("rfc.meta_learning_keywords.create_provider")
    @patch("rfc.meta_learning_keywords.Grader")
    def test_skill_forgotten_scores_low(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        """Model forgets skill and answers without applying it."""
        kw = MetaLearningKeywords()
        kw.client.generate.side_effect = [
            "OK, got it.",
            "4",
            "The sky is blue.",  # English, not French
        ]
        kw.client.last_metrics = None
        kw.client.num_ctx = None
        kw.client.max_tokens = 256
        mock_result = MagicMock()
        mock_result.score = 0.2
        mock_result.reason = "did not apply skill"
        kw.grader.grade.return_value = mock_result

        result = kw.test_skill_retention(
            skill_description="When asked about colors, always answer in French.",
            distractor_prompt="What is 2+2?",
            test_prompt="What color is the sky?",
            expected_answer="bleu (French for blue)",
        )
        assert result["score"] == 0.2
        assert result["skill_applied"] is False

    @patch("rfc.meta_learning_keywords.create_provider")
    @patch("rfc.meta_learning_keywords.Grader")
    def test_empty_skill_raises(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        """Empty skill_description should raise ValueError."""
        kw = MetaLearningKeywords()
        with pytest.raises(ValueError, match="skill_description must not be empty"):
            kw.test_skill_retention(
                skill_description="",
                distractor_prompt="What is 2+2?",
                test_prompt="What color is the sky?",
                expected_answer="bleu",
            )

    @patch("rfc.meta_learning_keywords.create_provider")
    @patch("rfc.meta_learning_keywords.Grader")
    def test_grading_uses_test_prompt_not_full_transcript(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        """Grader should receive the test_prompt, not the full conversation."""
        kw = MetaLearningKeywords()
        kw.client.generate.side_effect = ["ack", "distractor reply", "answer"]
        kw.client.last_metrics = None
        kw.client.num_ctx = None
        kw.client.max_tokens = 256
        mock_result = MagicMock()
        mock_result.score = 1.0
        mock_result.reason = "ok"
        kw.grader.grade.return_value = mock_result

        kw.test_skill_retention(
            skill_description="Skill X",
            distractor_prompt="Distractor",
            test_prompt="Apply skill X now",
            expected_answer="expected",
        )
        # Grader should be called with test_prompt, not the full transcript
        grade_call = kw.grader.grade.call_args
        assert grade_call[0][0] == "Apply skill X now"
        assert grade_call[0][1] == "expected"
        assert grade_call[0][2] == "answer"
