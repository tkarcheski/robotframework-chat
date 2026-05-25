"""Tests for the run-local-models coverage audit (scripts/audit_robot_reports.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.audit_robot_reports import (
    COVERED,
    ERRORED,
    MISSING,
    PARTIAL,
    build_report,
    cell_status,
    latest_version,
    load_master_models,
    load_suites,
    parse_output_xml,
    render_markdown,
    select_latest,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _write_output_xml(
    root: Path,
    *,
    version: str,
    model: str,
    suite: str,
    host: str,
    session: str,
    passed: int,
    failed: int,
    skipped: int = 0,
    end_time: str = "2026-05-20T00:00:00Z",
    watermark: bool = True,
) -> Path:
    """Write a minimal Robot output.xml mirroring the run-local-models watermark."""
    if watermark:
        metas = "\n".join(
            [
                f'<meta name="rfc_version">{version}</meta>',
                f'<meta name="model_name">{model}</meta>',
                f'<meta name="test_suite">{suite}</meta>',
                f'<meta name="hostname">{host}</meta>',
                f'<meta name="session_id">{session}</meta>',
                f'<meta name="Test_End_Time">{end_time}</meta>',
            ]
        )
    else:
        # A dryrun-style file carries documentation metadata but no run watermark.
        metas = '<meta name="Author">Some Suite</meta>'

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<robot generator="Robot 7.4.1" generated="{end_time}" rpa="false" schemaversion="5">
<suite id="s1" name="{suite}">
{metas}
</suite>
<statistics>
<total>
<stat pass="{passed}" fail="{failed}" skip="{skipped}">All Tests</stat>
</total>
</statistics>
</robot>
"""
    path = root / version / model / suite / host / session / "output.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(xml)
    return path


# ---------------------------------------------------------------------------
# parse_output_xml
# ---------------------------------------------------------------------------


def test_parse_extracts_watermark_and_stats(tmp_path: Path) -> None:
    path = _write_output_xml(
        tmp_path,
        version="1.10.7",
        model="llama3",
        suite="math",
        host="ai1",
        session="abc123",
        passed=3,
        failed=1,
    )
    run = parse_output_xml(path)
    assert run is not None
    assert run.rfc_version == "1.10.7"
    assert run.model == "llama3"
    assert run.suite == "math"
    assert run.hostname == "ai1"
    assert run.session_id == "abc123"
    assert run.total == 4
    assert run.passed == 3
    assert run.failed == 1
    assert run.pass_rate == 0.75


def test_parse_returns_none_without_watermark(tmp_path: Path) -> None:
    # dryrun-style output.xml has no rfc_version/test_suite/model — must be skipped.
    path = _write_output_xml(
        tmp_path,
        version="1.10.7",
        model="x",
        suite="dryrun",
        host="h",
        session="s",
        passed=1,
        failed=0,
        watermark=False,
    )
    assert parse_output_xml(path) is None


def test_parse_returns_none_for_lfs_pointer(tmp_path: Path) -> None:
    pointer = tmp_path / "output.xml"
    pointer.write_text(
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:deadbeef\nsize 1234\n"
    )
    assert parse_output_xml(pointer) is None


# ---------------------------------------------------------------------------
# cell_status thresholds
# ---------------------------------------------------------------------------


def _stub(passed: int, failed: int, skipped: int = 0):
    from scripts.audit_robot_reports import RunStats

    return RunStats(
        rfc_version="1.0.0",
        model="m",
        suite="s",
        hostname="h",
        session_id="x",
        total=passed + failed + skipped,
        passed=passed,
        failed=failed,
        skipped=skipped,
        end_time="2026-01-01T00:00:00Z",
        path=Path("x"),
    )


def test_cell_status_thresholds() -> None:
    assert cell_status(None) == MISSING
    assert cell_status(_stub(0, 0)) == ERRORED  # 0 tests
    assert cell_status(_stub(1, 1)) == COVERED  # exactly 50%
    assert cell_status(_stub(3, 1)) == COVERED  # 75%
    assert cell_status(_stub(1, 3)) == PARTIAL  # 25%


# ---------------------------------------------------------------------------
# select_latest — most recent across hosts wins
# ---------------------------------------------------------------------------


