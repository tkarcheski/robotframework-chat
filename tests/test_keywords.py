"""Tests for rfc.keywords.LLMKeywords."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from rfc.exceptions import EmptyLLMResponseError
from rfc.keywords import LLMKeywords
from rfc.ollama import OllamaClient


class TestLLMKeywordsInit:
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_default_init(self, MockGrader, mock_create):
        LLMKeywords()
        mock_create.assert_called_once_with(timeout=5400, max_retries=2)
        MockGrader.assert_called_once_with(mock_create.return_value)

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_custom_timeout_and_retries(self, MockGrader, mock_create):
        LLMKeywords(timeout=60, max_retries=5)
        mock_create.assert_called_once_with(timeout=60, max_retries=5)

    @patch.dict(os.environ, {"OLLAMA_TIMEOUT": "300"})
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_default_timeout_from_env(self, MockGrader, mock_create):
        LLMKeywords()
        mock_create.assert_called_once_with(timeout=300, max_retries=2)


class TestLLMKeywordsSetters:
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_set_endpoint_ollama(self, MockGrader, mock_create):
        """When provider is OllamaClient, sets endpoint property."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_create.return_value = mock_client
        kw = LLMKeywords()
        kw.set_llm_endpoint("http://custom:11434")
        assert kw.client.endpoint == "http://custom:11434"

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_set_endpoint_non_ollama(self, MockGrader, mock_create):
        """When provider is non-Ollama, sets base_url."""
        kw = LLMKeywords()
        kw.set_llm_endpoint("https://api.openai.com/v1")
        assert kw.client.base_url == "https://api.openai.com/v1"

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_set_model(self, MockGrader, mock_create):
        kw = LLMKeywords()
        kw.set_llm_model("mistral")
        assert kw.client.model == "mistral"

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_set_parameters(self, MockGrader, mock_create):
        kw = LLMKeywords()
        kw.set_llm_parameters(temperature=0.7, max_tokens=512)
        assert kw.client.temperature == 0.7
        assert kw.client.max_tokens == 512


class TestLLMKeywordsAsk:
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_ask_llm(self, MockGrader, mock_create):
        kw = LLMKeywords()
        kw.client.generate.return_value = "42"
        kw.client.last_metrics = None
        result = kw.ask_llm("What is 6 * 7?")
        kw.client.generate.assert_called_once_with("What is 6 * 7?")
        assert result == "42"

    @patch("rfc.rfc_data.logger")
    @patch("rfc.keywords.logger")
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_ask_llm_emits_llm_metrics(
        self, MockGrader, mock_create, mock_logger, mock_rfc_logger
    ):
        kw = LLMKeywords()
        kw.client.generate.return_value = "42"
        kw.client.max_tokens = 256
        kw.client.num_ctx = None
        kw.client.last_metrics = {
            "model_name": "llama3",
            "total_duration_ns": 17607688368,
            "eval_rate": 11.0,
        }

        kw.ask_llm("What is 6 * 7?")

        # RFC_DATA messages must be emitted at INFO level so the
        # DbListener.log_message() receives them at the default --loglevel.
        info_calls = [str(c) for c in mock_rfc_logger.info.call_args_list]
        metrics_calls = [c for c in info_calls if "RFC_DATA:llm_metrics:" in c]
        assert len(metrics_calls) == 1

        # Parse and verify the JSON payload
        raw = [
            c.args[0]
            for c in mock_rfc_logger.info.call_args_list
            if "RFC_DATA:llm_metrics:" in str(c)
        ][0]
        payload = raw.split("RFC_DATA:llm_metrics:", 1)[1]
        data = json.loads(payload)
        assert data["model_name"] == "llama3"
        assert data["total_duration_ns"] == 17607688368
        assert data["prompt_text"] == "What is 6 * 7?"

    @patch("rfc.rfc_data.logger")
    @patch("rfc.keywords.logger")
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_ask_llm_skips_metrics_when_none(
        self, MockGrader, mock_create, mock_logger, mock_rfc_logger
    ):
        kw = LLMKeywords()
        kw.client.generate.return_value = "42"
        kw.client.last_metrics = None

        kw.ask_llm("test")

        info_calls = [str(c) for c in mock_rfc_logger.info.call_args_list]
        metrics_calls = [c for c in info_calls if "RFC_DATA:llm_metrics:" in c]
        assert len(metrics_calls) == 0

    @patch.dict(os.environ, {"RFC_DIALOG_RECORDING_ID": "rec-null-test"})
    @patch("rfc.rfc_data.logger")
    @patch("rfc.keywords.logger")
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_dialog_turns_skip_null_metric_values(
        self, MockGrader, mock_create, mock_logger, mock_rfc_logger
    ):
        """Metrics with None values (absent usage) must not raise TypeError.

        _extract_metrics returns None for prompt_eval_count/eval_count when
        the provider response omits the usage block.  _emit_dialog_turns checks
        key presence, so it would call int(None) without a non-null guard.
        """
        kw = LLMKeywords()
        kw.client.generate.return_value = "answer"
        kw.client.max_tokens = 256
        kw.client.num_ctx = None
        kw.client.last_metrics = {
            "model_name": "gpt-4o",
            "prompt_eval_count": None,
            "eval_count": None,
            "total_duration_ns": None,
        }

        kw.ask_llm("hello")  # must not raise TypeError

        # The assistant dialog_turn must be emitted without the null fields
        info_calls = [c.args[0] for c in mock_rfc_logger.info.call_args_list]
        turn_calls = [c for c in info_calls if "RFC_DATA:dialog_turn:" in c]
        assistant_payloads = [
            json.loads(c.split("RFC_DATA:dialog_turn:", 1)[1])
            for c in turn_calls
            if json.loads(c.split("RFC_DATA:dialog_turn:", 1)[1]).get("role")
            == "assistant"
        ]
        assert len(assistant_payloads) == 1
        turn = assistant_payloads[0]
        assert "prompt_tokens" not in turn
        assert "completion_tokens" not in turn
        assert "latency_ms" not in turn


