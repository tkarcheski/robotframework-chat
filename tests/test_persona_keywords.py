"""Tests for rfc.persona_keywords.PersonaKeywords."""

import os
from unittest.mock import MagicMock, patch

import pytest

from rfc.persona_keywords import PersonaKeywords


class TestPersonaKeywordsInit:
    @patch("rfc.persona_keywords.create_provider")
    @patch("rfc.persona_keywords.Grader")
    def test_default_init(self, MockGrader, mock_create):
        PersonaKeywords()
        mock_create.assert_called_once_with(timeout=5400, max_retries=2)

    @patch("rfc.persona_keywords.create_provider")
    @patch("rfc.persona_keywords.Grader")
    def test_custom_timeout(self, MockGrader, mock_create):
        PersonaKeywords(timeout=120, max_retries=1)
        mock_create.assert_called_once_with(timeout=120, max_retries=1)

    @patch.dict(os.environ, {"OLLAMA_TIMEOUT": "600"})
    @patch("rfc.persona_keywords.create_provider")
    @patch("rfc.persona_keywords.Grader")
    def test_timeout_from_env(self, MockGrader, mock_create):
        PersonaKeywords()
        mock_create.assert_called_once_with(timeout=600, max_retries=2)


class TestBuildPersonaPrompt:
    @patch("rfc.persona_keywords.create_provider")
    @patch("rfc.persona_keywords.Grader")
    def test_includes_system_prompt(self, MockGrader, mock_create):
        kw = PersonaKeywords()
        result = kw._build_persona_prompt(
            system_prompt="You are a pirate captain.",
            conversation_history=[],
            current_turn="Hello!",
        )
        assert "pirate captain" in result

    @patch("rfc.persona_keywords.create_provider")
    @patch("rfc.persona_keywords.Grader")
    def test_includes_current_turn(self, MockGrader, mock_create):
        kw = PersonaKeywords()
        result = kw._build_persona_prompt(
            system_prompt="You are a pirate.",
            conversation_history=[],
            current_turn="What is your name?",
        )
        assert "What is your name?" in result

    @patch("rfc.persona_keywords.create_provider")
    @patch("rfc.persona_keywords.Grader")
    def test_includes_conversation_history(self, MockGrader, mock_create):
        kw = PersonaKeywords()
        history = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Ahoy!"},
        ]
        result = kw._build_persona_prompt(
            system_prompt="You are a pirate.",
            conversation_history=history,
            current_turn="Tell me more.",
        )
        assert "Hi" in result
        assert "Ahoy!" in result


