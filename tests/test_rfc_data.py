"""Tests for rfc.rfc_data — centralized RFC_DATA emission helper."""

from unittest.mock import patch

import pytest


class TestEmitRfcData:
    """Tests for the emit_rfc_data() helper function."""

    @patch("rfc.rfc_data.logger")
    def test_formats_correctly(self, mock_logger):
        from rfc.rfc_data import emit_rfc_data

        emit_rfc_data("actual_answer", "42")
        mock_logger.info.assert_called_once_with("RFC_DATA:actual_answer:42")

    @patch("rfc.rfc_data.logger")
    def test_preserves_colons_in_value(self, mock_logger):
        from rfc.rfc_data import emit_rfc_data

        emit_rfc_data("grading_reason", "Score: 1/1, reason: correct")
        mock_logger.info.assert_called_once_with(
            "RFC_DATA:grading_reason:Score: 1/1, reason: correct"
        )

    @patch("rfc.rfc_data.logger")
    def test_empty_value(self, mock_logger):
        from rfc.rfc_data import emit_rfc_data

        emit_rfc_data("key", "")
        mock_logger.info.assert_called_once_with("RFC_DATA:key:")

    def test_rejects_empty_key(self):
        from rfc.rfc_data import emit_rfc_data

        with pytest.raises(ValueError, match="must not be empty"):
            emit_rfc_data("", "value")

    def test_rejects_key_with_colon(self):
        from rfc.rfc_data import emit_rfc_data

        with pytest.raises(ValueError, match="must not contain ':'"):
            emit_rfc_data("bad:key", "value")

    def test_prefix_constant_value(self):
        from rfc.rfc_data import RFC_DATA_PREFIX

        assert RFC_DATA_PREFIX == "RFC_DATA:"