class TestLLMKeywordsAskThinking:
    @patch("rfc.keywords.logger")
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_ask_llm_strips_thinking(self, MockGrader, mock_create, mock_logger):
        kw = LLMKeywords()
        kw.client.generate.return_value = (
            "<think>reasoning here</think>The answer is 42."
        )
        kw.client.last_metrics = None
        kw.client.num_ctx = None
        kw.client.max_tokens = 256
        result = kw.ask_llm("What is 6 * 7?")
        assert result == "The answer is 42."

    @patch("rfc.rfc_data.logger")
    @patch("rfc.keywords.logger")
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_ask_llm_emits_thinking_data(
        self, MockGrader, mock_create, mock_logger, mock_rfc_logger
    ):
        kw = LLMKeywords()
        kw.client.generate.return_value = "<think>step by step</think>42"
        kw.client.last_metrics = None
        kw.client.num_ctx = None
        kw.client.max_tokens = 256
        kw.ask_llm("test")

        info_calls = [str(c) for c in mock_rfc_logger.info.call_args_list]
        thinking_calls = [c for c in info_calls if "RFC_DATA:thinking_text:" in c]
        assert len(thinking_calls) == 1
        assert "step by step" in thinking_calls[0]

        token_calls = [c for c in info_calls if "RFC_DATA:thinking_tokens:" in c]
        assert len(token_calls) == 1

    @patch("rfc.rfc_data.logger")
    @patch("rfc.keywords.logger")
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_ask_llm_no_thinking_no_data(
        self, MockGrader, mock_create, mock_logger, mock_rfc_logger
    ):
        kw = LLMKeywords()
        kw.client.generate.return_value = "42"
        kw.client.last_metrics = None
        kw.client.num_ctx = None
        kw.client.max_tokens = 256
        kw.ask_llm("test")

        info_calls = [str(c) for c in mock_rfc_logger.info.call_args_list]
        thinking_calls = [c for c in info_calls if "RFC_DATA:thinking_text:" in c]
        assert len(thinking_calls) == 0


