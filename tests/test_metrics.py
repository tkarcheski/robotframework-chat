"""Tests for rfc.metrics — extracted metrics helpers."""

import json
from unittest.mock import MagicMock, patch

import pytest

from rfc.metrics import (
    compute_token_efficiency,
    extract_llm_metrics,
    get_robot_float,
    get_robot_int,
    nvl,
    parse_tags,
    safe_int,
    warn_near_miss,
)


# ---------------------------------------------------------------------------
# compute_token_efficiency
# ---------------------------------------------------------------------------


class TestComputeTokenEfficiency:
    def test_correct_answer(self) -> None:
        assert compute_token_efficiency(1.0, 150) == 150.0

    def test_partial_correct(self) -> None:
        assert compute_token_efficiency(0.5, 200) == 200.0

    def test_incorrect_answer(self) -> None:
        assert compute_token_efficiency(0.3, 300) == 0.0

    def test_zero_eval_count(self) -> None:
        assert compute_token_efficiency(1.0, 0) == 0.0

    def test_custom_threshold(self) -> None:
        assert compute_token_efficiency(0.6, 100, pass_threshold=0.8) == 0.0

    def test_ungraded(self) -> None:
        assert compute_token_efficiency(-1.0, 500) == 0.0


# ---------------------------------------------------------------------------
# nvl
# ---------------------------------------------------------------------------


class TestNvl:
    def test_returns_value_when_not_none(self) -> None:
        assert nvl(42, 0) == 42

    def test_returns_default_when_none(self) -> None:
        assert nvl(None, 0) == 0

    def test_returns_empty_string_value(self) -> None:
        assert nvl("", "default") == ""

    def test_returns_zero_value(self) -> None:
        assert nvl(0, 99) == 0


# ---------------------------------------------------------------------------
# parse_tags
# ---------------------------------------------------------------------------


class TestParseTags:
    def test_extracts_severity(self) -> None:
        result = parse_tags(["safety", "severity:high", "regression"])
        assert result["tag_severity"] == "high"

    def test_extracts_tier(self) -> None:
        result = parse_tags(["tier:1", "safety"])
        assert result["tag_tier"] == 1

    def test_extracts_verify(self) -> None:
        result = parse_tags(["verify:python", "safety"])
        assert result["tag_verify"] == "python"

    def test_remaining_tags_sorted_alphabetically(self) -> None:
        result = parse_tags(
            [
                "safety",
                "regression",
                "batch",
                "severity:high",
                "tier:1",
                "verify:python",
            ]
        )
        assert result["tags_sorted"] == "batch,regression,safety"

    def test_empty_tags(self) -> None:
        result = parse_tags([])
        assert result["tag_severity"] == ""
        assert result["tag_tier"] == -1
        assert result["tag_verify"] == ""
        assert result["tags_sorted"] == ""

    def test_no_structured_tags(self) -> None:
        result = parse_tags(["safety", "regression"])
        assert result["tag_severity"] == ""
        assert result["tag_tier"] == -1
        assert result["tag_verify"] == ""
        assert result["tags_sorted"] == "regression,safety"

    def test_invalid_tier_kept_in_other(self) -> None:
        result = parse_tags(["tier:abc", "safety"])
        assert result["tag_tier"] == -1
        assert "tier:abc" in result["tags_sorted"]

    def test_all_structured_no_remaining(self) -> None:
        result = parse_tags(["severity:critical", "tier:2", "verify:llm"])
        assert result["tag_severity"] == "critical"
        assert result["tag_tier"] == 2
        assert result["tag_verify"] == "llm"
        assert result["tags_sorted"] == ""

    def test_score_tag_kept_in_other(self) -> None:
        result = parse_tags(["score:1", "tier:0", "verify:robot"])
        assert result["tag_tier"] == 0
        assert result["tag_verify"] == "robot"
        assert "score:1" in (result["tags_sorted"] or "")


# ---------------------------------------------------------------------------
# safe_int
# ---------------------------------------------------------------------------


