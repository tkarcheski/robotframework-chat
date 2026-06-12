from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "metrics" / "entrypoint.sh"


def run_bash(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", "-lc", script], capture_output=True, text=True)


def test_relative_path_handles_results_root() -> None:
    proc = run_bash(
        f"export RESULTS_DIR=/tmp/results OUTPUT_DIR=/tmp/out; source '{SCRIPT}'; relative_path /tmp/results /tmp/results"
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "."


def _fake_robotmetrics(bin_dir: Path) -> None:
    """Drop a stub `robotmetrics` that mimics robotframework-metrics 3.3.3.

    Two verified facts about the real CLI are encoded here:
      * it has no `--metrics-report-path` flag (argparse exits non-zero), and
      * it writes its report to the path given by `--metrics-report-name`.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    fake = bin_dir / "robotmetrics"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "args = sys.argv[1:]\n"
        "if '--metrics-report-path' in args:\n"
        "    sys.stderr.write('robotmetrics: error: unrecognized arguments: "
        "--metrics-report-path\\n')\n"
        "    sys.exit(2)\n"
        "name = None\n"
        "for i, a in enumerate(args):\n"
        "    if a in ('-M', '--metrics-report-name'):\n"
        "        name = args[i + 1]\n"
        "if not name:\n"
        "    sys.exit(3)\n"
        "open(name, 'w').write('<html>dashboard</html>')\n"
    )
    fake.chmod(0o755)


def test_generate_metrics_uses_supported_flags_and_writes_dashboard(
    tmp_path: Path,
) -> None:
    results_dir = tmp_path / "results"
    suite = results_dir / "local" / "host" / "model"
    suite.mkdir(parents=True)
    xml = suite / "output.xml"
    xml.write_text("<robot><suite></suite></robot>")
    old_time = time.time() - 3600
    os.utime(xml, (old_time, old_time))
    output_dir = tmp_path / "metrics"
    output_dir.mkdir()
    bin_dir = tmp_path / "bin"
    _fake_robotmetrics(bin_dir)

    proc = run_bash(
        f"export PATH='{bin_dir}':\"$PATH\" "
        f"RESULTS_DIR='{results_dir}' OUTPUT_DIR='{output_dir}' "
        "METRICS_FRESH_WINDOW_SECONDS=120; "
        f"source '{SCRIPT}'; generate_metrics"
    )

    assert proc.returncode == 0, proc.stderr
    dashboard = output_dir / "local" / "host" / "model" / "dashboard.html"
    assert dashboard.is_file(), (
        f"dashboard not generated; stdout={proc.stdout} stderr={proc.stderr}"
    )
    assert "Generated metrics for 1 suite" in proc.stdout


def test_generate_metrics_skips_recently_modified_xml(tmp_path: Path) -> None:
    """output.xml modified within the fresh window is skipped with INFO, not processed."""
    results_dir = tmp_path / "results"
    suite = results_dir / "local" / "host" / "model"
    suite.mkdir(parents=True)
    xml = suite / "output.xml"
    xml.write_text("<robot><suite></suite></robot>")
    # mtime is "now" by default — keep it fresh
    output_dir = tmp_path / "metrics"
    output_dir.mkdir()
    bin_dir = tmp_path / "bin"
    _fake_robotmetrics(bin_dir)

    proc = run_bash(
        f"export PATH='{bin_dir}':\"$PATH\" "
        f"RESULTS_DIR='{results_dir}' OUTPUT_DIR='{output_dir}' "
        "METRICS_FRESH_WINDOW_SECONDS=3600; "
        f"source '{SCRIPT}'; generate_metrics"
    )

    assert proc.returncode == 0, proc.stderr
    dashboard = output_dir / "local" / "host" / "model" / "dashboard.html"
    assert not dashboard.exists(), (
        f"dashboard must not be generated for an in-progress run; stdout={proc.stdout}"
    )
    assert "in progress" in proc.stdout.lower(), (
        f"expected in-progress INFO message; stdout={proc.stdout}"
    )


def test_generate_metrics_skips_stale_truncated_xml(tmp_path: Path) -> None:
    """output.xml that is old but lacks </robot> produces a WARNING and is skipped."""
    results_dir = tmp_path / "results"
    suite = results_dir / "local" / "host" / "model"
    suite.mkdir(parents=True)
    xml = suite / "output.xml"
    xml.write_text("<robot><suite><test>no closing tag")
    old_time = time.time() - 3600
    os.utime(xml, (old_time, old_time))
    output_dir = tmp_path / "metrics"
    output_dir.mkdir()
    bin_dir = tmp_path / "bin"
    _fake_robotmetrics(bin_dir)

    proc = run_bash(
        f"export PATH='{bin_dir}':\"$PATH\" "
        f"RESULTS_DIR='{results_dir}' OUTPUT_DIR='{output_dir}' "
        "METRICS_FRESH_WINDOW_SECONDS=120; "
        f"source '{SCRIPT}'; generate_metrics"
    )

    assert proc.returncode == 0, proc.stderr
    dashboard = output_dir / "local" / "host" / "model" / "dashboard.html"
    assert not dashboard.exists(), (
        f"dashboard must not be generated for truncated XML; stdout={proc.stdout}"
    )
    assert "truncated" in proc.stdout.lower(), (
        f"expected truncation WARNING message; stdout={proc.stdout}"
    )


def test_generate_index_lists_root_and_nested_dashboards(tmp_path: Path) -> None:
    output_dir = tmp_path / "metrics"
    output_dir.mkdir()
    (output_dir / "root-dashboard.html").write_text("<html>root</html>")
    (output_dir / "accounting").mkdir()
    (output_dir / "accounting" / "dashboard.html").write_text("<html>nested</html>")

    proc = run_bash(
        f"export OUTPUT_DIR='{output_dir}' RESULTS_DIR=/tmp/results; source '{SCRIPT}'; generate_index; cat '{output_dir / 'index.html'}'"
    )

    assert proc.returncode == 0, proc.stderr
    html = proc.stdout
    assert 'href="root-dashboard.html"' in html
    assert ">root<" in html
    assert 'href="accounting/dashboard.html"' in html
    assert ">accounting<" in html


class TestSkipLogicWithXmlFixtures:
    """Fixture-based regression tests for each production skip shape in entrypoint.sh.

    Canonical fixture files in tests/fixtures/output_xml/ capture the exact byte
    sequences seen in the #413 incident so future format changes can't silently
    break the skip path.  The zero-byte case closes a gap not covered by the
    inline-content tests above.
    """

    FIXTURES = Path(__file__).resolve().parent / "fixtures" / "output_xml"

    def _run_with_fixture_xml(
        self,
        tmp_path: Path,
        fixture_name: str,
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        bin_dir = tmp_path / "bin"
        _fake_robotmetrics(bin_dir)
        results_dir = tmp_path / "results"
        suite = results_dir / "local" / "host" / "model"
        suite.mkdir(parents=True)
        xml = suite / "output.xml"
        xml.write_bytes((self.FIXTURES / fixture_name).read_bytes())
        old_time = time.time() - 3600
        os.utime(xml, (old_time, old_time))
        output_dir = tmp_path / "metrics"
        output_dir.mkdir()
        proc = run_bash(
            f"export PATH='{bin_dir}':\"$PATH\" "
            f"RESULTS_DIR='{results_dir}' OUTPUT_DIR='{output_dir}' "
            "METRICS_FRESH_WINDOW_SECONDS=120; "
            f"source '{SCRIPT}'; generate_metrics"
        )
        dashboard = output_dir / "local" / "host" / "model" / "dashboard.html"
        return proc, dashboard

    def test_truncated_mid_element_is_skipped(self, tmp_path: Path) -> None:
        proc, dashboard = self._run_with_fixture_xml(tmp_path, "truncated_mid_element.xml")
        assert proc.returncode == 0, proc.stderr
        assert "truncated" in proc.stdout.lower()
        assert not dashboard.exists()

    def test_in_progress_stale_file_is_skipped(self, tmp_path: Path) -> None:
        """A stale (old mtime) file with no </robot> is skipped via the content check."""
        proc, dashboard = self._run_with_fixture_xml(tmp_path, "in_progress.xml")
        assert proc.returncode == 0, proc.stderr
        assert "truncated" in proc.stdout.lower()
        assert not dashboard.exists()

    def test_zero_byte_xml_is_skipped(self, tmp_path: Path) -> None:
        proc, dashboard = self._run_with_fixture_xml(tmp_path, "zero_byte.xml")
        assert proc.returncode == 0, proc.stderr
        assert "truncated" in proc.stdout.lower()
        assert not dashboard.exists()
