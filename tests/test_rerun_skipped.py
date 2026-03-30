"""Tests for the rerun_skipped helper module.

Covers collect_skipped() with various output.xml scenarios and
the CLI entry point.
"""

from pathlib import Path

import pytest

from src.rfc.rerun_skipped import collect_skipped, main


MIXED_OUTPUT_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<robot generator="Robot 7.0" generated="2025-06-15T10:00:00.000000">
  <suite name="Example" id="s1">
    <test name="Passing Test" id="s1-t1">
      <status status="PASS" start="2025-06-15T10:00:01.000000" end="2025-06-15T10:00:02.000000"/>
    </test>
    <test name="Failing Test" id="s1-t2">
      <status status="FAIL" start="2025-06-15T10:00:02.000000" end="2025-06-15T10:00:03.000000">
        AssertionError
      </status>
    </test>
    <test name="Skipped Test" id="s1-t3">
      <status status="SKIP" start="2025-06-15T10:00:03.000000" end="2025-06-15T10:00:03.000000">
        Test skipped
      </status>
    </test>
    <status status="FAIL" start="2025-06-15T10:00:00.000000" end="2025-06-15T10:00:05.000000"/>
  </suite>
  <statistics>
    <total><stat pass="1" fail="1" skip="1">All Tests</stat></total>
  </statistics>
</robot>
"""

ALL_PASS_OUTPUT_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<robot generator="Robot 7.0" generated="2025-06-15T10:00:00.000000">
  <suite name="Example" id="s1">
    <test name="Test One" id="s1-t1">
      <status status="PASS" start="2025-06-15T10:00:01.000000" end="2025-06-15T10:00:02.000000"/>
    </test>
    <status status="PASS" start="2025-06-15T10:00:00.000000" end="2025-06-15T10:00:05.000000"/>
  </suite>
  <statistics>
    <total><stat pass="1" fail="0" skip="0">All Tests</stat></total>
  </statistics>
</robot>
"""

NESTED_SKIPPED_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<robot generator="Robot 7.0" generated="2025-06-15T10:00:00.000000">
  <suite name="Root" id="s1">
    <suite name="Child" id="s1-s1">
      <test name="Nested Skip" id="s1-s1-t1">
        <status status="SKIP" start="2025-06-15T10:00:01.000000" end="2025-06-15T10:00:01.000000">
          Skipped
        </status>
      </test>
      <test name="Nested Pass" id="s1-s1-t2">
        <status status="PASS" start="2025-06-15T10:00:02.000000" end="2025-06-15T10:00:03.000000"/>
      </test>
      <status status="PASS" start="2025-06-15T10:00:00.000000" end="2025-06-15T10:00:05.000000"/>
    </suite>
    <status status="PASS" start="2025-06-15T10:00:00.000000" end="2025-06-15T10:00:05.000000"/>
  </suite>
  <statistics>
    <total><stat pass="1" fail="0" skip="1">All Tests</stat></total>
  </statistics>
</robot>
"""

MULTI_SKIPPED_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<robot generator="Robot 7.0" generated="2025-06-15T10:00:00.000000">
  <suite name="Suite" id="s1">
    <test name="Skip A" id="s1-t1">
      <status status="SKIP" start="2025-06-15T10:00:01.000000" end="2025-06-15T10:00:01.000000">
        Skipped
      </status>
    </test>
    <test name="Skip B" id="s1-t2">
      <status status="SKIP" start="2025-06-15T10:00:02.000000" end="2025-06-15T10:00:02.000000">
        Skipped
      </status>
    </test>
    <test name="Pass C" id="s1-t3">
      <status status="PASS" start="2025-06-15T10:00:03.000000" end="2025-06-15T10:00:04.000000"/>
    </test>
    <status status="PASS" start="2025-06-15T10:00:00.000000" end="2025-06-15T10:00:05.000000"/>
  </suite>
  <statistics>
    <total><stat pass="1" fail="0" skip="2">All Tests</stat></total>
  </statistics>
</robot>
"""


class TestCollectSkipped:
    def test_mixed_statuses(self, tmp_path: Path) -> None:
        xml = tmp_path / "output.xml"
        xml.write_text(MIXED_OUTPUT_XML)
        result = collect_skipped(str(xml))
        assert result == ["Example.Skipped Test"]

    def test_no_skipped(self, tmp_path: Path) -> None:
        xml = tmp_path / "output.xml"
        xml.write_text(ALL_PASS_OUTPUT_XML)
        result = collect_skipped(str(xml))
        assert result == []

    def test_nested_suites(self, tmp_path: Path) -> None:
        xml = tmp_path / "output.xml"
        xml.write_text(NESTED_SKIPPED_XML)
        result = collect_skipped(str(xml))
        assert result == ["Root.Child.Nested Skip"]

    def test_multiple_skipped(self, tmp_path: Path) -> None:
        xml = tmp_path / "output.xml"
        xml.write_text(MULTI_SKIPPED_XML)
        result = collect_skipped(str(xml))
        assert result == ["Suite.Skip A", "Suite.Skip B"]


class TestMain:
    def test_prints_test_flags(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        xml = tmp_path / "output.xml"
        xml.write_text(MIXED_OUTPUT_XML)
        monkeypatch.setattr("sys.argv", ["rerun_skipped", str(xml)])
        main()
        captured = capsys.readouterr()
        assert captured.out.strip() == "--test\nExample.Skipped Test"

    def test_no_output_when_no_skipped(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        xml = tmp_path / "output.xml"
        xml.write_text(ALL_PASS_OUTPUT_XML)
        monkeypatch.setattr("sys.argv", ["rerun_skipped", str(xml)])
        main()
        captured = capsys.readouterr()
        assert captured.out.strip() == ""

    def test_missing_arg_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.argv", ["rerun_skipped"])
        with pytest.raises(SystemExit, match="1"):
            main()

    def test_multiple_skipped_flags(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        xml = tmp_path / "output.xml"
        xml.write_text(MULTI_SKIPPED_XML)
        monkeypatch.setattr("sys.argv", ["rerun_skipped", str(xml)])
        main()
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert lines == ["--test", "Suite.Skip A", "--test", "Suite.Skip B"]