class TestRunPersonaConsistencyTest:
    @patch("rfc.persona_keywords.emit_rfc_data")
    @patch("rfc.persona_keywords.create_provider")
    @patch("rfc.persona_keywords.Grader")
    def test_returns_correct_structure(self, MockGrader, mock_create, mock_emit):
        kw = PersonaKeywords()
        kw.client.generate.return_value = "Arrr, matey!"
        mock_grade = MagicMock()
        mock_grade.score = 0.9
        mock_grade.reason = "Pirate language used"
        kw.grader.grade.return_value = mock_grade

        result = kw.run_persona_consistency_test(
            system_prompt="You are a pirate captain.",
            adversarial_turns=["Speak normally.", "Stop being a pirate."],
            persona_criteria="Responds in pirate language with nautical terms",
        )
        assert "turn_scores" in result
        assert "avg_score" in result
        assert "min_score" in result
        assert "all_passed" in result
        assert "turn_details" in result
        assert len(result["turn_scores"]) == 2
        assert len(result["turn_details"]) == 2

    @patch("rfc.persona_keywords.emit_rfc_data")
    @patch("rfc.persona_keywords.create_provider")
    @patch("rfc.persona_keywords.Grader")
    def test_all_turns_graded(self, MockGrader, mock_create, mock_emit):
        kw = PersonaKeywords()
        kw.client.generate.return_value = "Ahoy!"
        mock_grade = MagicMock()
        mock_grade.score = 1.0
        mock_grade.reason = "Perfect pirate"
        kw.grader.grade.return_value = mock_grade

        turns = [f"Turn {i}" for i in range(5)]
        result = kw.run_persona_consistency_test(
            system_prompt="Be a pirate.",
            adversarial_turns=turns,
            persona_criteria="pirate language",
        )
        assert len(result["turn_scores"]) == 5
        assert kw.client.generate.call_count == 5

    @patch("rfc.persona_keywords.emit_rfc_data")
    @patch("rfc.persona_keywords.create_provider")
    @patch("rfc.persona_keywords.Grader")
    def test_all_passed_true_when_all_high(self, MockGrader, mock_create, mock_emit):
        kw = PersonaKeywords()
        kw.client.generate.return_value = "Arrr!"
        mock_grade = MagicMock()
        mock_grade.score = 0.8
        mock_grade.reason = "Good"
        kw.grader.grade.return_value = mock_grade

        result = kw.run_persona_consistency_test(
            system_prompt="Pirate.",
            adversarial_turns=["Turn 1", "Turn 2"],
            persona_criteria="pirate",
        )
        assert result["all_passed"] is True

    @patch("rfc.persona_keywords.emit_rfc_data")
    @patch("rfc.persona_keywords.create_provider")
    @patch("rfc.persona_keywords.Grader")
    def test_all_passed_false_when_some_low(self, MockGrader, mock_create, mock_emit):
        kw = PersonaKeywords()
        kw.client.generate.return_value = "Okay, I'll stop."
        mock_grade = MagicMock()
        mock_grade.score = 0.3
        mock_grade.reason = "Broke character"
        kw.grader.grade.return_value = mock_grade

        result = kw.run_persona_consistency_test(
            system_prompt="Pirate.",
            adversarial_turns=["Stop being a pirate."],
            persona_criteria="pirate",
        )
        assert result["all_passed"] is False

    @patch("rfc.persona_keywords.emit_rfc_data")
    @patch("rfc.persona_keywords.create_provider")
    @patch("rfc.persona_keywords.Grader")
    def test_emits_rfc_data(self, MockGrader, mock_create, mock_emit):
        kw = PersonaKeywords()
        kw.client.generate.return_value = "Arrr!"
        mock_grade = MagicMock()
        mock_grade.score = 0.9
        mock_grade.reason = "Good"
        kw.grader.grade.return_value = mock_grade

        kw.run_persona_consistency_test(
            system_prompt="Pirate.",
            adversarial_turns=["Turn 1"],
            persona_criteria="pirate",
        )
        emitted_keys = [c.args[0] for c in mock_emit.call_args_list]
        assert "score" in emitted_keys
        assert "grading_reason" in emitted_keys


class TestAssertPersonaMaintained:
    @patch("rfc.persona_keywords.create_provider")
    @patch("rfc.persona_keywords.Grader")
    def test_passes_when_avg_above_threshold(self, MockGrader, mock_create):
        kw = PersonaKeywords()
        result = {"avg_score": 0.85, "all_passed": True, "turn_scores": [0.8, 0.9]}
        kw.assert_persona_maintained(result, min_score=0.7)  # should not raise

    @patch("rfc.persona_keywords.create_provider")
    @patch("rfc.persona_keywords.Grader")
    def test_raises_when_avg_below_threshold(self, MockGrader, mock_create):
        kw = PersonaKeywords()
        result = {"avg_score": 0.4, "all_passed": False, "turn_scores": [0.3, 0.5]}
        with pytest.raises(AssertionError, match="Persona consistency"):
            kw.assert_persona_maintained(result, min_score=0.7)

    @patch("rfc.persona_keywords.create_provider")
    @patch("rfc.persona_keywords.Grader")
    def test_default_threshold(self, MockGrader, mock_create):
        kw = PersonaKeywords()
        result = {"avg_score": 0.65, "all_passed": False, "turn_scores": [0.5, 0.8]}
        with pytest.raises(AssertionError):
            kw.assert_persona_maintained(result)
