"""Tests for the import_test_results bridge.

Covers timestamp parsing, output.xml parsing, metadata extraction,
per-test result extraction, and end-to-end import with database writes.
"""

import os
import tempfile
from datetime import datetime
from unittest.mock import MagicMock, patch
from xml.etree.ElementTree import ParseError

import pytest

from scripts.import_test_results import (
    _parse_rf_timestamp,
    import_results,
    parse_output_xml,
)


# ── Minimal output.xml fixtures ──────────────────────────────────────

MINIMAL_OUTPUT_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<robot generator="Robot 7.0" generated="2025-06-15T10:00:00.000000">
  <suite name="Math Tests" id="s1">
    <metadata>
      <item name="Model">llama3</item>
      <item name="Commit_SHA">abc123</item>
      <item name="Branch">main</item>
      <item name="Pipeline_URL">https://gl.test/p/500</item>
      <item name="Runner_ID">runner-1</item>
      <item name="Runner_Tags">ollama,gpu</item>
      <item name="Timestamp">2025-06-15T10:00:00</item>
    </metadata>
    <test name="IQ 100 Basic Addition" id="s1-t1">
      <doc>What is 2 + 2?</doc>
      <tags>
        <tag>score:1</tag>
      </tags>
      <msg>Answer: 4</msg>
      <msg>Expected: 4</msg>
      <status status="PASS" start="2025-06-15T10:00:01.000000" end="2025-06-15T10:00:02.000000"/>
    </test>
    <test name="IQ 100 Basic Subtraction" id="s1-t2">
      <doc>What is 5 - 3?</doc>
      <tags>
        <tag>score:0</tag>
      </tags>
      <msg>Answer: 1</msg>
      <msg>Expected: 2</msg>
      <status status="FAIL" start="2025-06-15T10:00:03.000000" end="2025-06-15T10:00:04.000000"/>
    </test>
    <status status="FAIL" start="2025-06-15T10:00:00.000000" end="2025-06-15T10:00:05.000000"/>
  </suite>
  <statistics>
    <total>
      <stat pass="1" fail="1" skip="0">All Tests</stat>
    </total>
  </statistics>
</robot>
"""

NESTED_SUITES_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<robot generator="Rebot 7.0" generated="2025-06-15T12:00:00.000000">
  <suite name="Combined Results" id="s1">
    <suite name="Math Tests" id="s1-s1">
      <metadata>
        <item name="Model">mistral</item>
      </metadata>
      <test name="Addition" id="s1-s1-t1">
        <status status="PASS"/>
      </test>
      <status status="PASS" start="2025-06-15T12:00:00.000000" end="2025-06-15T12:00:01.000000"/>
    </suite>
    <suite name="Docker Tests" id="s1-s2">
      <test name="Container Start" id="s1-s2-t1">
        <status status="PASS"/>
      </test>
      <test name="Container Stop" id="s1-s2-t1">
        <status status="FAIL"/>
      </test>
      <status status="FAIL" start="2025-06-15T12:00:01.000000" end="2025-06-15T12:00:03.000000"/>
    </suite>
    <status status="FAIL" start="2025-06-15T12:00:00.000000" end="2025-06-15T12:00:03.000000"/>
  </suite>
  <statistics>
    <total>
      <stat pass="2" fail="1" skip="0">All Tests</stat>
    </total>
  </statistics>
</robot>
"""

EMPTY_SUITE_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<robot generator="Robot 7.0" generated="2025-06-15T10:00:00.000000">
  <suite name="Empty Suite" id="s1">
    <status status="PASS" start="2025-06-15T10:00:00.000000" end="2025-06-15T10:00:00.100000"/>
  </suite>
  <statistics>
    <total>
      <stat pass="0" fail="0" skip="0">All Tests</stat>
    </total>
  </statistics>
