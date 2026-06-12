"""Tests for rfc.retry.retry_on_transient."""

from unittest.mock import MagicMock, call, patch

import pytest
import requests as req_lib

from rfc.retry import retry_on_transient


class TestRetryOnTransient:
    @patch("rfc.retry.logger")
    @patch("rfc.retry.time.sleep")
    def test_returns_result_on_first_success(self, mock_sleep, mock_logger):
        fn = MagicMock(return_value="ok")
        result = retry_on_transient(fn, max_retries=2)
        assert result == "ok"
        fn.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("rfc.retry.logger")
    @patch("rfc.retry.time.sleep")
    def test_retries_on_read_timeout(self, mock_sleep, mock_logger):
        fn = MagicMock(side_effect=[req_lib.exceptions.ReadTimeout("timed out"), "ok"])
        result = retry_on_transient(fn, max_retries=2)
        assert result == "ok"
        assert fn.call_count == 2
        mock_sleep.assert_called_once_with(2)

    @patch("rfc.retry.logger")
    @patch("rfc.retry.time.sleep")
    def test_retries_on_connection_error(self, mock_sleep, mock_logger):
        fn = MagicMock(
            side_effect=[req_lib.exceptions.ConnectionError("refused"), "ok"]
        )
        result = retry_on_transient(fn, max_retries=2)
        assert result == "ok"
        assert fn.call_count == 2

    @patch("rfc.retry.logger")
    @patch("rfc.retry.time.sleep")
    def test_exhausts_retries_then_raises(self, mock_sleep, mock_logger):
        fn = MagicMock(side_effect=req_lib.exceptions.ReadTimeout("timed out"))
        with pytest.raises(req_lib.exceptions.ReadTimeout):
            retry_on_transient(fn, max_retries=2)
        assert fn.call_count == 3  # 1 initial + 2 retries

    @patch("rfc.retry.logger")
    def test_no_retry_when_max_retries_zero(self, mock_logger):
        fn = MagicMock(side_effect=req_lib.exceptions.ReadTimeout("timed out"))
        with pytest.raises(req_lib.exceptions.ReadTimeout):
            retry_on_transient(fn, max_retries=0)
        fn.assert_called_once()

    @patch("rfc.retry.logger")
    @patch("rfc.retry.time.sleep")
    def test_exponential_backoff_timing(self, mock_sleep, mock_logger):
        fn = MagicMock(side_effect=req_lib.exceptions.ReadTimeout("timed out"))
        with pytest.raises(req_lib.exceptions.ReadTimeout):
            retry_on_transient(fn, max_retries=2)
        assert mock_sleep.call_args_list == [call(2), call(4)]

    @patch("rfc.retry.logger")
    @patch("rfc.retry.time.sleep")
    def test_non_transient_error_propagates(self, mock_sleep, mock_logger):
        fn = MagicMock(side_effect=req_lib.exceptions.HTTPError("500 Server Error"))
        with pytest.raises(req_lib.exceptions.HTTPError):
            retry_on_transient(fn, max_retries=2)
        fn.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("rfc.retry.logger")
    @patch("rfc.retry.time.sleep")
    def test_logs_warn_on_retry_and_error_on_exhaust(self, mock_sleep, mock_logger):
        fn = MagicMock(side_effect=req_lib.exceptions.ReadTimeout("timed out"))
        with pytest.raises(req_lib.exceptions.ReadTimeout):
            retry_on_transient(fn, max_retries=1)

        # First attempt fails -> warn about retry
        mock_logger.warn.assert_called_once()
        warn_msg = mock_logger.warn.call_args[0][0]
        assert "attempt 1 failed" in warn_msg
        assert "Retrying in 2s" in warn_msg

        # Second attempt fails -> error (exhausted)
        mock_logger.error.assert_called_once()
        error_msg = mock_logger.error.call_args[0][0]
        assert "failed after 2 attempts" in error_msg


def _http_error(status_code: int) -> req_lib.exceptions.HTTPError:
    """Build an HTTPError carrying a response with the given status code."""
    response = MagicMock(status_code=status_code)
    return req_lib.exceptions.HTTPError(f"{status_code} error", response=response)


class TestRetryOn429:
    """Rate-limit (429) responses back off and retry like transient errors (#507)."""

    @patch("rfc.retry.logger")
    @patch("rfc.retry.time.sleep")
    def test_429_retried_with_backoff(self, mock_sleep, mock_logger):
        fn = MagicMock(side_effect=[_http_error(429), "ok"])
        result = retry_on_transient(fn, max_retries=2)
        assert result == "ok"
        assert fn.call_count == 2
        mock_sleep.assert_called_once_with(2)

    @patch("rfc.retry.logger")
    @patch("rfc.retry.time.sleep")
    def test_429_exhausts_retries_then_raises(self, mock_sleep, mock_logger):
        fn = MagicMock(side_effect=_http_error(429))
        with pytest.raises(req_lib.exceptions.HTTPError):
            retry_on_transient(fn, max_retries=2)
        assert fn.call_count == 3

    @patch("rfc.retry.logger")
    @patch("rfc.retry.time.sleep")
    def test_429_backoff_sequence_is_2_4_8(self, mock_sleep, mock_logger):
        """PR #514 claims 2/4/8s backoff on 429; that needs max_retries=3.

        Note: OpenAIClient's default max_retries=2 yields only 2/4 before
        propagating — the full 2/4/8 sequence requires configuring
        max_retries=3 on the client.
        """
        fn = MagicMock(side_effect=_http_error(429))
        with pytest.raises(req_lib.exceptions.HTTPError):
            retry_on_transient(fn, max_retries=3)
        assert fn.call_count == 4
        assert mock_sleep.call_args_list == [call(2), call(4), call(8)]

    @patch("rfc.retry.logger")
    @patch("rfc.retry.time.sleep")
    def test_non_429_http_error_propagates_immediately(self, mock_sleep, mock_logger):
        fn = MagicMock(side_effect=_http_error(500))
        with pytest.raises(req_lib.exceptions.HTTPError):
            retry_on_transient(fn, max_retries=2)
        fn.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("rfc.retry.logger")
    @patch("rfc.retry.time.sleep")
    def test_http_error_without_response_propagates(self, mock_sleep, mock_logger):
        fn = MagicMock(side_effect=req_lib.exceptions.HTTPError("no response"))
        with pytest.raises(req_lib.exceptions.HTTPError):
            retry_on_transient(fn, max_retries=2)
        fn.assert_called_once()
