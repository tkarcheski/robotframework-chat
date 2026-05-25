#!/usr/bin/env python3
"""Audit run-local-models coverage and render a markdown report.

``make run-local-models`` exercises every test suite in
``config/local_models.yaml`` against every model discovered on the local
Ollama fleet, writing one ``output.xml`` per (model, suite, host, session)
under the ``results/`` submodule. This script answers the question that
matters once those runs pile up: *which models have actually been measured
against which suites, for the current rfc version?*

It scans the results tree, keys each run by the 5-tuple watermark stamped
into ``output.xml`` (see ``CLAUDE.md`` § Real results), and builds a
model x test-suite coverage matrix for the latest version. The matrix is
rendered as a markdown report under ``.claude/audits/`` so coverage is
reviewable in a PR rather than buried in HTML logs.

Usage::

    # Audit the existing results tree, write the report, print a summary.
    uv run python scripts/audit_robot_reports.py

    # Audit and commit the latest results + report (submodule-aware).
    uv run python scripts/audit_robot_reports.py --commit

    # Audit a specific version / results root.
    uv run python scripts/audit_robot_reports.py --version 1.10.7 \
        --results-root results
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml
from packaging.version import InvalidVersion, Version

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RESULTS_ROOT = _PROJECT_ROOT / "results"
LOCAL_MODELS_CONFIG = _PROJECT_ROOT / "config" / "local_models.yaml"
TEST_SUITES_CONFIG = _PROJECT_ROOT / "config" / "test_suites.yaml"
DEFAULT_AUDIT_DIR = _PROJECT_ROOT / ".claude" / "audits"

# Coverage cell statuses. Emoji keep the matrix scannable at a glance — a wall
# of ✅ with the occasional ⬜ tells the story faster than a table of numbers.
COVERED = "✅"  # ran, and at least half the tests passed
PARTIAL = "⚠️"  # ran, but fewer than half passed — the model struggles here
ERRORED = "🛑"  # ran but produced zero tests (setup/collection failure)
MISSING = "⬜"  # never ran — a genuine coverage gap
PASS_THRESHOLD = 0.5

# An LFS pointer file starts with this when the content hasn't been pulled.
_LFS_POINTER_PREFIX = "version https://git-lfs"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


@dataclass
class RunStats:
    """Outcome of one (model, suite, host, session) Robot run.

    Built from the watermark metadata and the ``All Tests`` statistic in a
    single ``output.xml``. ``end_time`` is kept as the raw ISO string so the
    most-recent run for a cell can be chosen with a plain string comparison
    (ISO-8601 sorts chronologically).
    """

    rfc_version: str
    model: str
    suite: str
    hostname: str
    session_id: str
    total: int
    passed: int
    failed: int
    skipped: int
    end_time: str
    path: Path

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


def _read_metas(root: ET.Element) -> dict[str, str]:
    """Collect every ``<meta name=...>`` value (last write wins per key).

    Robot stores the run watermark as suite metadata; the DbListener appends a
    second block carrying ``rfc_version`` / ``test_suite`` / ``model_name`` /
    ``hostname`` / ``session_id``. Iterating all ``<meta>`` elements picks those
    up regardless of which suite level they live on.
    """
    metas: dict[str, str] = {}
    for meta in root.iter("meta"):
        name = meta.get("name")
        if name is not None:
            metas[name] = (meta.text or "").strip()
    return metas


def _read_totals(root: ET.Element) -> tuple[int, int, int] | None:
    """Return (passed, failed, skipped) from the ``All Tests`` total stat."""
    for stat in root.iter("stat"):
        if (stat.text or "").strip() == "All Tests":
            return (
                int(stat.get("pass", 0)),
                int(stat.get("fail", 0)),
                int(stat.get("skip", 0)),
            )
    return None


def parse_output_xml(path: Path) -> RunStats | None:
    """Parse one ``output.xml`` into a :class:`RunStats`, or ``None`` to skip.

    Skips files that aren't run-local watermarked results: LFS pointers (content
    not pulled), dryrun outputs (no ``rfc_version`` / ``test_suite``), and
    anything that fails to parse. Skipping rather than raising keeps the audit
    resilient to a stray malformed file in a large tree.
    """
    try:
        head = path.read_text(errors="replace")[:64]
    except OSError:
        return None
    if head.startswith(_LFS_POINTER_PREFIX):
        return None

    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return None

    metas = _read_metas(root)
    version = metas.get("rfc_version")
    suite = metas.get("test_suite")
    model = metas.get("model_name") or metas.get("Default_Model")
    if not (version and suite and model):
        return None  # not a run-local watermarked result (e.g. dryrun)

    totals = _read_totals(root)
    if totals is not None:
        passed, failed, skipped = totals
    else:
        passed = int(metas.get("Passed_Tests", 0))
        failed = int(metas.get("Failed_Tests", 0))
        skipped = int(metas.get("Skipped_Tests", 0))

    end_time = (
        metas.get("Test_End_Time")
        or metas.get("Timestamp")
        or root.get("generated", "")
    )

    return RunStats(
        rfc_version=version,
        model=model,
        suite=suite,
        hostname=metas.get("hostname", "_unknown"),
        session_id=metas.get("session_id", "_unknown"),
        total=passed + failed + skipped,
        passed=passed,
        failed=failed,
        skipped=skipped,
        end_time=end_time,
        path=path,
    )


def find_runs(results_root: Path) -> list[RunStats]:
    """Parse every watermarked ``output.xml`` under ``results_root``."""
    runs: list[RunStats] = []
    for path in sorted(results_root.rglob("output.xml")):
        run = parse_output_xml(path)
        if run is not None:
            runs.append(run)
    return runs


def latest_version(runs: list[RunStats]) -> str | None:
    """Return the highest PEP 440 version seen, ignoring non-version dirs."""
    versions: set[str] = set()
    for run in runs:
        try:
            Version(run.rfc_version)
        except InvalidVersion:
            continue
        versions.add(run.rfc_version)
    if not versions:
        return None
    return max(versions, key=Version)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def load_suites(config_path: Path = LOCAL_MODELS_CONFIG) -> list[str]:
    """Suite names run-local-models executes, in config order."""
    data = yaml.safe_load(config_path.read_text())
    return [s["name"] for s in data.get("test_suites", [])]


def load_master_models(config_path: Path = TEST_SUITES_CONFIG) -> list[str]:
    """The known fleet models, so models with zero data show up as gaps."""
    data = yaml.safe_load(config_path.read_text())
    return list(data.get("master_models", []))


# ---------------------------------------------------------------------------
# Coverage matrix
# ---------------------------------------------------------------------------


def select_latest(
    runs: list[RunStats], version: str
) -> dict[tuple[str, str], RunStats]:
    """Pick the most-recent run per (model, suite) for ``version``.

    Hosts are collapsed: a cell reflects whichever host most recently ran that
    (model, suite) pair, because for *coverage* we only care that the pair has
    been measured, not where.
    """
    best: dict[tuple[str, str], RunStats] = {}
    for run in runs:
        if run.rfc_version != version:
            continue
        key = (run.model, run.suite)
        current = best.get(key)
        if current is None or run.end_time > current.end_time:
            best[key] = run
    return best


def cell_status(stats: RunStats | None) -> str:
    """Map a (model, suite) cell to its coverage emoji."""
    if stats is None:
        return MISSING
    if stats.total == 0:
        return ERRORED
    return COVERED if stats.pass_rate >= PASS_THRESHOLD else PARTIAL


@dataclass
class CoverageReport:
    """A model x suite coverage snapshot for one rfc version."""

    version: str
    suites: list[str]
    models: list[str]  # observed models, sorted
    cells: dict[tuple[str, str], RunStats]
    master_models: list[str]
    hosts: list[str] = field(default_factory=list)

    def status(self, model: str, suite: str) -> str:
        return cell_status(self.cells.get((model, suite)))

    def model_suite_count(self, model: str) -> int:
        """How many of the configured suites this model has ≥1 run for."""
        return sum(1 for suite in self.suites if (model, suite) in self.cells)

    def fully_covered_models(self) -> list[str]:
        """Observed models that have run every configured suite at least once."""
        return [
            m for m in self.models if self.model_suite_count(m) == len(self.suites)
        ]

    def missing_fleet_models(self) -> list[str]:
        """Fleet (master) models with no runs at all for this version."""
        observed = set(self.models)
        return [m for m in self.master_models if m not in observed]

    def uncovered_suites(self) -> list[str]:
        """Suites no observed model has run for this version."""
        run_suites = {suite for (_model, suite) in self.cells}
        return [s for s in self.suites if s not in run_suites]

    @property
    def covered_cells(self) -> int:
        return sum(
            1
            for m in self.models
            for s in self.suites
            if self.status(m, s) == COVERED
        )

    @property
    def total_cells(self) -> int:
        return len(self.models) * len(self.suites)


def build_report(
    runs: list[RunStats],
    version: str,
    suites: list[str],
    master_models: list[str],
) -> CoverageReport:
    """Assemble the coverage matrix for ``version`` from parsed runs."""
    cells = select_latest(runs, version)
    observed = sorted({model for (model, _suite) in cells})
    hosts = sorted(
        {run.hostname for run in runs if run.rfc_version == version}
    )
    return CoverageReport(
        version=version,
        suites=suites,
        models=observed,
        cells=cells,
        master_models=master_models,
        hosts=hosts,
    )


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def render_markdown(report: CoverageReport) -> str:
    """Render the coverage report as a markdown document.

    Layout: suites as rows, observed models as columns. Suites outnumber models
    on a typical fleet, so this keeps the table narrow enough to read without
    horizontal scrolling. A completion checklist and a gaps section follow.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    hosts = ", ".join(report.hosts) or "—"
    lines: list[str] = []

    lines.append(f"# Robot coverage audit — v{report.version}")
    lines.append("")
    lines.append(
        f"_Generated {today} • {len(report.models)} models × "
        f"{len(report.suites)} suites • "
        f"{report.covered_cells}/{report.total_cells} cells covered • "
        f"host(s): {hosts}_"
    )
    lines.append("")
    lines.append(
        f"**Legend** — {COVERED} ran, ≥50% pass · {PARTIAL} ran, <50% pass · "
        f"{ERRORED} ran, 0 tests · {MISSING} not run"
    )
    lines.append("")

    if not report.models:
        lines.append("> No watermarked run-local-models results for this version yet.")
        lines.append("")
    else:
        lines.append("## Coverage matrix")
        lines.append("")
        header = "| Suite | " + " | ".join(report.models) + " |"
        sep = "|---|" + "|".join([":---:"] * len(report.models)) + "|"
        lines.append(header)
        lines.append(sep)
        for suite in report.suites:
            row = [report.status(m, suite) for m in report.models]
            lines.append(f"| {suite} | " + " | ".join(row) + " |")
        lines.append("")

        lines.append("## Model completion (full suite set)")
        lines.append("")
        n_suites = len(report.suites)
        for model in report.models:
            count = report.model_suite_count(model)
            box = "x" if count == n_suites else " "
            lines.append(f"- [{box}] {model} — {count}/{n_suites} suites")
        lines.append("")

    lines.append("## Gaps")
    lines.append("")
    uncovered = report.uncovered_suites()
    missing_models = report.missing_fleet_models()
    if not uncovered and not missing_models:
        lines.append("None — every suite and every fleet model has data.")
    else:
        if uncovered:
            lines.append(
                f"**Suites no model has run ({len(uncovered)}):** "
                + ", ".join(uncovered)
            )
            lines.append("")
        if missing_models:
            lines.append(
                f"**Fleet models with no v{report.version} data "
                f"({len(missing_models)}):** " + ", ".join(missing_models)
            )
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Git (submodule-aware commit)
# ---------------------------------------------------------------------------


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True
    )


