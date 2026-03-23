"""Tests for scripts/robot_review.py — Robot Framework tag compliance checker."""

from __future__ import annotations

from pathlib import Path

import pytest

# The script uses sys.path manipulation; replicate it for test imports.
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from robot.errors import DataError  # noqa: E402
from robot_review import (  # noqa: E402
    ReviewResult,
    Violation,
    check_test,
    main,
    print_report,
    review_output_xml,
)


# ── check_test() unit tests ─────────────────────────────────────────


class TestCheckTestCompliant:
    """Tests where tags are fully compliant — no violation returned."""

    def test_tier0_verify_robot(self) -> None:
        result = check_test("My Test", "Suite", ["tier:0", "verify:robot"])
        assert result is None

    def test_extra_tags_ignored(self) -> None:
        result = check_test(
            "My Test", "Suite", ["tier:2", "verify:llm", "IQ:100", "math"]
        )
        assert result is None

    @pytest.mark.parametrize("tier", [0, 1, 2, 3, 4, 5, 6])
    def test_all_valid_tiers(self, tier: int) -> None:
        result = check_test("T", "S", [f"tier:{tier}", "verify:robot"])
        assert result is None

    @pytest.mark.parametrize("verify", ["robot", "python", "llm", "llms"])
    def test_all_valid_verify(self, verify: str) -> None:
        result = check_test("T", "S", ["tier:0", f"verify:{verify}"])
        assert result is None

    def test_mixed_case_tags(self) -> None:
        """Robot Framework tags are case-insensitive; mixed case must pass."""
        result = check_test("T", "S", ["TIER:2", "VERIFY:LLM"])
        assert result is None

    def test_title_case_tags(self) -> None:
        result = check_test("T", "S", ["Tier:0", "Verify:Robot"])
        assert result is None

    def test_mixed_case_verify_value(self) -> None:
        result = check_test("T", "S", ["tier:1", "Verify:Python"])
        assert result is None


class TestCheckTestViolations:
    """Tests where tags are non-compliant — Violation returned."""

    def test_missing_tier(self) -> None:
        v = check_test("T", "S", ["verify:robot"])
        assert v is not None
        assert any("tier" in issue.lower() for issue in v.issues)

    def test_missing_verify(self) -> None:
        v = check_test("T", "S", ["tier:1"])
        assert v is not None
        assert any("verify" in issue.lower() for issue in v.issues)

    def test_missing_both(self) -> None:
        v = check_test("T", "S", [])
        assert v is not None
        assert len(v.issues) == 2

    def test_invalid_tier_value(self) -> None:
        v = check_test("T", "S", ["tier:9", "verify:robot"])
        assert v is not None
        assert any("9" in issue for issue in v.issues)

    def test_invalid_verify_value(self) -> None:
        v = check_test("T", "S", ["tier:0", "verify:magic"])
        assert v is not None
        assert any("magic" in issue for issue in v.issues)

    def test_duplicate_tier(self) -> None:
        v = check_test("T", "S", ["tier:0", "tier:1", "verify:robot"])
        assert v is not None
        assert any(
            "duplicate" in issue.lower() or "multiple" in issue.lower()
            for issue in v.issues
        )

    def test_duplicate_verify(self) -> None:
        v = check_test("T", "S", ["tier:0", "verify:robot", "verify:llm"])
        assert v is not None
        assert any(
            "duplicate" in issue.lower() or "multiple" in issue.lower()
            for issue in v.issues
        )

    def test_non_numeric_tier(self) -> None:
        v = check_test("T", "S", ["tier:abc", "verify:robot"])
        assert v is not None
        assert any("tier" in issue.lower() for issue in v.issues)

    def test_violation_has_test_name(self) -> None:
        v = check_test("My Test Name", "My Suite", ["tier:0"])
        assert v is not None
        assert v.test_name == "My Test Name"
        assert v.suite_name == "My Suite"


# ── review_output_xml() integration tests ────────────────────────────

# Minimal output.xml that robot.api.ExecutionResult can parse.
_COMPLIANT_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<robot generator="Robot 7.4.1" generated="2026-03-20T10:00:00.000000">
  <suite id="s1" name="Test Suite" source="/tmp/test.robot">
    <test id="s1-t1" name="Compliant Test" line="5">
      <tag>tier:0</tag>
      <tag>verify:robot</tag>
      <status status="PASS" start="2026-03-20T10:00:00.000000" elapsed="0.001"/>
    </test>
    <status status="PASS" start="2026-03-20T10:00:00.000000" elapsed="0.002"/>
  </suite>
  <statistics>
    <total><stat pass="1" fail="0" skip="0">All Tests</stat></total>
  </statistics>
