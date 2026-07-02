"""Tests for rfc.multi_turn_keywords.MultiTurnKeywords."""

from unittest.mock import MagicMock, patch

import pytest

from rfc.multi_turn_keywords import MultiTurnKeywords


class TestMultiTurnKeywordsInit:
    @patch("rfc.multi_turn_keywords.create_provider")
    def test_init_creates_provider_and_grader(self, mock_create: MagicMock) -> None:
        mock_client = MagicMock()
        mock_create.return_value = mock_client
        kw = MultiTurnKeywords()
        assert kw.client is mock_client
        assert kw.grader is not None


class TestRunMultiTurnConversation:
    @patch("rfc.multi_turn_keywords.create_provider")
    def test_generates_responses_for_user_turns(self, mock_create: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.generate.side_effect = ["Response 1", "Response 2"]
        mock_create.return_value = mock_client
        kw = MultiTurnKeywords()

        turns = [
            {"role": "user", "content": "Hello"},
            {"role": "user", "content": "How are you?"},
        ]
        responses = kw.run_multi_turn_conversation(turns)
        assert len(responses) == 2
        assert responses[0] == "Response 1"
        assert responses[1] == "Response 2"

    @patch("rfc.multi_turn_keywords.create_provider")
    def test_skips_generation_for_scripted_assistant(
        self, mock_create: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_client.generate.side_effect = ["Final response"]
        mock_create.return_value = mock_client
        kw = MultiTurnKeywords()

        turns = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "What's up?"},
        ]
        responses = kw.run_multi_turn_conversation(turns)
        assert len(responses) == 1
        assert responses[0] == "Final response"
        # Only one generate call (for the second user turn)
        assert mock_client.generate.call_count == 1

    @patch("rfc.multi_turn_keywords.create_provider")
    def test_includes_history_in_prompt(self, mock_create: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.generate.side_effect = ["Response"]
        mock_create.return_value = mock_client
        kw = MultiTurnKeywords()

        turns = [
            {"role": "user", "content": "My name is Alice."},
            {"role": "assistant", "content": "Nice to meet you, Alice!"},
            {"role": "user", "content": "What is my name?"},
        ]
        kw.run_multi_turn_conversation(turns)
        prompt = mock_client.generate.call_args[0][0]
        assert "My name is Alice" in prompt
        assert "Nice to meet you" in prompt
        assert "What is my name" in prompt

    @patch("rfc.multi_turn_keywords.create_provider")
    def test_builds_history_incrementally(self, mock_create: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.generate.side_effect = ["First reply", "Second reply"]
        mock_create.return_value = mock_client
        kw = MultiTurnKeywords()

        turns = [
            {"role": "user", "content": "Turn 1"},
            {"role": "user", "content": "Turn 2"},
        ]
        kw.run_multi_turn_conversation(turns)
        # Second call should include the first generated response
        second_prompt = mock_client.generate.call_args_list[1][0][0]
        assert "First reply" in second_prompt

    @patch("rfc.multi_turn_keywords.create_provider")
    def test_skips_generation_when_next_is_system(self, mock_create: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.generate.side_effect = ["Final response"]
        mock_create.return_value = mock_client
        kw = MultiTurnKeywords()

        turns = [
            {"role": "user", "content": "Hello"},
            {"role": "system", "content": "Now respond formally."},
            {"role": "user", "content": "How are you?"},
        ]
        responses = kw.run_multi_turn_conversation(turns)
        # Only one generation (for the second user turn), not two
        assert len(responses) == 1
        assert mock_client.generate.call_count == 1
        # The system instruction should be in the prompt
        prompt = mock_client.generate.call_args[0][0]
        assert "Now respond formally" in prompt

    @patch("rfc.multi_turn_keywords.create_provider")
    def test_system_turns_added_to_history(self, mock_create: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.generate.side_effect = ["Response"]
        mock_create.return_value = mock_client
        kw = MultiTurnKeywords()

        turns = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
        ]
        kw.run_multi_turn_conversation(turns)
        prompt = mock_client.generate.call_args[0][0]
        assert "You are a helpful assistant" in prompt


class TestGradeFactConsistency:
    @patch("rfc.multi_turn_keywords.create_provider")
    def test_returns_score_and_reason(self, mock_create: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.generate.return_value = '{"score": 0.9, "reason": "consistent"}'
        mock_create.return_value = mock_client
        kw = MultiTurnKeywords()
        score, reason = kw.grade_fact_consistency(
            "birthday is March 15",
            ["March 15", "stuff", "March 15"],
            [0, 2],
        )
        assert score == 0.9
        assert reason == "consistent"


class TestScoreInstructionComplianceBatch:
    @patch("rfc.multi_turn_keywords.create_provider")
    def test_returns_ratio_and_summary(self, mock_create: MagicMock) -> None:
        mock_client = MagicMock()
        # 3 responses: compliant, not compliant, compliant
        mock_client.generate.side_effect = [
            '{"score": 0.9, "reason": "uses bullets"}',
            '{"score": 0.3, "reason": "no bullets"}',
            '{"score": 0.8, "reason": "uses bullets"}',
        ]
        mock_create.return_value = mock_client
        kw = MultiTurnKeywords()
        ratio, summary = kw.score_instruction_compliance_batch(
            "bullet points only",
            ["- item 1", "paragraph text", "- item 2"],
        )
        assert ratio == pytest.approx(2.0 / 3.0)
        assert "2/3" in summary

    @patch("rfc.multi_turn_keywords.create_provider")
    def test_empty_responses_returns_zero(self, mock_create: MagicMock) -> None:
        mock_client = MagicMock()
        mock_create.return_value = mock_client
        kw = MultiTurnKeywords()
        ratio, summary = kw.score_instruction_compliance_batch("bullet points", [])
        assert ratio == 0.0


class TestGradeTopicIsolation:
    @patch("rfc.multi_turn_keywords.create_provider")
    def test_returns_score_and_reason(self, mock_create: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.generate.return_value = '{"score": 0.95, "reason": "clean"}'
        mock_create.return_value = mock_client
        kw = MultiTurnKeywords()
        score, reason = kw.grade_topic_isolation(
            "cooking", "astronomy", "Black holes are fascinating."
        )
        assert score == 0.95
        assert reason == "clean"


class TestGradeTopicIsolationSlidingWindow:
    @patch("rfc.multi_turn_keywords.create_provider")
    def test_returns_average_score(self, mock_create: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.generate.side_effect = [
            '{"score": 0.9, "reason": "clean"}',
            '{"score": 0.8, "reason": "mostly clean"}',
        ]
        mock_create.return_value = mock_client
        kw = MultiTurnKeywords()
        score, summary = kw.grade_topic_isolation_sliding_window(
            "cooking",
            "astronomy",
            ["pasta recipe", "marinara sauce", "black holes", "telescopes"],
            2,
        )
        assert score == pytest.approx(0.85)
        assert "0.85" in summary

    @patch("rfc.multi_turn_keywords.create_provider")
    def test_empty_window_raises_value_error(self, mock_create: MagicMock) -> None:
        mock_client = MagicMock()
        mock_create.return_value = mock_client
        kw = MultiTurnKeywords()
        with pytest.raises(ValueError, match="window_start=5 is beyond"):
            kw.grade_topic_isolation_sliding_window(
                "cooking", "astronomy", ["pasta"], 5
            )