def test_select_latest_picks_most_recent_across_hosts(tmp_path: Path) -> None:
    _write_output_xml(
        tmp_path, version="1.10.7", model="llama3", suite="math",
        host="ai1", session="old", passed=1, failed=1,
        end_time="2026-05-19T00:00:00Z",
    )
    _write_output_xml(
        tmp_path, version="1.10.7", model="llama3", suite="math",
        host="ai2", session="new", passed=4, failed=0,
        end_time="2026-05-20T00:00:00Z",
    )
    from scripts.audit_robot_reports import find_runs

    runs = find_runs(tmp_path)
    latest = select_latest(runs, "1.10.7")
    chosen = latest[("llama3", "math")]
    assert chosen.session_id == "new"
    assert chosen.pass_rate == 1.0


# ---------------------------------------------------------------------------
# latest_version
# ---------------------------------------------------------------------------


def test_latest_version_ignores_non_pep440(tmp_path: Path) -> None:
    from scripts.audit_robot_reports import find_runs

    _write_output_xml(
        tmp_path, version="1.10.6", model="m", suite="math",
        host="h", session="a", passed=1, failed=0,
    )
    _write_output_xml(
        tmp_path, version="1.10.10", model="m", suite="math",
        host="h", session="b", passed=1, failed=0,
    )
    _write_output_xml(
        tmp_path, version="legacy", model="m", suite="math",
        host="h", session="c", passed=1, failed=0,
    )
    runs = find_runs(tmp_path)
    # 1.10.10 > 1.10.6 numerically (not lexically); "legacy" ignored.
    assert latest_version(runs) == "1.10.10"


# ---------------------------------------------------------------------------
# config loaders (against the real repo config)
# ---------------------------------------------------------------------------


def test_load_suites_includes_known_suites() -> None:
    suites = load_suites()
    assert "math" in suites
    assert "safety" in suites
    assert len(suites) >= 30


def test_load_master_models_includes_known_model() -> None:
    models = load_master_models()
    assert "llama3" in models


# ---------------------------------------------------------------------------
# build_report + render_markdown
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_report(tmp_path: Path):
    from scripts.audit_robot_reports import find_runs

    # llama3 runs both suites; mistral only one.
    _write_output_xml(
        tmp_path, version="1.10.7", model="llama3", suite="math",
        host="ai1", session="a", passed=4, failed=0,
    )
    _write_output_xml(
        tmp_path, version="1.10.7", model="llama3", suite="safety",
        host="ai1", session="b", passed=1, failed=3,
    )
    _write_output_xml(
        tmp_path, version="1.10.7", model="mistral", suite="math",
        host="ai1", session="c", passed=0, failed=0,
    )
    # An older version's run must not leak into the latest-version report.
    _write_output_xml(
        tmp_path, version="1.9.0", model="oldmodel", suite="math",
        host="ai1", session="d", passed=1, failed=0,
    )
    runs = find_runs(tmp_path)
    return build_report(
        runs,
        version="1.10.7",
        suites=["math", "safety"],
        master_models=["llama3", "mistral", "qwen3"],
    )


def test_build_report_cells_and_models(sample_report) -> None:
    r = sample_report
    assert r.version == "1.10.7"
    assert r.models == ["llama3", "mistral"]  # observed, sorted; oldmodel excluded
    assert r.status("llama3", "math") == COVERED
    assert r.status("llama3", "safety") == PARTIAL  # 25%
    assert r.status("mistral", "math") == ERRORED  # 0 tests
    assert r.status("mistral", "safety") == MISSING  # never ran


def test_model_completion_counts(sample_report) -> None:
    r = sample_report
    assert r.model_suite_count("llama3") == 2  # ran both suites
    assert r.model_suite_count("mistral") == 1  # ran only math
    assert r.fully_covered_models() == ["llama3"]


def test_missing_fleet_models(sample_report) -> None:
    # qwen3 is in master_models but produced no data this version.
    assert "qwen3" in sample_report.missing_fleet_models()
    assert "llama3" not in sample_report.missing_fleet_models()


def test_render_markdown_structure(sample_report) -> None:
    md = render_markdown(sample_report)
    assert "# Robot coverage audit" in md
    assert "1.10.7" in md
    # legend
    assert COVERED in md and MISSING in md
    # matrix has suite rows and model columns
    assert "| math |" in md
    assert "llama3" in md and "mistral" in md
    # completion checklist uses task-list checkboxes
    assert "- [x] llama3" in md
    assert "- [ ] mistral" in md
    # gaps surface the never-run fleet model
    assert "qwen3" in md