</robot>
"""

NO_METADATA_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<robot generator="Robot 7.0" generated="2025-06-15T10:00:00.000000">
  <suite name="Plain Suite" id="s1">
    <test name="Simple Test" id="s1-t1">
      <status status="PASS"/>
    </test>
    <status status="PASS" start="2025-06-15T10:00:00.000000" end="2025-06-15T10:00:01.000000"/>
  </suite>
  <statistics>
    <total>
      <stat pass="1" fail="0" skip="0">All Tests</stat>
    </total>
  </statistics>
</robot>
"""

SKIP_TESTS_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<robot generator="Robot 7.0" generated="2025-06-15T10:00:00.000000">
  <suite name="Skip Suite" id="s1">
    <test name="Skipped Test" id="s1-t1">
      <status status="SKIP"/>
    </test>
    <test name="Passing Test" id="s1-t2">
      <status status="PASS"/>
    </test>
    <status status="PASS" start="2025-06-15T10:00:00.000000" end="2025-06-15T10:00:01.000000"/>
  </suite>
  <statistics>
    <total>
      <stat pass="1" fail="0" skip="1">All Tests</stat>
    </total>
  </statistics>
</robot>
"""

LEGACY_TIMESTAMP_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<robot generator="Robot 5.0" generated="20240213 12:34:56.789">
  <suite name="Legacy Suite" id="s1">
    <test name="Old Test" id="s1-t1">
      <status status="PASS" starttime="20240213 12:34:56.789" endtime="20240213 12:34:57.123"/>
    </test>
    <status status="PASS" starttime="20240213 12:34:56.000" endtime="20240213 12:35:00.000"/>
  </suite>
  <statistics>
    <total>
      <stat pass="1" fail="0" skip="0">All Tests</stat>
    </total>
  </statistics>
</robot>
"""

LEGACY_METADATA_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<robot generator="Robot 7.0" generated="2025-06-15T10:00:00.000000">
  <suite name="Legacy Meta" id="s1">
    <metadata>
      <item name="GitLab Commit">def456</item>
      <item name="GitLab Branch">feature-x</item>
      <item name="GitLab Pipeline">https://gl.test/p/600</item>
      <item name="Runner ID">runner-2</item>
      <item name="Runner Tags">docker</item>
    </metadata>
    <test name="Test 1" id="s1-t1">
      <status status="PASS"/>
    </test>
    <status status="PASS" start="2025-06-15T10:00:00.000000" end="2025-06-15T10:00:01.000000"/>
  </suite>
  <statistics>
    <total>
      <stat pass="1" fail="0" skip="0">All Tests</stat>
    </total>
  </statistics>
</robot>
"""


def _write_xml(content: str) -> str:
    """Write XML content to a temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".xml")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


# ── _parse_rf_timestamp tests ────────────────────────────────────────


class TestParseRfTimestamp:
    """Tests for Robot Framework timestamp parsing."""

    def test_iso_format(self):
        """Parses ISO 8601 timestamp from RF 7.x."""
        result = _parse_rf_timestamp("2025-06-15T10:30:45.123456")
        assert result == datetime(2025, 6, 15, 10, 30, 45, 123456)

    def test_iso_format_no_microseconds(self):
        """Parses ISO timestamp without microseconds."""
        result = _parse_rf_timestamp("2025-06-15T10:30:45")
        assert result == datetime(2025, 6, 15, 10, 30, 45)

    def test_legacy_format(self):
        """Parses legacy RF 5.x/6.x timestamp: YYYYMMDD HH:MM:SS.mmm."""
        result = _parse_rf_timestamp("20240213 12:34:56.789")
        assert result is not None
        assert result.year == 2024
        assert result.month == 2
        assert result.day == 13
        assert result.hour == 12
        assert result.minute == 34
        assert result.second == 56

    def test_empty_string_returns_none(self):
        """Returns None for empty string."""
        assert _parse_rf_timestamp("") is None

    def test_none_returns_none(self):
        """Returns None for None input."""
        assert _parse_rf_timestamp(None) is None

    def test_garbage_returns_none(self):
        """Returns None for unparseable string."""
        assert _parse_rf_timestamp("not-a-timestamp") is None


# ── parse_output_xml tests ───────────────────────────────────────────