</robot>
"""

_MIXED_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<robot generator="Robot 7.4.1" generated="2026-03-20T10:00:00.000000">
  <suite id="s1" name="Test Suite" source="/tmp/test.robot">
    <test id="s1-t1" name="Good Test" line="5">
      <tag>tier:0</tag>
      <tag>verify:robot</tag>
      <status status="PASS" start="2026-03-20T10:00:00.000000" elapsed="0.001"/>
    </test>
    <test id="s1-t2" name="Missing Tags" line="10">
      <tag>IQ:100</tag>
      <status status="PASS" start="2026-03-20T10:00:01.000000" elapsed="0.001"/>
    </test>
    <test id="s1-t3" name="Bad Tier" line="15">
      <tag>tier:9</tag>
      <tag>verify:robot</tag>
      <status status="PASS" start="2026-03-20T10:00:02.000000" elapsed="0.001"/>
    </test>
    <status status="PASS" start="2026-03-20T10:00:00.000000" elapsed="0.003"/>
  </suite>
  <statistics>
    <total><stat pass="3" fail="0" skip="0">All Tests</stat></total>
  </statistics>
</robot>
"""


class TestReviewOutputXml:
    """Integration tests that parse real output.xml content."""

    def test_compliant_file(self, tmp_path: Path) -> None:
        xml_file = tmp_path / "output.xml"
        xml_file.write_text(_COMPLIANT_XML)
        result = review_output_xml(str(xml_file))
        assert result.total_tests == 1
        assert result.compliant == 1
        assert len(result.violations) == 0

    def test_mixed_file(self, tmp_path: Path) -> None:
        xml_file = tmp_path / "output.xml"
        xml_file.write_text(_MIXED_XML)
        result = review_output_xml(str(xml_file))
        assert result.total_tests == 3
        assert result.compliant == 1
        assert len(result.violations) == 2

    def test_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            review_output_xml("/nonexistent/output.xml")

    def test_malformed_xml(self, tmp_path: Path) -> None:
        """Malformed XML should raise DataError, caught as exit code 2."""
        bad_file = tmp_path / "output.xml"
        bad_file.write_text("<<<not valid xml>>>")
        with pytest.raises(DataError):
            review_output_xml(str(bad_file))

    def test_directory_instead_of_file(self, tmp_path: Path) -> None:
        """Passing a directory should raise DataError, not a traceback."""
        with pytest.raises(DataError):
            review_output_xml(str(tmp_path))

    def test_file_path_stored(self, tmp_path: Path) -> None:
        xml_file = tmp_path / "output.xml"
        xml_file.write_text(_COMPLIANT_XML)
        result = review_output_xml(str(xml_file))
        assert result.file_path == str(xml_file)


# ── print_report() output tests ─────────────────────────────────────


class TestPrintReport:
    """Test that print_report produces expected output."""

    def test_compliant_report(self, capsys: pytest.CaptureFixture[str]) -> None:
        results = [
            ReviewResult(
                total_tests=5,
                compliant=5,
                violations=[],
                file_path="results/output.xml",
            )
        ]
        print_report(results)
        captured = capsys.readouterr().out
        assert "5" in captured
        assert "100" in captured  # 100%
        assert (
            "PASS" in captured
            or "pass" in captured.lower()
            or "compliant" in captured.lower()
        )

    def test_violation_report(self, capsys: pytest.CaptureFixture[str]) -> None:
        results = [
            ReviewResult(
                total_tests=3,
                compliant=1,
                violations=[
                    Violation(
                        test_name="Bad Test",
                        suite_name="Suite",
                        issues=["missing tier:* tag"],
                    ),
                    Violation(
                        test_name="Worse Test",
                        suite_name="Suite",
                        issues=["missing tier:* tag", "missing verify:* tag"],
                    ),
                ],
                file_path="results/output.xml",
            )
        ]
        print_report(results)
        captured = capsys.readouterr().out
        assert "Bad Test" in captured
        assert "Worse Test" in captured


# ── main() exit code tests ────────────────────────────────────────────


class TestMainExitCode:
    """Verify main() returns correct exit codes for error cases."""

    def test_malformed_xml_returns_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Malformed XML should exit 2 (file error), not crash with a traceback."""
        bad_file = tmp_path / "output.xml"
        bad_file.write_text("<<<not valid xml>>>")
        monkeypatch.setattr("sys.argv", ["robot_review", str(bad_file)])
        assert main() == 2

    def test_directory_returns_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Passing a directory should exit 2 (file error), not crash."""
        monkeypatch.setattr("sys.argv", ["robot_review", str(tmp_path)])
        assert main() == 2