class TestLLMKeywordsHideThinking:
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_hide_thinking_default_true(self, MockGrader, mock_create):
        """hide_thinking defaults to True."""
        kw = LLMKeywords()
        assert kw._hide_thinking is True

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_hide_thinking_strips_unclosed_tags(self, MockGrader, mock_create):
        """With hide_thinking=True (default), unclosed <think> tags are stripped."""
        kw = LLMKeywords()
        kw.client.generate.return_value = "<think>reasoning here"
        kw.client.last_metrics = None
        kw.client.num_ctx = None
        kw.client.max_tokens = 256
        result = kw.ask_llm("test")
        assert "<think>" not in result

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_hide_thinking_false_preserves_unclosed_tags(self, MockGrader, mock_create):
        """With hide_thinking=False, unclosed <think> tags pass through."""
        kw = LLMKeywords(hide_thinking=False)
        kw.client.generate.return_value = "<think>reasoning here"
        kw.client.last_metrics = None
        kw.client.num_ctx = None
        kw.client.max_tokens = 256
        result = kw.ask_llm("test")
        assert "<think>" in result

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_hide_thinking_string_coercion(self, MockGrader, mock_create):
        """Robot Framework passes all args as strings — 'True'/'False' must work."""
        kw = LLMKeywords(hide_thinking="False")
        assert kw._hide_thinking is False
        kw2 = LLMKeywords(hide_thinking="True")
        assert kw2._hide_thinking is True


class TestLLMKeywordsSetParametersExtended:
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_set_extended_parameters(self, MockGrader, mock_create):
        kw = LLMKeywords()
        kw.set_llm_parameters(
            temperature=0.7,
            max_tokens=512,
            seed=42,
            top_p=0.9,
            top_k=40,
            num_ctx=4096,
            keep_alive="5m",
        )
        assert kw.client.temperature == 0.7
        assert kw.client.max_tokens == 512
        assert kw.client.seed == 42
        assert kw.client.top_p == 0.9
        assert kw.client.top_k == 40
        assert kw.client.num_ctx == 4096
        assert kw.client.keep_alive == "5m"

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_set_parameters_string_coercion(self, MockGrader, mock_create):
        """Robot Framework passes all args as strings."""
        kw = LLMKeywords()
        kw.set_llm_parameters(
            temperature="0.5",
            max_tokens="1024",
            seed="42",
            top_p="0.9",
            top_k="40",
            num_ctx="8192",
        )
        assert kw.client.seed == 42
        assert kw.client.num_ctx == 8192


class TestLLMKeywordsUnload:
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_unload_model_ollama(self, MockGrader, mock_create):
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.unload_model.return_value = True
        mock_create.return_value = mock_client
        kw = LLMKeywords()
        result = kw.unload_model()
        assert result is True
        mock_client.unload_model.assert_called_once_with(None)

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_unload_model_non_ollama_returns_false(self, MockGrader, mock_create):
        kw = LLMKeywords()
        result = kw.unload_model()
        assert result is False


class TestLLMKeywordsGrade:
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_grade_answer(self, MockGrader, mock_create):
        kw = LLMKeywords()
        mock_result = MagicMock()
        mock_result.score = 1
        mock_result.reason = "correct"
        kw.grader.grade.return_value = mock_result

        score, reason = kw.grade_answer("Q", "expected", "actual")
        assert score == 1
        assert reason == "correct"
        kw.grader.grade.assert_called_once_with("Q", "expected", "actual")


