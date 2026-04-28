"""Tests for rfc.creativity_keywords.CreativityKeywords."""

from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

from rfc.creativity_keywords import CreativityKeywords
from rfc.exceptions import EmptyLLMResponseError, MissingEnvironmentError


@pytest.fixture
def grader_models_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Set CREATIVITY_GRADER_MODELS so the panel grader can be built."""
    monkeypatch.setenv("CREATIVITY_GRADER_MODELS", "judge1,judge2,judge3")
    yield


@pytest.fixture
def no_grader_models_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Ensure CREATIVITY_GRADER_MODELS is unset."""
    monkeypatch.delenv("CREATIVITY_GRADER_MODELS", raising=False)
    yield


def _make_client_mock(
    generate_side_effect: object = None,
    generate_return: object = None,
) -> MagicMock:
    client = MagicMock()
    if generate_side_effect is not None:
        client.generate.side_effect = generate_side_effect
    elif generate_return is not None:
        client.generate.return_value = generate_return
    client.temperature = 0.0
    client.max_tokens = 256
    client.last_metrics = None
    client.num_ctx = None
    client.model = "gen-model"
    return client


class TestCreativityKeywords:
    @patch("rfc.creativity_keywords.create_provider")
    def test_init_does_not_eagerly_build_panel(self, mock_create: MagicMock) -> None:
        """Panel grader is lazy — instantiating must not require env var (#260)."""
        mock_create.return_value = _make_client_mock()
        kw = CreativityKeywords()
        assert kw.client is mock_create.return_value
        # Internal panel slot is empty until grade_joke is called.
        assert kw._creativity_grader is None

    @patch("rfc.creativity_keywords.create_provider")
    def test_grade_joke_skips_when_grader_models_unset(
        self,
        mock_create: MagicMock,
        no_grader_models_env: None,
    ) -> None:
        """Without CREATIVITY_GRADER_MODELS, grading skips (#260)."""
        mock_create.return_value = _make_client_mock(
            generate_return='{"score": 0.8, "reason": "x"}'
        )
        kw = CreativityKeywords()
        with pytest.raises(MissingEnvironmentError) as exc_info:
            kw.grade_joke("Tell me a joke", "joke text", "humor")
        assert exc_info.value.ROBOT_SKIP is True
        assert "CREATIVITY_GRADER_MODELS" in str(exc_info.value)

    @patch("rfc.creativity_keywords.create_provider")
    def test_grade_joke_rejects_too_few_models(
        self,
        mock_create: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("CREATIVITY_GRADER_MODELS", "only-one")
        mock_create.return_value = _make_client_mock()
        kw = CreativityKeywords()
        with pytest.raises(ValueError, match="at least 3 distinct models"):
            kw.grade_joke("Tell me a joke", "joke text", "humor")

    @patch("rfc.creativity_keywords.create_provider")
    def test_grade_joke_rejects_duplicate_judges(
        self,
        mock_create: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Duplicates must not satisfy the 3+ panel requirement (#260)."""
        monkeypatch.setenv("CREATIVITY_GRADER_MODELS", "judge1,judge1,judge1")
        mock_create.return_value = _make_client_mock()
        kw = CreativityKeywords()
        with pytest.raises(ValueError, match="at least 3 distinct models"):
            kw.grade_joke("Tell me a joke", "joke text", "humor")

    @patch("rfc.creativity_keywords.create_provider")
    def test_grade_joke_rejects_generation_model_in_panel(
        self,
        mock_create: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Generation model in the panel = self-grading bias — reject (#260)."""
        monkeypatch.setenv("CREATIVITY_GRADER_MODELS", "judge1,gen-model,judge2")
        mock_create.return_value = _make_client_mock()  # client.model = "gen-model"
        kw = CreativityKeywords()
        with pytest.raises(ValueError, match="must not contain the generation model"):
            kw.grade_joke("Tell me a joke", "joke text", "humor")

    @patch("rfc.creativity_keywords.create_provider")
    def test_grade_joke_rejects_generation_model_alias(
        self,
        mock_create: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """':latest' alias of the generation model must also be rejected (#260)."""
        monkeypatch.setenv("CREATIVITY_GRADER_MODELS", "gen-model:latest,judge2,judge3")
        mock_create.return_value = _make_client_mock()  # client.model = "gen-model"
        kw = CreativityKeywords()
        with pytest.raises(ValueError, match="must not contain the generation model"):
            kw.grade_joke("Tell me a joke", "joke text", "humor")

    @patch("rfc.creativity_keywords.create_provider")
    def test_grade_joke_treats_implicit_latest_as_duplicate(
        self,
        mock_create: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """'judge1' and 'judge1:latest' canonicalise to the same model (#260)."""
        monkeypatch.setenv("CREATIVITY_GRADER_MODELS", "judge1,judge1:latest,judge2")
        mock_create.return_value = _make_client_mock()
        kw = CreativityKeywords()
        with pytest.raises(ValueError, match="at least 3 distinct models"):
            kw.grade_joke("Tell me a joke", "joke text", "humor")

    @patch("rfc.creativity_keywords.create_provider")
    def test_grade_joke_treats_case_aliases_as_duplicate(
        self,
        mock_create: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Case-only differences canonicalise to the same model (#260)."""
        monkeypatch.setenv("CREATIVITY_GRADER_MODELS", "Judge1,JUDGE1,judge2")
        mock_create.return_value = _make_client_mock()
        kw = CreativityKeywords()
        with pytest.raises(ValueError, match="at least 3 distinct models"):
            kw.grade_joke("Tell me a joke", "joke text", "humor")

    @patch("rfc.creativity_keywords.create_provider")
    def test_grade_joke_builds_panel_from_env(
        self,
        mock_create: MagicMock,
        grader_models_env: None,
    ) -> None:
        """Each grader model gets its own provider via create_provider (#260)."""
        mock_create.return_value = _make_client_mock(
            generate_return='{"score": 0.7, "reason": "panel says funny"}'
        )
        kw = CreativityKeywords()
        score, reason = kw.grade_joke("Tell me a joke", "joke text", "humor")

        # 1 call for generation client at __init__, 3 for the panel.
        assert mock_create.call_count == 4
        panel_calls = mock_create.call_args_list[1:]
        passed_models = [c.kwargs.get("model") for c in panel_calls]
        assert passed_models == ["judge1", "judge2", "judge3"]
        assert score == 0.7
        assert "panel" in reason.lower() or "agreement" in reason.lower()

    @patch("rfc.creativity_keywords.create_provider")
    def test_ask_for_joke_sets_temperature(self, mock_create: MagicMock) -> None:
        mock_client = _make_client_mock()
        temps_during_call: list[float] = []

        def capture_temp(prompt: str) -> str:
            temps_during_call.append(mock_client.temperature)
            return "Why did the chicken cross the road?"

        mock_client.generate.side_effect = capture_temp
        mock_create.return_value = mock_client
        kw = CreativityKeywords()
        kw.ask_for_joke("Tell me a joke")
        assert temps_during_call[0] == 0.7

    @patch("rfc.creativity_keywords.create_provider")
    def test_ask_for_joke_returns_response(self, mock_create: MagicMock) -> None:
        mock_create.return_value = _make_client_mock(generate_return="A funny joke!")
        kw = CreativityKeywords()
        assert kw.ask_for_joke("Tell me a joke") == "A funny joke!"

    @patch("rfc.creativity_keywords.create_provider")
    def test_ask_for_joke_restores_temperature(self, mock_create: MagicMock) -> None:
        mock_client = _make_client_mock(generate_return="joke")
        mock_create.return_value = mock_client
        kw = CreativityKeywords()
        kw.ask_for_joke("Tell me a joke")
        assert mock_client.temperature == 0.0

    @patch("rfc.creativity_keywords.create_provider")
    def test_ask_with_conversation_builds_prompt(self, mock_create: MagicMock) -> None:
        mock_client = _make_client_mock(generate_return="Hello Alice!")
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
        mock_create.return_value = _make_client_mock(
            generate_return="Your name is Alice!"
        )
        kw = CreativityKeywords()
        messages = [{"role": "user", "content": "Hello"}]
        assert kw.ask_with_conversation(messages) == "Your name is Alice!"

    @patch("rfc.creativity_keywords.create_provider")
    def test_grade_joke_delegates_to_panel(
        self,
        mock_create: MagicMock,
        grader_models_env: None,
    ) -> None:
        mock_create.return_value = _make_client_mock(
            generate_return='{"score": 0.8, "reason": "funny"}'
        )
        kw = CreativityKeywords()
        score, reason = kw.grade_joke("Tell me a joke", "A funny joke!", "humor")
        assert score == 0.8
        # Panel response wraps the per-judge reasons.
        assert "funny" in reason

    @patch("rfc.creativity_keywords.create_provider")
    def test_grade_context_awareness_uses_single_client(
        self, mock_create: MagicMock
    ) -> None:
        """Context grading is out of scope for #260 — keep single-client path."""
        mock_create.return_value = _make_client_mock(
            generate_return='{"score": 0.9, "reason": "good context"}'
        )
        kw = CreativityKeywords()
        score, reason = kw.grade_context_awareness(
            "test scenario",
            "User: hi\nAssistant: hello",
            "hello there",
            "greets user",
        )
        # Only the generation client was needed (no panel build).
        assert mock_create.call_count == 1
        assert score == 0.9
        assert reason == "good context"

    @patch("rfc.creativity_keywords.create_provider")
    def test_ask_and_grade_joke_with_retry_passes_first_try(
        self,
        mock_create: MagicMock,
        grader_models_env: None,
    ) -> None:
        # Joke + 3 panel grades, all "funny".
        mock_create.return_value = _make_client_mock(
            generate_side_effect=[
                "A great joke!",
                '{"score": 0.8, "reason": "funny"}',
                '{"score": 0.8, "reason": "funny"}',
                '{"score": 0.8, "reason": "funny"}',
            ]
        )
        kw = CreativityKeywords()
        score, reason, joke = kw.ask_and_grade_joke_with_retry(
            "Tell me a joke", "humor"
        )
        assert score == 0.8
        assert joke == "A great joke!"

    @patch("rfc.creativity_keywords.create_provider")
    def test_ask_and_grade_joke_with_retry_escalates_tokens(
        self,
        mock_create: MagicMock,
        grader_models_env: None,
    ) -> None:
        mock_client = _make_client_mock()
        max_tokens_for_jokes: list[int] = []

        responses = [
            "bad joke",
            '{"score": 0.2, "reason": "weak"}',
            '{"score": 0.2, "reason": "weak"}',
            '{"score": 0.2, "reason": "weak"}',
            "A much better joke with more detail!",
            '{"score": 0.8, "reason": "funny"}',
            '{"score": 0.8, "reason": "funny"}',
            '{"score": 0.8, "reason": "funny"}',
        ]

        def capture(prompt: str) -> str:
            if "comedy and creativity judge" in prompt or "automated grader" in prompt:
                pass  # grader prompt — token state irrelevant
            else:
                max_tokens_for_jokes.append(mock_client.max_tokens)
            return responses.pop(0)

        mock_client.generate.side_effect = capture
        mock_create.return_value = mock_client
        kw = CreativityKeywords()
        score, _reason, _joke = kw.ask_and_grade_joke_with_retry(
            "Tell me a joke", "humor", max_retries=3
        )
        assert score == 0.8
        # First joke at default 512, retry escalates 8x to 4096.
        assert max_tokens_for_jokes == [512, 4096]

    @patch("rfc.creativity_keywords.create_provider")
    def test_ask_and_grade_joke_with_retry_enriches_prompt(
        self,
        mock_create: MagicMock,
        grader_models_env: None,
    ) -> None:
        joke_prompts: list[str] = []
        responses = [
            "meh",
            '{"score": 0.2, "reason": "weak"}',
            '{"score": 0.2, "reason": "weak"}',
            '{"score": 0.2, "reason": "weak"}',
            "great joke!",
            '{"score": 0.8, "reason": "funny"}',
            '{"score": 0.8, "reason": "funny"}',
            '{"score": 0.8, "reason": "funny"}',
        ]

        def capture(prompt: str) -> str:
            if (
                "comedy and creativity judge" not in prompt
                and "automated grader" not in prompt
            ):
                joke_prompts.append(prompt)
            return responses.pop(0)

        mock_create.return_value = _make_client_mock(generate_side_effect=capture)
        kw = CreativityKeywords()
        kw.ask_and_grade_joke_with_retry("Tell me a joke", "humor")
        # Second joke prompt should be enriched.
        assert (
            "creative" in joke_prompts[1].lower() or "detail" in joke_prompts[1].lower()
        )

    @patch("rfc.creativity_keywords.emit_rfc_data")
    @patch("rfc.creativity_keywords.create_provider")
    def test_ask_for_joke_emits_actual_answer(
        self, mock_create: MagicMock, mock_emit: MagicMock
    ) -> None:
        mock_create.return_value = _make_client_mock(generate_return="A funny joke!")
        kw = CreativityKeywords()
        kw.ask_for_joke("Tell me a joke")
        mock_emit.assert_any_call("actual_answer", "A funny joke!")

    @patch("rfc.creativity_keywords.emit_rfc_data")
    @patch("rfc.creativity_keywords.create_provider")
    def test_ask_with_conversation_emits_actual_answer(
        self, mock_create: MagicMock, mock_emit: MagicMock
    ) -> None:
        mock_create.return_value = _make_client_mock(
            generate_return="Your name is Alice!"
        )
        kw = CreativityKeywords()
        messages = [{"role": "user", "content": "Hello"}]
        kw.ask_with_conversation(messages)
        mock_emit.assert_any_call("actual_answer", "Your name is Alice!")

    @patch("rfc.creativity_keywords.create_provider")
    def test_ask_and_grade_joke_skips_on_empty_response(
        self,
        mock_create: MagicMock,
        grader_models_env: None,
    ) -> None:
        """Empty joke response should SKIP — consistent with timeouts."""
        # First call returns empty joke; panel grade gets 3 zero-scores.
        mock_create.return_value = _make_client_mock(
            generate_side_effect=[
                "",
                '{"score": 0.0, "reason": "empty"}',
                '{"score": 0.0, "reason": "empty"}',
                '{"score": 0.0, "reason": "empty"}',
            ]
        )
        kw = CreativityKeywords()
        with pytest.raises(EmptyLLMResponseError) as exc_info:
            kw.ask_and_grade_joke_with_retry("Tell me a joke", "humor")
        assert exc_info.value.ROBOT_SKIP is True