def _is_submodule(results_root: Path) -> bool:
    """True if ``results_root`` is its own git working tree (a submodule)."""
    common = _run_git(["rev-parse", "--git-common-dir"], results_root)
    if common.returncode != 0:
        return False
    # A submodule's common dir lives under the superproject's .git/modules/...
    return "modules" in Path(common.stdout.strip()).parts


def commit_audit(
    report_path: Path,
    results_root: Path,
    version: str,
    project_root: Path = _PROJECT_ROOT,
) -> None:
    """Commit the latest results and the audit report.

    When ``results_root`` is a submodule, this does the two-repo dance: commit
    and push the new ``output.xml`` inside the submodule first, then commit the
    pointer bump plus the report in the superproject. Pushing the submodule
    before bumping the pointer avoids a parent commit that references a SHA the
    remote doesn't have yet.
    """
    msg = f"chore: audit robot coverage for v{version}"

    if _is_submodule(results_root):
        # 1. Submodule: stage *all* fresh results, commit, push. run-local-models
        #    writes under results/local/<node>/<model>, not results/<version>/,
        #    so a version-scoped pathspec would silently drop the new output.xml.
        add = _run_git(["add", "-A"], results_root)
        if add.returncode != 0:
            print(f"  [audit] submodule add failed: {add.stderr.strip()}")
        committed = _run_git(["commit", "-m", msg], results_root)
        if committed.returncode == 0:
            push = _run_git(["push"], results_root)
            if push.returncode != 0:
                print(f"  [audit] submodule push failed: {push.stderr.strip()}")
        else:
            print(f"  [audit] nothing to commit in submodule ({committed.stdout.strip()})")
        # 2. Superproject: stage the pointer bump + the report.
        _run_git(["add", str(results_root.name)], project_root)
    else:
        _run_git(["add", "results"], project_root)

    rel_report = report_path.relative_to(project_root)
    _run_git(["add", str(rel_report)], project_root)
    parent_commit = _run_git(["commit", "-m", msg], project_root)
    if parent_commit.returncode == 0:
        print(f"  [audit] committed: {msg}")
    else:
        print(f"  [audit] nothing to commit in superproject ({parent_commit.stdout.strip()})")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_audit(
    *,
    results_root: Path,
    version: str | None,
    audit_dir: Path,
    commit: bool,
) -> Path | None:
    """Audit ``results_root`` and write the markdown report. Returns its path."""
    runs = find_runs(results_root)
    target = version or latest_version(runs)
    if target is None:
        print("No watermarked run-local-models results found; nothing to audit.")
        return None

    report = build_report(
        runs, target, load_suites(), load_master_models()
    )
    audit_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_path = audit_dir / f"{today}-v{target}-coverage.md"
    report_path.write_text(render_markdown(report))

    print(
        f"Audited v{target}: {len(report.models)} models × "
        f"{len(report.suites)} suites, "
        f"{report.covered_cells}/{report.total_cells} cells covered."
    )
    print(f"Report: {report_path}")
    missing = report.missing_fleet_models()
    if missing:
        print(f"Fleet models with no data: {', '.join(missing)}")

    if commit:
        commit_audit(report_path, results_root, target)
    return report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version", default=None, help="rfc version to audit (default: latest found)"
    )
    parser.add_argument(
        "--results-root",
        type=Path,
        default=DEFAULT_RESULTS_ROOT,
        help="root of the results tree (default: ./results)",
    )
    parser.add_argument(
        "--audit-dir",
        type=Path,
        default=DEFAULT_AUDIT_DIR,
        help="where to write the report (default: .claude/audits)",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="commit the latest results + report (submodule-aware)",
    )
    args = parser.parse_args(argv)

    report_path = run_audit(
        results_root=args.results_root,
        version=args.version,
        audit_dir=args.audit_dir,
        commit=args.commit,
    )
    return 0 if report_path is not None else 1


if __name__ == "__main__":
    sys.exit(main())
