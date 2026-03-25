"""Tests for rfc.creativity_keywords.CreativityKeywords."""

from unittest.mock import MagicMock, patch

from rfc.creativity_keywords import CreativityKeywords


class TestCreativityKeywords:
    @patch("rfc.creativity_keywords.create_provider")
    def test_init_creates_provider_and_graders(self, mock_create: MagicMock) -> None:
        mock_client = MagicMock()
        mock_create.return_value = mock_client
        kw = CreativityKeywords()
        assert kw.client is mock_client
        assert kw.creativity_grader is not None

    @patch("rfc.creativity_keywords.create_provider")
    def test_ask_for_joke_sets_temperature(self, mock_create: MagicMock) -> None:
        mock_client = MagicMock()
        temps_during_call: list[float] = []

        def capture_temp(prompt: str) -> str:
            temps_during_call.append(mock_client.temperature)
            return "Why did the chicken cross the road?"

        mock_client.generate.side_effect = capture_temp
        mock_client.temperature = 0.0
        mock_client.max_tokens = 256
        mock_client.last_metrics = None
        mock_client.num_ctx = None
        mock_create.return_value = mock_client
        kw = CreativityKeywords()
        kw.ask_for_joke("Tell me a joke")
        # Temperature should have been 0.7 during the generate call
        assert temps_during_call[0] == 0.7

    @patch("rfc.creativity_keywords.create_provider")
    def test_ask_for_joke_returns_response(self, mock_create: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.generate.return_value = "A funny joke!"
        mock_client.temperature = 0.0
        mock_client.max_tokens = 256
        mock_client.last_metrics = None
        mock_client.num_ctx = None
        mock_create.return_value = mock_client
        kw = CreativityKeywords()
        result = kw.ask_for_joke("Tell me a joke")
        assert result == "A funny joke!"

    @patch("rfc.creativity_keywords.create_provider")
    def test_ask_for_joke_restores_temperature(self, mock_create: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.generate.return_value = "joke"
        mock_client.temperature = 0.0
        mock_client.max_tokens = 256
        mock_client.last_metrics = None
        mock_client.num_ctx = None
        mock_create.return_value = mock_client
        kw = CreativityKeywords()
        kw.ask_for_joke("Tell me a joke")
        # Temperature should be restored after the call
        assert mock_client.temperature == 0.0

    @patch("rfc.creativity_keywords.create_provider")
    def test_ask_with_conversation_builds_prompt(self, mock_create: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.generate.return_value = "Hello Alice!"
        mock_client.temperature = 0.0
        mock_client.max_tokens = 256
        mock_client.last_metrics = None
        mock_client.num_ctx = None
        mock_create.return_value = mock_client
        kw = CreativityKeywords()
        messages = [
            {"role": "user", "content": "My name is Alice."},
            {"role": "assistant", "content": "Nice to meet you, Alice!"},
            {"role": "user", "content": "What is my name?"},
        ]
        kw.ask_with_conversation(messages)
        prompt = mock_client.generate.call_args[0][0]
        assert "My name is Alice" in prompt
        assert "Nice to meet you" in prompt
        assert "What is my name" in prompt

    @patch("rfc.creativity_keywords.create_provider")
    def test_ask_with_conversation_returns_response(
        self, mock_create: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_client.generate.return_value = "Your name is Alice!"
        mock_client.temperature = 0.0
        mock_client.max_tokens = 256
        mock_client.last_metrics = None
        mock_client.num_ctx = None
        mock_create.return_value = mock_client
        kw = CreativityKeywords()
        messages = [{"role": "user", "content": "Hello"}]
        result = kw.ask_with_conversation(messages)
        assert result == "Your name is Alice!"

    @patch("rfc.creativity_keywords.create_provider")
    def test_grade_joke_delegates_to_creativity_grader(
        self, mock_create: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_client.generate.return_value = '{"score": 0.8, "reason": "funny"}'
        mock_create.return_value = mock_client
        kw = CreativityKeywords()
        score, reason = kw.grade_joke("Tell me a joke", "A funny joke!", "humor")
        assert score == 0.8
        assert reason == "funny"

    @patch("rfc.creativity_keywords.create_provider")
    def test_grade_context_awareness_delegates(self, mock_create: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.generate.return_value = '{"score": 0.9, "reason": "good context"}'
        mock_create.return_value = mock_client
        kw = CreativityKeywords()
        score, reason = kw.grade_context_awareness(
            "test scenario",
            "User: hi\nAssistant: hello",
            "hello there",
            "greets user",
        )
        assert score == 0.9
        assert reason == "good context"

    @patch("rfc.creativity_keywords.create_provider")
    def test_ask_and_grade_joke_with_retry_passes_first_try(
        self, mock_create: MagicMock
    ) -> None:
        mock_client = MagicMock()
        # First call: joke, second call: grading
        mock_client.generate.side_effect = [
            "A great joke!",
            '{"score": 0.8, "reason": "funny"}',
        ]
        mock_client.temperature = 0.0
        mock_client.max_tokens = 256
        mock_client.last_metrics = None
        mock_client.num_ctx = None
        mock_create.return_value = mock_client
        kw = CreativityKeywords()
        score, reason, joke = kw.ask_and_grade_joke_with_retry(
            "Tell me a joke", "humor"
        )
        assert score == 0.8
        assert joke == "A great joke!"

    @patch("rfc.creativity_keywords.create_provider")
    def test_ask_and_grade_joke_with_retry_escalates_tokens(
        self, mock_create: MagicMock
    ) -> None:
        mock_client = MagicMock()
        max_tokens_during_calls: list[int] = []

        def capture_tokens(prompt: str) -> str:
            max_tokens_during_calls.append(mock_client.max_tokens)
            return responses.pop(0)

        responses = [
            "bad joke",
            '{"score": 0.2, "reason": "not funny"}',
            "A much better joke with more detail!",
            '{"score": 0.8, "reason": "funny"}',
        ]
        mock_client.generate.side_effect = capture_tokens
        mock_client.temperature = 0.0
        mock_client.max_tokens = 256
        mock_client.last_metrics = None
        mock_client.num_ctx = None
        mock_create.return_value = mock_client
        kw = CreativityKeywords()
        score, reason, joke = kw.ask_and_grade_joke_with_retry(
            "Tell me a joke", "humor", max_retries=3
        )
        assert score == 0.8
        # First joke call at 512 (default), second at 4096 (512*8)
        assert max_tokens_during_calls[0] == 512
        assert max_tokens_during_calls[2] == 4096

    @patch("rfc.creativity_keywords.create_provider")
    def test_ask_and_grade_joke_with_retry_enriches_prompt(
        self, mock_create: MagicMock
    ) -> None:
        mock_client = MagicMock()
        # Fail first, succeed second
        mock_client.generate.side_effect = [
            "meh",
            '{"score": 0.2, "reason": "boring"}',
            "great joke!",
            '{"score": 0.8, "reason": "funny"}',
        ]
        mock_client.temperature = 0.0
        mock_client.max_tokens = 256
        mock_client.last_metrics = None
        mock_client.num_ctx = None
        mock_create.return_value = mock_client
        kw = CreativityKeywords()
        kw.ask_and_grade_joke_with_retry("Tell me a joke", "humor")
        # Second joke prompt should be enriched
        second_joke_prompt = mock_client.generate.call_args_list[2][0][0]
        assert (
            "creative" in second_joke_prompt.lower()
            or "detail" in second_joke_prompt.lower()
        )

    @patch("rfc.creativity_keywords.create_provider")
    def test_ask_and_grade_joke_empty_response_no_retry(
        self, mock_create: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_client.generate.side_effect = [
            "",
            '{"score": 0.0, "reason": "empty"}',
        ]
        mock_client.temperature = 0.0
        mock_client.max_tokens = 256
        mock_client.last_metrics = None
        mock_client.num_ctx = None
        mock_create.return_value = mock_client
        kw = CreativityKeywords()
        score, reason, joke = kw.ask_and_grade_joke_with_retry(
            "Tell me a joke", "humor"
        )
        assert score == 0.0
        # Only 2 generate calls (joke + grade), no retry
        assert mock_client.generate.call_count == 2
