"""Tests for rfc.self_healing — decorator, config, and strategy engine."""

from unittest.mock import MagicMock, patch


from rfc.models import GradeResult
from rfc.self_healing import (
    HealingAttempt,
    SelfHealingConfig,
    self_healing,
    _extract_prompt_arg,
    _replace_prompt_arg,
    _capture_params,
    _param_variations,
    _is_passing,
    _extract_grade_result,
    _extract_expected_arg,
)


class TestSelfHealingConfig:
    def test_defaults(self):
        cfg = SelfHealingConfig()
        assert cfg.max_prompt_retries == 2
        assert cfg.max_param_retries == 3
        assert cfg.fallback_models == []
        assert cfg.escalate_to_github is True
        assert cfg.score_threshold == 1.0
        assert cfg.param_temperatures == [0.0, 0.3, 0.7]
        assert cfg.param_seeds == [42, 123, 7]

    def test_custom_config(self):
        cfg = SelfHealingConfig(
            max_prompt_retries=5,
            fallback_models=["model-a", "model-b"],
            score_threshold=0.8,
        )
        assert cfg.max_prompt_retries == 5
        assert cfg.fallback_models == ["model-a", "model-b"]
        assert cfg.score_threshold == 0.8


class TestHealingAttempt:
    def test_creation(self):
        attempt = HealingAttempt(
            attempt_number=1,
            strategy="original",
            prompt_used="test prompt",
        )
        assert attempt.attempt_number == 1
        assert attempt.strategy == "original"
        assert attempt.prompt_used == "test prompt"
        assert attempt.result is None
        assert attempt.success is False
        assert attempt.error == ""

    def test_with_result(self):
        grade = GradeResult(score=0.5, reason="partial")
        attempt = HealingAttempt(
            attempt_number=2,
            strategy="prompt",
            prompt_used="modified prompt",
            result=grade,
            success=False,
            error="partial",
        )
        assert attempt.result.score == 0.5
        assert attempt.error == "partial"


class TestExtractPromptArg:
    def test_from_kwargs(self):
        prompt, idx = _extract_prompt_arg((), {"prompt": "hello"})
        assert prompt == "hello"
        assert idx == -1

    def test_from_positional(self):
        prompt, idx = _extract_prompt_arg(("hello", "world"), {})
        assert prompt == "hello"
        assert idx == 0

    def test_no_prompt(self):
        prompt, idx = _extract_prompt_arg((42, 3.14), {})
        assert prompt is None
        assert idx == -1


class TestReplacePromptArg:
    def test_replace_in_kwargs(self):
        args, kwargs = _replace_prompt_arg(("a",), {"prompt": "old"}, "new", -1)
        assert kwargs["prompt"] == "new"
        assert args == ("a",)

    def test_replace_in_positional(self):
        args, kwargs = _replace_prompt_arg(("old", "expected"), {}, "new", 0)
        assert args == ("new", "expected")


class TestCaptureParams:
    def test_captures_client_attrs(self):
        instance = MagicMock()
        instance.client.temperature = 0.5
        instance.client.max_tokens = 256
        instance.client.seed = 42
        instance.client.top_p = None
        instance.client.top_k = None
        instance.client.model = "test-model"
        params = _capture_params(instance)
        assert params["temperature"] == 0.5
        assert params["max_tokens"] == 256
        assert params["seed"] == 42
        assert params["model"] == "test-model"
        assert "top_p" not in params  # None values excluded

    def test_no_client(self):
        instance = MagicMock(spec=[])
        params = _capture_params(instance)
        assert params == {}


class TestParamVariations:
    def test_generates_temperature_variations(self):
        cfg = SelfHealingConfig(max_param_retries=3)
        original = {"temperature": 0.0, "max_tokens": 256}
        variations = _param_variations(cfg, original)
        assert len(variations) > 0
        # At least one variation should differ from original temperature
        assert any(v["temperature"] != 0.0 for v in variations)

    def test_respects_max_retries(self):
        cfg = SelfHealingConfig(max_param_retries=1)
        original = {"temperature": 0.0}
        variations = _param_variations(cfg, original)
        assert len(variations) <= 1