class TestAskAndGradeWithRetry:
    """Tests for Ask And Grade With Retry keyword — adaptive token scaling."""

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_passes_on_first_attempt(self, MockGrader, mock_create):
        """If grading passes on first try, no retry needed."""
        kw = LLMKeywords()
        kw.client.generate.return_value = "42"
        kw.client.last_metrics = None
        kw.client.num_ctx = None
        kw.client.max_tokens = 256
        mock_result = MagicMock()
        mock_result.score = 1.0
        mock_result.reason = "correct"
        kw.grader.grade.return_value = mock_result

        score, reason, answer = kw.ask_and_grade_with_retry(
            "What is 6*7?", "42", max_retries=3
        )
        assert score == 1.0
        assert answer == "42"
        assert kw.client.generate.call_count == 1

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_retries_on_wrong_answer_8x_tokens(self, MockGrader, mock_create):
        """When grading fails with non-empty answer, retry with 8x tokens."""
        kw = LLMKeywords()
        kw.client.max_tokens = 256
        kw.client.num_ctx = None
        kw.client.last_metrics = None

        # First attempt: wrong answer; second attempt: correct
        kw.client.generate.side_effect = ["wrong", "42"]
        fail_result = MagicMock()
        fail_result.score = 0.0
        fail_result.reason = "incorrect"
        pass_result = MagicMock()
        pass_result.score = 1.0
        pass_result.reason = "correct"
        kw.grader.grade.side_effect = [fail_result, pass_result]

        score, reason, answer = kw.ask_and_grade_with_retry(
            "What is 6*7?", "42", max_retries=3
        )
        assert score == 1.0
        assert answer == "42"
        assert kw.client.generate.call_count == 2
        # Token limit should have been 8x'd for the retry: 256 → 2048
        assert kw.client.max_tokens == 2048

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_8x_tokens_each_retry(self, MockGrader, mock_create):
        """Tokens 8x on each successive retry: 256 → 2048 → 16384 → 131072."""
        kw = LLMKeywords()
        kw.client.max_tokens = 256
        kw.client.num_ctx = None
        kw.client.last_metrics = None

        # Fail 3 times, pass on 4th (initial + 3 retries)
        kw.client.generate.side_effect = ["wrong1", "wrong2", "wrong3", "correct"]
        fail = MagicMock()
        fail.score = 0.0
        fail.reason = "incorrect"
        success = MagicMock()
        success.score = 1.0
        success.reason = "correct"
        kw.grader.grade.side_effect = [fail, fail, fail, success]

        score, reason, answer = kw.ask_and_grade_with_retry(
            "Q", "correct", max_retries=3
        )
        assert score == 1.0
        assert kw.client.generate.call_count == 4
        # 256 → 2048 → 16384 → 131072
        assert kw.client.max_tokens == 131072

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_skips_on_empty_response(self, MockGrader, mock_create):
        """Empty responses should SKIP (not fail) — consistent with timeouts."""
        kw = LLMKeywords()
        kw.client.max_tokens = 256
        kw.client.num_ctx = None
        kw.client.last_metrics = None
        kw.client.model = "test-model"

        kw.client.generate.return_value = ""
        fail = MagicMock()
        fail.score = 0.0
        fail.reason = "empty"
        kw.grader.grade.return_value = fail

        with pytest.raises(EmptyLLMResponseError) as exc_info:
            kw.ask_and_grade_with_retry("Q", "42", max_retries=3)
        assert exc_info.value.ROBOT_SKIP_EXECUTION is True
        assert kw.client.generate.call_count == 1
        assert kw.client.max_tokens == 256

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_exhausts_retries_returns_last_result(self, MockGrader, mock_create):
        """If all retries fail, return the last attempt's result."""
        kw = LLMKeywords()
        kw.client.max_tokens = 256
        kw.client.num_ctx = None
        kw.client.last_metrics = None

        kw.client.generate.return_value = "wrong"
        fail = MagicMock()
        fail.score = 0.0
        fail.reason = "incorrect"
        kw.grader.grade.return_value = fail

        score, reason, answer = kw.ask_and_grade_with_retry("Q", "42", max_retries=3)
        assert score == 0.0
        # 1 initial + 3 retries = 4 total attempts
        assert kw.client.generate.call_count == 4
        # Tokens should have been 8x'd 3 times: 256 → 131072
        assert kw.client.max_tokens == 131072

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_restores_original_max_tokens_on_success(self, MockGrader, mock_create):
        """After retry succeeds, max_tokens stays at the working value (for logging)."""
        kw = LLMKeywords()
        kw.client.max_tokens = 256
        kw.client.num_ctx = None
        kw.client.last_metrics = None

        kw.client.generate.side_effect = ["wrong", "correct"]
        fail = MagicMock()
        fail.score = 0.0
        fail.reason = "incorrect"
        success = MagicMock()
        success.score = 1.0
        success.reason = "correct"
        kw.grader.grade.side_effect = [fail, success]

        score, reason, answer = kw.ask_and_grade_with_retry(
            "Q", "correct", max_retries=3
        )
        assert score == 1.0
        # max_tokens should reflect what worked (2048)
        assert kw.client.max_tokens == 2048

    @patch("rfc.rfc_data.logger")
    @patch("rfc.keywords.logger")
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_emits_retry_metadata(
        self, MockGrader, mock_create, mock_logger, mock_rfc_logger
    ):
        """Should emit RFC_DATA with retry count and final token budget."""
        kw = LLMKeywords()
        kw.client.max_tokens = 256
        kw.client.num_ctx = None
        kw.client.last_metrics = None

        kw.client.generate.side_effect = ["wrong", "42"]
        fail = MagicMock()
        fail.score = 0.0
        fail.reason = "incorrect"
        success = MagicMock()
        success.score = 1.0
        success.reason = "correct"
        kw.grader.grade.side_effect = [fail, success]

        kw.ask_and_grade_with_retry("Q", "42", max_retries=3)

        info_calls = [str(c) for c in mock_rfc_logger.info.call_args_list]
        retry_calls = [c for c in info_calls if "RFC_DATA:token_retry_count:" in c]
        assert len(retry_calls) == 1
        assert "1" in retry_calls[0]

        budget_calls = [
            c for c in info_calls if "RFC_DATA:token_retry_max_tokens:" in c
        ]
        assert len(budget_calls) == 1
        assert "2048" in budget_calls[0]

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_default_max_retries_is_three(self, MockGrader, mock_create):
        """Default max_retries should be 3."""
        kw = LLMKeywords()
        kw.client.max_tokens = 256
        kw.client.num_ctx = None
        kw.client.last_metrics = None

        kw.client.generate.return_value = "wrong"
        fail = MagicMock()
        fail.score = 0.0
        fail.reason = "nope"
        kw.grader.grade.return_value = fail

        kw.ask_and_grade_with_retry("Q", "42")
        # 1 initial + 3 retries = 4 total
        assert kw.client.generate.call_count == 4

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_grading_question_separates_prompt_from_grading(
        self, MockGrader, mock_create
    ):
        """grading_question should be passed to grader, not the full prompt."""
        kw = LLMKeywords()
        kw.client.generate.return_value = "auto-renewal after 12 months"
        kw.client.last_metrics = None
        kw.client.num_ctx = None
        kw.client.max_tokens = 1024
        success = MagicMock()
        success.score = 1.0
        success.reason = "correct"
        kw.grader.grade.return_value = success

        big_prompt = "BEGIN AGREEMENT\n" + ("x" * 10000) + "\nEND\nQuestion: renewal?"
        short_q = "What is the auto-renewal clause?"

        kw.ask_and_grade_with_retry(big_prompt, "12 months", grading_question=short_q)

        # LLM should receive the full prompt
        kw.client.generate.assert_called_once_with(big_prompt)
        # Grader should receive the short question, not the 10KB prompt
        kw.grader.grade.assert_called_once_with(
            short_q, "12 months", "auto-renewal after 12 months"
        )

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_grading_question_defaults_to_prompt(self, MockGrader, mock_create):
        """When grading_question is not provided, prompt is used for grading."""
        kw = LLMKeywords()
        kw.client.generate.return_value = "42"
        kw.client.last_metrics = None
        kw.client.num_ctx = None
        kw.client.max_tokens = 256
        success = MagicMock()
        success.score = 1.0
        success.reason = "correct"
        kw.grader.grade.return_value = success

        kw.ask_and_grade_with_retry("What is 6*7?", "42")

        kw.grader.grade.assert_called_once_with("What is 6*7?", "42", "42")

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_token_scaling_capped_at_ceiling(self, MockGrader, mock_create):
        """Token scaling must not exceed _MAX_TOKEN_CEILING (131072)."""
        kw = LLMKeywords()
        kw.client.max_tokens = 32768  # 32K — one 8x would be 262144
        kw.client.num_ctx = None
        kw.client.last_metrics = None

        kw.client.generate.side_effect = ["wrong", "correct"]
        fail = MagicMock()
        fail.score = 0.0
        fail.reason = "incorrect"
        success = MagicMock()
        success.score = 1.0
        success.reason = "correct"
        kw.grader.grade.side_effect = [fail, success]

        kw.ask_and_grade_with_retry("Q", "correct", max_retries=3)
        # 32768 * 8 = 262144, but capped at 131072
        assert kw.client.max_tokens == 131072