class TestSafeInt:
    def test_valid_int(self) -> None:
        assert safe_int("42") == 42

    def test_none_returns_none(self) -> None:
        assert safe_int(None) is None

    def test_invalid_returns_none(self) -> None:
        assert safe_int("abc") is None


# ---------------------------------------------------------------------------
# extract_llm_metrics
# ---------------------------------------------------------------------------


class TestExtractLlmMetrics:
    def test_valid_json(self) -> None:
        data = '{"eval_count": 186, "eval_duration_ns": 16907870673, "eval_rate": 11.0}'
        result = extract_llm_metrics(data)
        assert result["eval_count"] == 186
        assert result["eval_duration_ns"] == 16907870673
        assert result["eval_rate"] == 11.0

    def test_none_returns_empty(self) -> None:
        assert extract_llm_metrics(None) == {}

    def test_invalid_json_returns_empty(self) -> None:
        assert extract_llm_metrics("not json") == {}

    def test_missing_keys_return_none(self) -> None:
        result = extract_llm_metrics('{"eval_count": 10}')
        assert result["eval_count"] == 10
        assert result.get("eval_duration_ns") is None

    def test_openai_metrics_passthrough(self) -> None:
        data = json.dumps(
            {
                "reasoning_tokens": 30,
                "cached_tokens": 20,
                "accepted_prediction_tokens": 10,
                "rejected_prediction_tokens": 5,
                "prompt_eval_count": 100,
                "eval_count": 50,
            }
        )
        result = extract_llm_metrics(data)
        assert result["reasoning_tokens"] == 30
        assert result["cached_tokens"] == 20
        assert result["accepted_prediction_tokens"] == 10
        assert result["rejected_prediction_tokens"] == 5

    def test_openai_metrics_missing_returns_none(self) -> None:
        result = extract_llm_metrics('{"eval_count": 10}')
        assert result.get("reasoning_tokens") is None
        assert result.get("cached_tokens") is None


# ---------------------------------------------------------------------------
# warn_near_miss
# ---------------------------------------------------------------------------


class TestWarnNearMiss:
    @patch("rfc.metrics.logger")
    def test_warns_on_lowercase(self, mock_logger: MagicMock) -> None:
        warn_near_miss("rfc_data:actual_answer:42")
        mock_logger.warn.assert_called_once()

    @patch("rfc.metrics.logger")
    def test_warns_on_missing_underscore(self, mock_logger: MagicMock) -> None:
        warn_near_miss("RFCDATA:actual_answer:42")
        mock_logger.warn.assert_called_once()

    @patch("rfc.metrics.logger")
    def test_warns_on_space(self, mock_logger: MagicMock) -> None:
        warn_near_miss("RFC DATA:actual_answer:42")
        mock_logger.warn.assert_called_once()

    @patch("rfc.metrics.logger")
    def test_no_warning_on_normal_message(self, mock_logger: MagicMock) -> None:
        warn_near_miss("Just a normal log message")
        mock_logger.warn.assert_not_called()


# ---------------------------------------------------------------------------
# get_robot_float / get_robot_int
# ---------------------------------------------------------------------------


class TestGetRobotFloat:
    def test_from_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEMPERATURE", "0.7")
        result = get_robot_float("TEMPERATURE")
        assert result == 0.7

    def test_invalid_env_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEMPERATURE", "not_a_float")
        result = get_robot_float("TEMPERATURE")
        assert result == 0.0

    def test_missing_env_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEMPERATURE", raising=False)
        result = get_robot_float("TEMPERATURE")
        assert result == 0.0


class TestGetRobotInt:
    def test_from_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SEED", "42")
        result = get_robot_int("SEED")
        assert result == 42

    def test_invalid_env_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SEED", "not_an_int")
        result = get_robot_int("SEED")
        assert result == 0

    def test_missing_env_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SEED", raising=False)
        result = get_robot_int("SEED")
        assert result == 0