class TestIsPassing:
    def test_grade_result_passing(self):
        assert _is_passing(GradeResult(score=1.0, reason="ok"), 1.0)

    def test_grade_result_failing(self):
        assert not _is_passing(GradeResult(score=0.5, reason="partial"), 1.0)

    def test_tuple_passing(self):
        assert _is_passing((1.0, "ok", "answer"), 1.0)

    def test_tuple_failing(self):
        assert not _is_passing((0.3, "wrong"), 1.0)

    def test_non_result(self):
        assert not _is_passing("not a result", 1.0)


class TestExtractGradeResult:
    def test_from_grade_result(self):
        gr = GradeResult(score=0.8, reason="good")
        assert _extract_grade_result(gr) is gr

    def test_from_tuple(self):
        result = _extract_grade_result((0.8, "good", "answer"))
        assert result is not None
        assert result.score == 0.8
        assert result.reason == "good"

    def test_from_invalid(self):
        assert _extract_grade_result("invalid") is None


class TestExtractExpectedArg:
    def test_from_kwargs(self):
        assert _extract_expected_arg((), {"expected": "four"}) == "four"

    def test_from_positional(self):
        assert _extract_expected_arg(("prompt", "four"), {}) == "four"

    def test_missing(self):
        assert _extract_expected_arg((42,), {}) == ""