class TestParseOutputXml:
    """Tests for output.xml parsing."""

    def test_minimal_suite(self):
        """Parses a minimal output.xml with two tests."""
        path = _write_xml(MINIMAL_OUTPUT_XML)
        try:
            data = parse_output_xml(path)
            assert data["suite_name"] == "Math Tests"
            assert data["passed"] == 1
            assert data["failed"] == 1
            assert data["skipped"] == 0
            assert data["total_tests"] == 2
        finally:
            os.unlink(path)

    def test_duration_calculated(self):
        """Duration is calculated from suite start/end times."""
        path = _write_xml(MINIMAL_OUTPUT_XML)
        try:
            data = parse_output_xml(path)
            assert data["duration"] == 5.0
        finally:
            os.unlink(path)

    def test_metadata_extracted(self):
        """Metadata items are extracted from suite."""
        path = _write_xml(MINIMAL_OUTPUT_XML)
        try:
            data = parse_output_xml(path)
            assert data["metadata"]["Model"] == "llama3"
            assert data["metadata"]["Commit_SHA"] == "abc123"
            assert data["metadata"]["Branch"] == "main"
            assert data["metadata"]["Pipeline_URL"] == "https://gl.test/p/500"
        finally:
            os.unlink(path)

    def test_test_results_extracted(self):
        """Per-test results are extracted with status and score."""
        path = _write_xml(MINIMAL_OUTPUT_XML)
        try:
            data = parse_output_xml(path)
            results = data["test_results"]
            assert len(results) == 2

            addition = results[0]
            assert addition["name"] == "IQ 100 Basic Addition"
            assert addition["status"] == "PASS"
            assert addition["score"] == 1
            assert addition["question"] == "What is 2 + 2?"

            subtraction = results[1]
            assert subtraction["name"] == "IQ 100 Basic Subtraction"
            assert subtraction["status"] == "FAIL"
            assert subtraction["score"] == 0
        finally:
            os.unlink(path)

    def test_nested_suites(self):
        """Parses combined rebot output with nested sub-suites."""
        path = _write_xml(NESTED_SUITES_XML)
        try:
            data = parse_output_xml(path)
            assert data["suite_name"] == "Combined Results"
            assert data["passed"] == 2
            assert data["failed"] == 1
            assert data["total_tests"] == 3
            assert len(data["test_results"]) == 3
        finally:
            os.unlink(path)

    def test_nested_suite_metadata_found(self):
        """Metadata from nested sub-suites is found via recursive search."""
        path = _write_xml(NESTED_SUITES_XML)
        try:
            data = parse_output_xml(path)
            assert data["metadata"]["Model"] == "mistral"
        finally:
            os.unlink(path)

    def test_empty_suite(self):
        """Handles suites with no tests."""
        path = _write_xml(EMPTY_SUITE_XML)
        try:
            data = parse_output_xml(path)
            assert data["suite_name"] == "Empty Suite"
            assert data["total_tests"] == 0
            assert data["passed"] == 0
            assert data["test_results"] == []
        finally:
            os.unlink(path)

    def test_no_metadata(self):
        """Handles suites without metadata section."""
        path = _write_xml(NO_METADATA_XML)
        try:
            data = parse_output_xml(path)
            assert data["metadata"] == {}
            assert data["passed"] == 1
        finally:
            os.unlink(path)

    def test_skipped_tests(self):
        """Counts skipped tests separately from total."""
        path = _write_xml(SKIP_TESTS_XML)
        try:
            data = parse_output_xml(path)
            assert data["passed"] == 1
            assert data["skipped"] == 1
            assert data["total_tests"] == 1  # total = pass + fail, not skip
        finally:
            os.unlink(path)

    def test_legacy_timestamps(self):
        """Parses duration from legacy RF timestamp format."""
        path = _write_xml(LEGACY_TIMESTAMP_XML)
        try:
            data = parse_output_xml(path)
            assert data["duration"] == 4.0
        finally:
            os.unlink(path)

    def test_malformed_xml_raises(self):
        """Raises ParseError for malformed XML."""
        path = _write_xml("<not valid xml")
        try:
            with pytest.raises(ParseError):
                parse_output_xml(path)
        finally:
            os.unlink(path)

    def test_answer_extraction(self):
        """Extracts actual and expected answers from msg elements."""
        path = _write_xml(MINIMAL_OUTPUT_XML)
        try:
            data = parse_output_xml(path)
            addition = data["test_results"][0]
            assert addition["actual_answer"] == "Answer: 4"
            assert addition["expected_answer"] == "Expected: 4"
        finally:
            os.unlink(path)

    def test_score_tag_parsing(self):
        """Parses score from tag like 'score:1'."""
        path = _write_xml(MINIMAL_OUTPUT_XML)
        try:
            data = parse_output_xml(path)
            assert data["test_results"][0]["score"] == 1
            assert data["test_results"][1]["score"] == 0
        finally:
            os.unlink(path)

    def test_no_score_tag(self):
        """Score is None when no score tag is present."""
        path = _write_xml(NO_METADATA_XML)
        try:
            data = parse_output_xml(path)
            assert data["test_results"][0]["score"] is None
        finally:
            os.unlink(path)


