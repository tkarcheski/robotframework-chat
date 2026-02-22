"""Tests for rfc.keywords.LLMKeywords."""

from unittest.mock import MagicMock, patch

from rfc.keywords import LLMKeywords


class TestLLMKeywordsInit:
    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_default_init(self, MockGrader, MockClient):
        LLMKeywords()
        MockClient.assert_called_once_with(timeout=120, max_retries=2)
        MockGrader.assert_called_once_with(MockClient.return_value)

    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_custom_timeout_and_retries(self, MockGrader, MockClient):
        LLMKeywords(timeout=60, max_retries=5)
        MockClient.assert_called_once_with(timeout=60, max_retries=5)


class TestLLMKeywordsSetters:
    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_set_endpoint(self, MockGrader, MockClient):
        kw = LLMKeywords()
        kw.set_llm_endpoint("http://custom:11434")
        assert kw.client.endpoint == "http://custom:11434"

    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_set_model(self, MockGrader, MockClient):
        kw = LLMKeywords()
        kw.set_llm_model("mistral")
        assert kw.client.model == "mistral"

    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_set_parameters(self, MockGrader, MockClient):
        kw = LLMKeywords()
        kw.set_llm_parameters(temperature=0.7, max_tokens=512)
        assert kw.client.temperature == 0.7
        assert kw.client.max_tokens == 512


class TestLLMKeywordsAsk:
    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_ask_llm(self, MockGrader, MockClient):
        kw = LLMKeywords()
        kw.client.generate.return_value = "42"
        result = kw.ask_llm("What is 6 * 7?")
        kw.client.generate.assert_called_once_with("What is 6 * 7?")
        assert result == "42"


class TestLLMKeywordsGrade:
    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_grade_answer(self, MockGrader, MockClient):
        kw = LLMKeywords()
        mock_result = MagicMock()
        mock_result.score = 1
        mock_result.reason = "correct"
        kw.grader.grade.return_value = mock_result

        score, reason = kw.grade_answer("Q", "expected", "actual")
        assert score == 1
        assert reason == "correct"
        kw.grader.grade.assert_called_once_with("Q", "expected", "actual")


class TestLLMKeywordsWait:
    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_wait_for_llm(self, MockGrader, MockClient):
        kw = LLMKeywords()
        kw.client.wait_until_ready.return_value = True
        result = kw.wait_for_llm(timeout=60, poll_interval=5)
        assert result is True
        kw.client.wait_until_ready.assert_called_once_with(60, 5)

    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_wait_for_llm_string_args(self, MockGrader, MockClient):
        """Robot Framework passes all args as strings."""
        kw = LLMKeywords()
        kw.client.wait_until_ready.return_value = True
        kw.wait_for_llm(timeout="30", poll_interval="3")
        kw.client.wait_until_ready.assert_called_once_with(30, 3)


class TestLLMKeywordsRunningModels:
    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_get_running_models(self, MockGrader, MockClient):
        kw = LLMKeywords()
        kw.client.running_models.return_value = [{"name": "llama3"}]
        result = kw.get_running_models()
        assert result == [{"name": "llama3"}]

    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_llm_is_busy_true(self, MockGrader, MockClient):
        kw = LLMKeywords()
        kw.client.is_busy.return_value = True
        assert kw.llm_is_busy() is True

    @patch("rfc.keywords.OllamaClient")
    @patch("rfc.keywords.Grader")
    def test_llm_is_busy_false(self, MockGrader, MockClient):
        kw = LLMKeywords()
        kw.client.is_busy.return_value = False
        assert kw.llm_is_busy() is False
