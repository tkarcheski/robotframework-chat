"""Tests for the rebot merge orchestrator.

Covers output.xml file discovery, merge configuration, provenance
tracking, and database recording of merge operations.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.rfc.rebot_merger import (
    MergeConfig,
    MergeResult,
    find_output_files,
    merge_outputs,
)


MINIMAL_OUTPUT_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<robot generator="Robot 7.0" generated="2025-06-15T10:00:00.000000">
  <suite name="Math Tests" id="s1">
    <test name="Addition" id="s1-t1">
      <status status="PASS" start="2025-06-15T10:00:01.000000" end="2025-06-15T10:00:02.000000"/>
    </test>
    <status status="PASS" start="2025-06-15T10:00:00.000000" end="2025-06-15T10:00:05.000000"/>
  </suite>
  <statistics>
    <total><stat pass="1" fail="0" skip="0">All Tests</stat></total>
  </statistics>
</robot>
"""


class TestMergeConfig:
    def test_defaults(self) -> None:
        cfg = MergeConfig(source_dirs=["results/"])
        assert cfg.output_dir == "results/combined"
        assert cfg.name == "Combined Results"

    def test_custom_name(self) -> None:
        cfg = MergeConfig(source_dirs=["a/"], name="My Report")
        assert cfg.name == "My Report"


class TestFindOutputFiles:
    def test_finds_files_recursively(self, tmp_path: Path) -> None:
        d1 = tmp_path / "math"
        d1.mkdir()
        (d1 / "output.xml").write_text(MINIMAL_OUTPUT_XML)
        d2 = tmp_path / "docker"
        d2.mkdir()
        (d2 / "output.xml").write_text(MINIMAL_OUTPUT_XML)
        # Non-xml file should be ignored
        (tmp_path / "other.txt").write_text("ignore")

        files = find_output_files([str(tmp_path)])
        assert len(files) == 2
        filenames = [os.path.basename(f) for f in files]
        assert all(f == "output.xml" for f in filenames)

    def test_multiple_source_dirs(self, tmp_path: Path) -> None:
        d1 = tmp_path / "a"
        d2 = tmp_path / "b"
        d1.mkdir()
        d2.mkdir()
        (d1 / "output.xml").write_text(MINIMAL_OUTPUT_XML)
        (d2 / "output.xml").write_text(MINIMAL_OUTPUT_XML)

        files = find_output_files([str(d1), str(d2)])
        assert len(files) == 2

    def test_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        files = find_output_files([str(tmp_path)])
        assert files == []

    def test_nonexistent_dir_skipped(self) -> None:
        files = find_output_files(["/nonexistent/path"])
        assert files == []

    def test_deduplicates_files(self, tmp_path: Path) -> None:
        d = tmp_path / "results"
        d.mkdir()
        (d / "output.xml").write_text(MINIMAL_OUTPUT_XML)
        # Pass the same dir twice
        files = find_output_files([str(d), str(d)])
        assert len(files) == 1


class TestMergeOutputs:
    def _setup_results(self, tmp_path: Path) -> tuple[Path, Path]:
        """Create two result directories with output.xml files."""
        d1 = tmp_path / "results" / "math"
        d2 = tmp_path / "results" / "docker"
        d1.mkdir(parents=True)
        d2.mkdir(parents=True)
        (d1 / "output.xml").write_text(MINIMAL_OUTPUT_XML)
        (d2 / "output.xml").write_text(MINIMAL_OUTPUT_XML)
        return d1, d2

    @patch("src.rfc.rebot_merger._run_rebot")
    def test_merge_creates_result(self, mock_rebot: MagicMock, tmp_path: Path) -> None:
        d1, d2 = self._setup_results(tmp_path)
        output_dir = tmp_path / "combined"
        output_dir.mkdir()
        # Mock rebot to create output files
        mock_rebot.return_value = 0

        cfg = MergeConfig(
            source_dirs=[str(tmp_path / "results")],
            output_dir=str(output_dir),
        )
        result = merge_outputs(cfg)
        assert isinstance(result, MergeResult)
        assert result.source_count == 2
        mock_rebot.assert_called_once()

    @patch("src.rfc.rebot_merger._run_rebot")
    def test_merge_with_no_files_returns_none(
        self, mock_rebot: MagicMock, tmp_path: Path
    ) -> None:
        cfg = MergeConfig(
            source_dirs=[str(tmp_path)],
            output_dir=str(tmp_path / "combined"),
        )
        result = merge_outputs(cfg)
        assert result is None
        mock_rebot.assert_not_called()

    @patch("src.rfc.rebot_merger._run_rebot")
    def test_merge_passes_correct_args(
        self, mock_rebot: MagicMock, tmp_path: Path
    ) -> None:
        d1, d2 = self._setup_results(tmp_path)
        output_dir = tmp_path / "combined"
        output_dir.mkdir()
        mock_rebot.return_value = 0

        cfg = MergeConfig(
            source_dirs=[str(tmp_path / "results")],
            output_dir=str(output_dir),
            name="Test Merge",
        )
        merge_outputs(cfg)

        call_args = mock_rebot.call_args
        assert call_args is not None
        args = call_args[0]
        # Should pass source files, output dir, and name
        assert "--name" in args[0] or "Test Merge" in str(args)