# ── import_results tests ─────────────────────────────────────────────


class TestImportResults:
    """Tests for the end-to-end import_results function."""

    def test_import_creates_test_run(self):
        """Creates a TestRun in the database from output.xml."""
        path = _write_xml(MINIMAL_OUTPUT_XML)
        try:
            db = MagicMock()
            db.add_test_run.return_value = 42

            run_id = import_results(path, db)
            assert run_id == 42

            db.add_test_run.assert_called_once()
            run = db.add_test_run.call_args[0][0]
            assert run.model_name == "llama3"
            assert run.test_suite == "Math Tests"
            assert run.passed == 1
            assert run.failed == 1
            assert run.total_tests == 2
            assert run.git_commit == "abc123"
            assert run.git_branch == "main"
            assert run.pipeline_url == "https://gl.test/p/500"
            assert run.runner_id == "runner-1"
            assert run.runner_tags == "ollama,gpu"
        finally:
            os.unlink(path)

    def test_import_creates_test_results(self):
        """Creates TestResult rows for each test case."""
        path = _write_xml(MINIMAL_OUTPUT_XML)
        try:
            db = MagicMock()
            db.add_test_run.return_value = 42

            import_results(path, db)

            db.add_test_results.assert_called_once()
            results = db.add_test_results.call_args[0][0]
            assert len(results) == 2
            assert all(r.run_id == 42 for r in results)
            assert results[0].test_name == "IQ 100 Basic Addition"
            assert results[0].test_status == "PASS"
            assert results[0].score == 1
            assert results[1].test_name == "IQ 100 Basic Subtraction"
            assert results[1].test_status == "FAIL"
        finally:
            os.unlink(path)

    def test_import_model_name_override(self):
        """Model name can be overridden via parameter."""
        path = _write_xml(MINIMAL_OUTPUT_XML)
        try:
            db = MagicMock()
            db.add_test_run.return_value = 1

            import_results(path, db, model_name="custom-model")

            run = db.add_test_run.call_args[0][0]
            assert run.model_name == "custom-model"
        finally:
            os.unlink(path)

    @patch.dict(os.environ, {"DEFAULT_MODEL": "env-model"}, clear=False)
    def test_import_model_from_env_when_no_metadata(self):
        """Falls back to DEFAULT_MODEL env var when metadata lacks Model."""
        path = _write_xml(NO_METADATA_XML)
        try:
            db = MagicMock()
            db.add_test_run.return_value = 1

            import_results(path, db)

            run = db.add_test_run.call_args[0][0]
            assert run.model_name == "env-model"
        finally:
            os.unlink(path)

    def test_import_legacy_metadata_keys(self):
        """Resolves git info from legacy GitLab-specific metadata keys."""
        path = _write_xml(LEGACY_METADATA_XML)
        try:
            db = MagicMock()
            db.add_test_run.return_value = 1

            import_results(path, db)

            run = db.add_test_run.call_args[0][0]
            assert run.git_commit == "def456"
            assert run.git_branch == "feature-x"
            assert run.pipeline_url == "https://gl.test/p/600"
            assert run.runner_id == "runner-2"
            assert run.runner_tags == "docker"
        finally:
            os.unlink(path)

    @patch.dict(
        os.environ,
        {
            "CI_COMMIT_SHA": "env-sha",
            "CI_COMMIT_REF_NAME": "env-branch",
            "CI_PIPELINE_URL": "https://gl.test/env-pipeline",
            "CI_RUNNER_ID": "env-runner",
            "CI_RUNNER_TAGS": "env-tags",
        },
        clear=False,
    )
    def test_import_fallback_to_env_vars(self):
        """Falls back to CI_* env vars when metadata has no git info."""
        path = _write_xml(NO_METADATA_XML)
        try:
            db = MagicMock()
            db.add_test_run.return_value = 1

            import_results(path, db)

            run = db.add_test_run.call_args[0][0]
            assert run.git_commit == "env-sha"
            assert run.git_branch == "env-branch"
            assert run.pipeline_url == "https://gl.test/env-pipeline"
            assert run.runner_id == "env-runner"
            assert run.runner_tags == "env-tags"
        finally:
            os.unlink(path)

    def test_import_empty_suite(self):
        """Handles empty suite with no tests."""
        path = _write_xml(EMPTY_SUITE_XML)
        try:
            db = MagicMock()
            db.add_test_run.return_value = 1

            run_id = import_results(path, db)
            assert run_id == 1

            run = db.add_test_run.call_args[0][0]
            assert run.total_tests == 0
            assert run.passed == 0

            results = db.add_test_results.call_args[0][0]
            assert results == []
        finally:
            os.unlink(path)

    def test_import_sets_rfc_version(self):
        """TestRun includes the rfc_version field."""
        path = _write_xml(MINIMAL_OUTPUT_XML)
        try:
            db = MagicMock()
            db.add_test_run.return_value = 1

            import_results(path, db)

            run = db.add_test_run.call_args[0][0]
            assert run.rfc_version is not None
        finally:
            os.unlink(path)

    def test_import_timestamp_from_metadata(self):
        """Uses Timestamp from metadata when available."""
        path = _write_xml(MINIMAL_OUTPUT_XML)
        try:
            db = MagicMock()
            db.add_test_run.return_value = 1

            import_results(path, db)

            run = db.add_test_run.call_args[0][0]
            assert run.timestamp == datetime(2025, 6, 15, 10, 0, 0)
        finally:
            os.unlink(path)

    def test_import_timestamp_defaults_to_now(self):
        """Falls back to datetime.now() when metadata has no Timestamp."""
        path = _write_xml(NO_METADATA_XML)
        try:
            db = MagicMock()
            db.add_test_run.return_value = 1

            before = datetime.now()
            import_results(path, db)
            after = datetime.now()

            run = db.add_test_run.call_args[0][0]
            assert before <= run.timestamp <= after
        finally:
            os.unlink(path)

    def test_import_duration(self):
        """Duration is passed through from XML parsing."""
        path = _write_xml(MINIMAL_OUTPUT_XML)
        try:
            db = MagicMock()
            db.add_test_run.return_value = 1

            import_results(path, db)

            run = db.add_test_run.call_args[0][0]
            assert run.duration_seconds == 5.0
        finally:
            os.unlink(path)

    def test_import_nested_suites(self):
        """Imports combined rebot output with nested suites."""
        path = _write_xml(NESTED_SUITES_XML)
        try:
            db = MagicMock()
            db.add_test_run.return_value = 1

            import_results(path, db)

            run = db.add_test_run.call_args[0][0]
            assert run.test_suite == "Combined Results"
            assert run.total_tests == 3
            assert run.passed == 2
            assert run.failed == 1

            results = db.add_test_results.call_args[0][0]
            assert len(results) == 3
        finally:
            os.unlink(path)