class TestLLMKeywordsWait:
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_wait_for_llm_with_ollama(self, MockGrader, mock_create):
        """When the provider is OllamaClient, delegates to wait_until_ready."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.wait_until_ready.return_value = True
        mock_create.return_value = mock_client
        kw = LLMKeywords()
        result = kw.wait_for_llm(timeout=60, poll_interval=5)
        assert result is True
        mock_client.wait_until_ready.assert_called_once_with(60, 5)

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_wait_for_llm_string_args(self, MockGrader, mock_create):
        """Robot Framework passes all args as strings."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.wait_until_ready.return_value = True
        mock_create.return_value = mock_client
        kw = LLMKeywords()
        kw.wait_for_llm(timeout="30", poll_interval="3")
        mock_client.wait_until_ready.assert_called_once_with(30, 3)

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_wait_for_llm_non_ollama_returns_true(self, MockGrader, mock_create):
        """Non-Ollama providers skip wait and return True."""
        kw = LLMKeywords()
        # mock_create returns a MagicMock (not OllamaClient spec)
        result = kw.wait_for_llm()
        assert result is True


class TestLLMKeywordsRunningModels:
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_get_running_models_with_ollama(self, MockGrader, mock_create):
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.running_models.return_value = [{"name": "llama3"}]
        mock_create.return_value = mock_client
        kw = LLMKeywords()
        result = kw.get_running_models()
        assert result == [{"name": "llama3"}]

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_get_running_models_non_ollama_returns_empty(self, MockGrader, mock_create):
        kw = LLMKeywords()
        result = kw.get_running_models()
        assert result == []

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_llm_is_busy_with_ollama(self, MockGrader, mock_create):
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.is_busy.return_value = True
        mock_create.return_value = mock_client
        kw = LLMKeywords()
        assert kw.llm_is_busy() is True

    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_llm_is_busy_non_ollama_returns_false(self, MockGrader, mock_create):
        kw = LLMKeywords()
        assert kw.llm_is_busy() is False


