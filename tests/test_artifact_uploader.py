"""Tests for dashboard.core.artifact_uploader."""

import os
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dashboard.core.artifact_uploader import (
    _find_output_xml,
    _parse_rf_timestamp,
    _import_output_xml,
    upload_session_results,
)


MINIMAL_OUTPUT_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<robot generator="Robot" generated="2024-02-13T12:00:00.000000">
  <suite name="TestSuite" source="/tests">
    <test name="Test Addition">
      <tags><tag>score:1</tag><tag>IQ:100</tag></tags>
      <doc>What is 2+2?</doc>
      <msg>Answer: 4</msg>
      <status status="PASS" start="2024-02-13T12:00:01.000000" end="2024-02-13T12:00:02.000000"/>
    </test>
    <test name="Test Subtraction">
      <tags><tag>score:0</tag></tags>
      <doc>What is 5-3?</doc>
      <status status="FAIL" start="2024-02-13T12:00:03.000000" end="2024-02-13T12:00:04.000000"/>
    </test>
    <metadata>
      <item name="Model">llama3</item>
      <item name="Timestamp">2024-02-13T12:00:00</item>
    </metadata>
    <status status="FAIL" start="2024-02-13T12:00:00.000000" end="2024-02-13T12:00:05.000000"/>
  </suite>
  <statistics>
    <total>
      <stat pass="1" fail="1" skip="0">All Tests</stat>
    </total>
  </statistics>
</robot>
"""


# ---------------------------------------------------------------------------
# _find_output_xml
# ---------------------------------------------------------------------------


class TestFindOutputXml:
    def test_finds_plain_output_xml(self, tmp_path):
        (tmp_path / "output.xml").write_text("<robot/>")
        result = _find_output_xml(tmp_path)
        assert result == tmp_path / "output.xml"

    def test_finds_timestamped_variant(self, tmp_path):
        (tmp_path / "output-20240213-123456.xml").write_text("<robot/>")
        result = _find_output_xml(tmp_path)
        assert result is not None
        assert "output-20240213" in str(result)

    def test_prefers_plain_over_timestamped(self, tmp_path):
        (tmp_path / "output.xml").write_text("<robot/>")
        (tmp_path / "output-20240213-123456.xml").write_text("<robot/>")
        result = _find_output_xml(tmp_path)
        assert result == tmp_path / "output.xml"

    def test_returns_none_when_empty(self, tmp_path):
        result = _find_output_xml(tmp_path)
        assert result is None

    def test_returns_most_recent_timestamped(self, tmp_path):
        (tmp_path / "output-20240101-000000.xml").write_text("<robot/>")
        (tmp_path / "output-20240213-123456.xml").write_text("<robot/>")
        result = _find_output_xml(tmp_path)
        assert "20240213" in str(result)

    def test_invalid_type(self):
        with pytest.raises(TypeError, match="session_dir must be a Path"):
            _find_output_xml("/some/string/path")


# ---------------------------------------------------------------------------
# _parse_rf_timestamp
# ---------------------------------------------------------------------------


class TestParseRfTimestamp:
    def test_iso_format(self):
        result = _parse_rf_timestamp("2024-02-13T12:34:56.789000")
        assert isinstance(result, datetime)
        assert result.year == 2024
        assert result.month == 2
        assert result.day == 13

    def test_old_format(self):
        result = _parse_rf_timestamp("20240213 12:34:56.789")
        assert isinstance(result, datetime)
        assert result.year == 2024

    def test_empty_string_returns_none(self):
        assert _parse_rf_timestamp("") is None

    def test_invalid_format_returns_none(self):
        assert _parse_rf_timestamp("not a date") is None

    def test_invalid_type(self):
        with pytest.raises(TypeError, match="ts must be a str"):
            _parse_rf_timestamp(12345)


# ---------------------------------------------------------------------------
# _import_output_xml
# ---------------------------------------------------------------------------


class TestImportOutputXml:
    def test_imports_valid_xml(self, tmp_path, tmp_db):
        xml_file = tmp_path / "output.xml"
        xml_file.write_text(MINIMAL_OUTPUT_XML)
        run_id = _import_output_xml(str(xml_file), tmp_db)
        assert isinstance(run_id, int)
        assert run_id > 0

    def test_extracts_statistics(self, tmp_path, tmp_db):
        xml_file = tmp_path / "output.xml"
        xml_file.write_text(MINIMAL_OUTPUT_XML)
        run_id = _import_output_xml(str(xml_file), tmp_db)
        runs = tmp_db.get_recent_runs(limit=1)
        assert len(runs) == 1
        assert runs[0]["passed"] == 1
        assert runs[0]["failed"] == 1

    def test_extracts_model_metadata(self, tmp_path, tmp_db):
        xml_file = tmp_path / "output.xml"
        xml_file.write_text(MINIMAL_OUTPUT_XML)
        _import_output_xml(str(xml_file), tmp_db)
        runs = tmp_db.get_recent_runs(limit=1)
        assert runs[0]["model_name"] == "llama3"

    def test_extracts_duration(self, tmp_path, tmp_db):
        xml_file = tmp_path / "output.xml"
        xml_file.write_text(MINIMAL_OUTPUT_XML)
        _import_output_xml(str(xml_file), tmp_db)
        runs = tmp_db.get_recent_runs(limit=1)
        assert runs[0]["duration_seconds"] == 5.0


# ---------------------------------------------------------------------------
# upload_session_results
# ---------------------------------------------------------------------------


class TestUploadSessionResults:
    def test_missing_session_dir(self, tmp_path):
        result = upload_session_results("nonexist", output_dir=str(tmp_path))
        assert result["status"] == "error"
        assert "not found" in result["message"]

    def test_no_output_xml(self, tmp_path):
        session_dir = tmp_path / "test_session"
        session_dir.mkdir()
        result = upload_session_results(
            "test_session", output_dir=str(tmp_path)
        )
        assert result["status"] == "error"
        assert "No output.xml" in result["message"]

    def test_success(self, tmp_path):
        session_dir = tmp_path / "test_session"
        session_dir.mkdir()
        (session_dir / "output.xml").write_text(MINIMAL_OUTPUT_XML)

        with patch.dict(os.environ, {"DATABASE_URL": ""}, clear=False):
            result = upload_session_results(
                "test_session", output_dir=str(tmp_path)
            )

        assert result["status"] == "success"
        assert result["run_id"] > 0
        assert result["backend"] == "SQLite"

    def test_empty_session_id(self):
        with pytest.raises(ValueError, match="non-empty string"):
            upload_session_results("")

    def test_invalid_session_id_type(self):
        with pytest.raises(TypeError, match="session_id must be a str"):
            upload_session_results(123)

    def test_database_error_returns_error_dict(self, tmp_path):
        session_dir = tmp_path / "test_session"
        session_dir.mkdir()
        (session_dir / "output.xml").write_text(MINIMAL_OUTPUT_XML)

        with patch(
            "dashboard.core.artifact_uploader.TestDatabase",
            side_effect=RuntimeError("db connection failed"),
        ):
            result = upload_session_results(
                "test_session", output_dir=str(tmp_path)
            )
        assert result["status"] == "error"
        assert "Upload failed" in result["message"]
