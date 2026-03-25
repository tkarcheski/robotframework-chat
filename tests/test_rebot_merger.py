"""Tests for the rebot merge orchestrator.

Covers output.xml file discovery, merge configuration, provenance
tracking, _run_rebot subprocess wrapper, and CLI entry point.
"""

import os
import subprocess
from pathlib import Path

import pytest

from src.rfc.rebot_merger import (
    MergeConfig,
    MergeResult,
    _run_rebot,
    find_output_files,
    main,
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
        files = find_output_files([str(d), str(d)])
        assert len(files) == 1

    def test_excludes_output_dir(self, tmp_path: Path) -> None:
        """find_output_files must skip the output_dir to avoid self-inclusion.

        When `make rebot-merge-all` runs `rfc.rebot_merger results/`, the
        output goes to `results/combined/output.xml`.  On the next run,
        that stale aggregate must not be picked up as a source — otherwise
        it gets merged back in, duplicating every test case.
        """
        results = tmp_path / "results"
        math = results / "math"
        combined = results / "combined"
        math.mkdir(parents=True)
        combined.mkdir(parents=True)
        (math / "output.xml").write_text(MINIMAL_OUTPUT_XML)
        (combined / "output.xml").write_text(MINIMAL_OUTPUT_XML)

        files = find_output_files([str(results)], exclude_dir=str(combined))
        assert len(files) == 1
        assert "math" in files[0]
        assert "combined" not in files[0]

    def test_exclude_does_not_match_sibling_prefix(self, tmp_path: Path) -> None:
        """Excluding /results/combined must NOT skip /results/combined-old."""
        results = tmp_path / "results"
        combined = results / "combined"
        combined_old = results / "combined-old"
        combined.mkdir(parents=True)
        combined_old.mkdir(parents=True)
        (combined / "output.xml").write_text(MINIMAL_OUTPUT_XML)
        (combined_old / "output.xml").write_text(MINIMAL_OUTPUT_XML)

        files = find_output_files([str(results)], exclude_dir=str(combined))
        assert len(files) == 1
        assert "combined-old" in files[0]


# ── _run_rebot ───────────────────────────────────────────────────────


class TestRunRebot:
    def test_returns_exit_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, 0, stdout="OK", stderr="")

        monkeypatch.setattr("src.rfc.rebot_merger.subprocess.run", fake_run)
        rc = _run_rebot(["--help"])
        assert rc == 0

    def test_captures_stderr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="warning")

        monkeypatch.setattr("src.rfc.rebot_merger.subprocess.run", fake_run)
        rc = _run_rebot(["--bad-flag"])
        assert rc == 1


# ── merge_outputs ────────────────────────────────────────────────────


class TestMergeOutputs:
    def _setup_results(self, tmp_path: Path) -> tuple[Path, Path]:
        d1 = tmp_path / "results" / "math"
        d2 = tmp_path / "results" / "docker"
        d1.mkdir(parents=True)
        d2.mkdir(parents=True)
        (d1 / "output.xml").write_text(MINIMAL_OUTPUT_XML)
        (d2 / "output.xml").write_text(MINIMAL_OUTPUT_XML)
        return d1, d2

    def test_merge_creates_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._setup_results(tmp_path)
        output_dir = tmp_path / "combined"

        monkeypatch.setattr("src.rfc.rebot_merger._run_rebot", lambda args: 0)

        cfg = MergeConfig(
            source_dirs=[str(tmp_path / "results")],
            output_dir=str(output_dir),
        )
        result = merge_outputs(cfg)
        assert isinstance(result, MergeResult)
        assert result.source_count == 2

    def test_merge_with_no_files_returns_none(self, tmp_path: Path) -> None:
        cfg = MergeConfig(
            source_dirs=[str(tmp_path)],
            output_dir=str(tmp_path / "combined"),
        )
        result = merge_outputs(cfg)
        assert result is None

    def test_merge_passes_correct_args(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._setup_results(tmp_path)
        output_dir = tmp_path / "combined"

        captured_args: list[list[str]] = []

        def capture_rebot(args: list[str]) -> int:
            captured_args.append(args)
            return 0

        monkeypatch.setattr("src.rfc.rebot_merger._run_rebot", capture_rebot)

        cfg = MergeConfig(
            source_dirs=[str(tmp_path / "results")],
            output_dir=str(output_dir),
            name="Test Merge",
        )
        merge_outputs(cfg)
        assert len(captured_args) == 1
        assert "--name" in captured_args[0]
        assert "Test Merge" in captured_args[0]


# ── CLI main() ───────────────────────────────────────────────────────


class TestRebotMergerMain:
    def test_main_success(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        d = tmp_path / "results"
        d.mkdir()
        (d / "output.xml").write_text(MINIMAL_OUTPUT_XML)
        output_dir = tmp_path / "combined"

        monkeypatch.setattr("src.rfc.rebot_merger._run_rebot", lambda args: 0)
        monkeypatch.setattr(
            "sys.argv",
            ["rebot_merger", str(d), "--output-dir", str(output_dir)],
        )

        main()
        captured = capsys.readouterr()
        assert "Merge Complete" in captured.out
        assert "Sources merged: 1" in captured.out

    def test_main_no_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        monkeypatch.setattr("sys.argv", ["rebot_merger", str(empty_dir)])

        with pytest.raises(SystemExit):
            main()
        captured = capsys.readouterr()
        assert "No output.xml" in captured.out

    def test_main_custom_name(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        d = tmp_path / "results"
        d.mkdir()
        (d / "output.xml").write_text(MINIMAL_OUTPUT_XML)

        monkeypatch.setattr("src.rfc.rebot_merger._run_rebot", lambda args: 0)
        monkeypatch.setattr(
            "sys.argv",
            ["rebot_merger", str(d), "--name", "Sprint 42"],
        )

        main()
        captured = capsys.readouterr()
        assert "Sprint 42" in captured.out