# ── set_llm_endpoint unsupported provider (line 42) ─────────────────


class TestLLMKeywordsSetEndpointUnsupported:
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_unsupported_provider_warns(self, MockGrader, mock_create):
        """Provider with no endpoint or base_url attribute should log a warning."""
        mock_client = MagicMock(spec=[])  # No attributes at all
        mock_create.return_value = mock_client
        kw = LLMKeywords()
        # Should not raise
        kw.set_llm_endpoint("http://new:11434")


# ── ask_llm with num_ctx in metrics (line 91) ───────────────────────


class TestAskLlmNumCtxInMetrics:
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_ask_llm_includes_num_ctx_in_metrics(self, MockGrader, mock_create):
        mock_client = MagicMock()
        mock_client.generate.return_value = "The answer is 42"
        mock_client.num_ctx = 4096
        mock_client.max_tokens = 256
        mock_client.last_metrics = {"eval_count": 10}
        mock_create.return_value = mock_client
        kw = LLMKeywords()
        result = kw.ask_llm("What is 6*7?")
        assert result == "The answer is 42"
        # Verify num_ctx was added to last_metrics
        assert mock_client.last_metrics["num_ctx"] == 4096


class TestSaveRestoreLLMModel:
    """Save/Restore LLM Model — the generative fork bracket (#359/#480)."""

    @patch("rfc.keywords.logger")
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_save_then_restore_round_trips(self, MockGrader, mock_create, mock_logger):
        kw = LLMKeywords()
        kw.client.model = "original-model"
        assert kw.save_llm_model() == "original-model"
        kw.set_llm_model("fork-model")
        assert kw.client.model == "fork-model"
        assert kw.restore_llm_model() == "original-model"
        assert kw.client.model == "original-model"

    @patch("rfc.keywords.logger")
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_restore_without_save_is_noop(self, MockGrader, mock_create, mock_logger):
        kw = LLMKeywords()
        kw.client.model = "original-model"
        assert kw.restore_llm_model() == ""
        assert kw.client.model == "original-model"