class TestSelfHealingDecorator:
    """Tests for the @self_healing decorator."""

    def _make_instance(self, model: str = "test-model"):
        """Create a mock keyword library instance with a client."""
        instance = MagicMock()
        instance.client.temperature = 0.0
        instance.client.max_tokens = 256
        instance.client.seed = None
        instance.client.top_p = None
        instance.client.top_k = None
        instance.client.model = model
        return instance

    @patch("rfc.self_healing.emit_rfc_data")
    def test_passes_on_first_try(self, mock_emit):
        """If the keyword succeeds on the first call, no healing occurs."""
        cfg = SelfHealingConfig()

        @self_healing(config=cfg)
        def my_keyword(self, prompt, expected):
            return GradeResult(score=1.0, reason="correct")

        instance = self._make_instance()
        result = my_keyword(instance, "What is 2+2?", "4")
        assert result.score == 1.0
        # Should emit healing data with 1 attempt
        calls = {c.args[0]: c.args[1] for c in mock_emit.call_args_list}
        assert calls["self_healing_attempts"] == "1"
        assert calls["self_healing_success"] == "True"

    @patch("rfc.self_healing._rewrite_prompt", return_value="improved prompt")
    @patch("rfc.self_healing.emit_rfc_data")
    def test_heals_with_prompt_modification(self, mock_emit, mock_rewrite):
        """If first attempt fails, prompt modification should be tried."""
        call_count = 0
        cfg = SelfHealingConfig(max_prompt_retries=1, max_param_retries=0)

        @self_healing(config=cfg)
        def my_keyword(self, prompt, expected):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return GradeResult(score=0.0, reason="wrong")
            return GradeResult(score=1.0, reason="correct after rewrite")

        instance = self._make_instance()
        result = my_keyword(instance, "bad prompt", "4")
        assert result.score == 1.0
        assert call_count == 2
        calls = {c.args[0]: c.args[1] for c in mock_emit.call_args_list}
        assert calls["self_healing_success"] == "True"
        assert calls["self_healing_strategy"] == "prompt"

    @patch("rfc.self_healing.emit_rfc_data")
    def test_heals_with_param_adjustment(self, mock_emit):
        """If prompt fails, parameter adjustment should be tried."""
        call_count = 0
        cfg = SelfHealingConfig(
            max_prompt_retries=0,
            max_param_retries=2,
        )

        @self_healing(config=cfg)
        def my_keyword(self, prompt, expected):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return GradeResult(score=0.0, reason="wrong")
            return GradeResult(score=1.0, reason="correct with new params")

        instance = self._make_instance()
        result = my_keyword(instance, "prompt", "answer")
        assert result.score == 1.0
        calls = {c.args[0]: c.args[1] for c in mock_emit.call_args_list}
        assert calls["self_healing_strategy"] == "params"

    @patch("rfc.self_healing.emit_rfc_data")
    def test_heals_with_model_fallback(self, mock_emit):
        """If params fail, model fallback should be tried."""
        call_count = 0
        cfg = SelfHealingConfig(
            max_prompt_retries=0,
            max_param_retries=0,
            fallback_models=["fallback-model"],
        )

        @self_healing(config=cfg)
        def my_keyword(self, prompt, expected):
            nonlocal call_count
            call_count += 1
            if self.client.model == "fallback-model":
                return GradeResult(score=1.0, reason="fallback worked")
            return GradeResult(score=0.0, reason="wrong")

        instance = self._make_instance()
        result = my_keyword(instance, "prompt", "answer")
        assert result.score == 1.0
        calls = {c.args[0]: c.args[1] for c in mock_emit.call_args_list}
        assert calls["self_healing_strategy"] == "model"
        # Original model should be restored
        assert instance.client.model == "test-model"

    @patch("rfc.self_healing._create_github_issue", return_value=True)
    @patch("rfc.self_healing.emit_rfc_data")
    def test_escalates_when_all_fail(self, mock_emit, mock_issue):
        """If all strategies fail, escalation should occur."""
        cfg = SelfHealingConfig(
            max_prompt_retries=0,
            max_param_retries=0,
            fallback_models=[],
            escalate_to_github=True,
        )

        @self_healing(config=cfg)
        def my_keyword(self, prompt, expected):
            return GradeResult(score=0.0, reason="always wrong")

        instance = self._make_instance()
        result = my_keyword(instance, "prompt", "answer")
        assert result.score == 0.0
        mock_issue.assert_called_once()
        calls = {c.args[0]: c.args[1] for c in mock_emit.call_args_list}
        assert calls["self_healing_success"] == "False"
        assert calls["self_healing_strategy"] == "exhausted"

    @patch("rfc.self_healing.emit_rfc_data")
    def test_no_escalation_when_disabled(self, mock_emit):
        """No GitHub issue when escalation is disabled."""
        cfg = SelfHealingConfig(
            max_prompt_retries=0,
            max_param_retries=0,
            escalate_to_github=False,
        )

        @self_healing(config=cfg)
        def my_keyword(self, prompt, expected):
            return GradeResult(score=0.0, reason="wrong")

        instance = self._make_instance()
        result = my_keyword(instance, "prompt", "answer")
        assert result.score == 0.0

    @patch("rfc.self_healing.emit_rfc_data")
    def test_handles_tuple_return(self, mock_emit):
        """Decorator works with tuple returns (score, reason, answer)."""
        cfg = SelfHealingConfig()

        @self_healing(config=cfg)
        def my_keyword(self, prompt, expected):
            return (1.0, "correct", "the answer")

        instance = self._make_instance()
        result = my_keyword(instance, "prompt", "answer")
        assert result == (1.0, "correct", "the answer")

    @patch("rfc.self_healing.emit_rfc_data")
    def test_handles_exception_in_keyword(self, mock_emit):
        """Decorator handles exceptions from the wrapped keyword."""
        call_count = 0
        cfg = SelfHealingConfig(
            max_prompt_retries=0,
            max_param_retries=0,
            escalate_to_github=False,
        )

        @self_healing(config=cfg)
        def my_keyword(self, prompt, expected):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("LLM error")
            return GradeResult(score=1.0, reason="ok")

        instance = self._make_instance()
        # With no retries configured, the exception path should still
        # emit healing data and return None (the last result)
        result = my_keyword(instance, "prompt", "answer")
        assert result is None

    @patch("rfc.self_healing.emit_rfc_data")
    def test_default_config(self, mock_emit):
        """Decorator works with default config (no args)."""

        @self_healing()
        def my_keyword(self, prompt, expected):
            return GradeResult(score=1.0, reason="ok")

        instance = self._make_instance()
        result = my_keyword(instance, "prompt", "answer")
        assert result.score == 1.0
