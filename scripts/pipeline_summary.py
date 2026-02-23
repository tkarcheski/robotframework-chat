#!/usr/bin/env python3
"""Collect pipeline job statuses and test results, generate an MR summary.

Queries the GitLab CI API for the current pipeline's jobs, optionally
parses JUnit XML artifacts, and produces a Markdown summary suitable
for posting as an MR comment.
"""

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import requests


# ── Data models ──────────────────────────────────────────────────────


@dataclass
class PipelineInfo:
    """Core metadata about the current pipeline."""

    pipeline_id: int
    project_url: str
    ref: str
    sha: str
    short_sha: str
    status: str
    source: str
    created_at: str


@dataclass
class JobInfo:
    """Status and metadata for a single CI job."""

    name: str
    stage: str
    status: str
    duration: float | None
    allow_failure: bool
    web_url: str


@dataclass
class JUnitSuite:
    """Parsed summary from a JUnit XML ``<testsuite>`` element."""

    name: str
    tests: int
    failures: int
    errors: int
    skipped: int


@dataclass
class SuiteCounts:
    """Aggregated test counts across all suites."""

    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0


# ── Pure helpers ─────────────────────────────────────────────────────

STATUS_EMOJIS: dict[str, str] = {
    "success": ":white_check_mark:",
    "failed": ":x:",
    "running": ":arrows_counterclockwise:",
    "pending": ":hourglass:",
    "skipped": ":fast_forward:",
    "canceled": ":no_entry_sign:",
    "created": ":new:",
    "manual": ":hand:",
}


def format_duration(seconds: float | None) -> str:
    """Human-readable duration string."""
    if seconds is None:
        return "-"
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    minutes = total // 60
    secs = total % 60
    return f"{minutes}m {secs}s"


def format_status_emoji(status: str) -> str:
    """Map a GitLab job status to a Markdown emoji."""
    return STATUS_EMOJIS.get(status, ":grey_question:")


def aggregate_test_counts(suites: list[JUnitSuite]) -> SuiteCounts:
    """Sum test counts across all JUnit suites."""
    counts = SuiteCounts()
    for s in suites:
        counts.total += s.tests
        counts.failed += s.failures
        counts.errors += s.errors
        counts.skipped += s.skipped
    counts.passed = counts.total - counts.failed - counts.errors - counts.skipped
    return counts


# ── Summary generation ───────────────────────────────────────────────


def generate_summary(
    pipeline: PipelineInfo,
    jobs: list[JobInfo],
    junit_suites: list[JUnitSuite] | None = None,
) -> str:
    """Generate a Markdown pipeline testing summary."""
    parts: list[str] = []

    # -- Header --
    parts.append("## Pipeline Testing Summary\n")
    pipeline_url = f"{pipeline.project_url}/-/pipelines/{pipeline.pipeline_id}"
    parts.append(f"**Pipeline:** [{pipeline.pipeline_id}]({pipeline_url})  ")
    parts.append(f"**Branch:** `{pipeline.ref}`  ")
    parts.append(f"**Commit:** `{pipeline.short_sha}`  ")
    parts.append(
        f"**Status:** {format_status_emoji(pipeline.status)} {pipeline.status}  "
    )
    parts.append(f"**Triggered by:** {pipeline.source}\n")

    # -- Job status table --
    if jobs:
        parts.append("### Job Results\n")
        parts.append("| Job | Stage | Status | Duration | Notes |")
        parts.append("|-----|-------|--------|----------|-------|")
        for job in jobs:
            status_str = f"{format_status_emoji(job.status)} {job.status}"
            dur_str = format_duration(job.duration)
            notes = ""
            if job.allow_failure:
                notes = "_optional_"
            job_link = f"[{job.name}]({job.web_url})"
            parts.append(
                f"| {job_link} | {job.stage} | {status_str} | {dur_str} | {notes} |"
            )
        parts.append("")
    else:
        parts.append("_No jobs found in this pipeline._\n")

    # -- Test results (JUnit) --
    if junit_suites:
        counts = aggregate_test_counts(junit_suites)
        parts.append("### Test Results\n")
        parts.append("| Suite | Tests | Passed | Failed | Errors | Skipped |")
        parts.append("|-------|------:|-------:|-------:|-------:|--------:|")
        for s in junit_suites:
            s_passed = s.tests - s.failures - s.errors - s.skipped
            parts.append(
                f"| {s.name} | {s.tests} | {s_passed} "
                f"| {s.failures} | {s.errors} | {s.skipped} |"
            )
        parts.append(
            f"| **Total** | **{counts.total}** | **{counts.passed}** "
            f"| **{counts.failed}** | **{counts.errors}** "
            f"| **{counts.skipped}** |\n"
        )

    # -- Failed required jobs --
    failed_required = [j for j in jobs if j.status == "failed" and not j.allow_failure]
    if failed_required:
        parts.append("### Failed Jobs (Required)\n")
        for j in failed_required:
            parts.append(f"- :x: [{j.name}]({j.web_url}) ({j.stage})")
        parts.append("")

    # -- Verdict --
    parts.append("### Verdict\n")
    if failed_required:
        names = ", ".join(f"`{j.name}`" for j in failed_required)
        parts.append(
            f":x: **FAILED** — {len(failed_required)} required job(s) failed: {names}"
        )
    elif pipeline.status == "success":
        parts.append(":white_check_mark: **PASSED** — all required jobs succeeded")
    else:
        parts.append(
            f"{format_status_emoji(pipeline.status)} **{pipeline.status.upper()}**"
        )
    parts.append("")

    return "\n".join(parts)


# ── JUnit XML parsing ───────────────────────────────────────────────


def parse_junit_xml(path: Path) -> list[JUnitSuite]:
    """Parse a JUnit XML file and return suite summaries."""
    suites: list[JUnitSuite] = []
    tree = ET.parse(path)
    root = tree.getroot()

    # Handle both <testsuites><testsuite>... and bare <testsuite>
    if root.tag == "testsuites":
        elements = root.findall("testsuite")
    elif root.tag == "testsuite":
        elements = [root]
    else:
        return suites

    for elem in elements:
        suites.append(
            JUnitSuite(
                name=elem.get("name", "unknown"),
                tests=int(elem.get("tests", "0")),
                failures=int(elem.get("failures", "0")),
                errors=int(elem.get("errors", "0")),
                skipped=int(elem.get("skipped", "0")),
            )
        )
    return suites


# ── GitLab API helpers ───────────────────────────────────────────────


def fetch_pipeline_info() -> PipelineInfo:
    """Build PipelineInfo from GitLab CI environment variables."""
    return PipelineInfo(
        pipeline_id=int(os.environ.get("CI_PIPELINE_ID", "0")),
        project_url=os.environ.get("CI_PROJECT_URL", ""),
        ref=os.environ.get("CI_COMMIT_REF_NAME", "unknown"),
        sha=os.environ.get("CI_COMMIT_SHA", "unknown"),
        short_sha=os.environ.get("CI_COMMIT_SHORT_SHA", "unknown"),
        status=os.environ.get("CI_PIPELINE_STATUS", "unknown"),
        source=os.environ.get("CI_PIPELINE_SOURCE", "unknown"),
        created_at=os.environ.get("CI_PIPELINE_CREATED_AT", ""),
    )


def fetch_pipeline_jobs() -> list[JobInfo]:
    """Fetch jobs for the current pipeline via the GitLab API."""
    api_url = os.environ.get("CI_API_V4_URL", "")
    project_id = os.environ.get("CI_PROJECT_ID", "")
    pipeline_id = os.environ.get("CI_PIPELINE_ID", "")
    token = os.environ.get("GITLAB_TOKEN", "")

    if not all([api_url, project_id, pipeline_id, token]):
        print(
            "WARNING: Missing GitLab CI env vars, cannot fetch jobs.",
            file=sys.stderr,
        )
        return []

    url = f"{api_url}/projects/{project_id}/pipelines/{pipeline_id}/jobs"
    headers = {"PRIVATE-TOKEN": token}
    jobs: list[JobInfo] = []
    page = 1

    while True:
        resp = requests.get(
            url, headers=headers, params={"per_page": 100, "page": page}
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            break
        for j in data:
            jobs.append(
                JobInfo(
                    name=j["name"],
                    stage=j["stage"],
                    status=j["status"],
                    duration=j.get("duration"),
                    allow_failure=j.get("allow_failure", False),
                    web_url=j.get("web_url", ""),
                )
            )
        page += 1

    # Sort by stage order, then name
    stage_order = ["lint", "generate", "test", "report", "deploy", "release", "review"]
    jobs.sort(
        key=lambda j: (
            stage_order.index(j.stage) if j.stage in stage_order else 99,
            j.name,
        )
    )
    return jobs


# ── Main ─────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline testing summary")
    parser.add_argument(
        "-o",
        "--output-dir",
        default="metrics",
        help="Output directory (default: metrics)",
    )
    parser.add_argument(
        "--junit-xml",
        action="append",
        default=[],
        help="Path to JUnit XML file(s) to include in summary",
    )
    args = parser.parse_args()

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    print("Fetching pipeline info...", file=sys.stderr)
    pipeline = fetch_pipeline_info()

    print("Fetching pipeline jobs...", file=sys.stderr)
    jobs = fetch_pipeline_jobs()
    print(f"  Found {len(jobs)} jobs", file=sys.stderr)

    # Parse JUnit XML files
    junit_suites: list[JUnitSuite] = []
    for xml_path in args.junit_xml:
        p = Path(xml_path)
        if p.is_file():
            print(f"  Parsing JUnit XML: {p}", file=sys.stderr)
            junit_suites.extend(parse_junit_xml(p))
        else:
            print(f"  JUnit XML not found: {p}", file=sys.stderr)

    # Generate summary
    summary = generate_summary(pipeline, jobs, junit_suites or None)
    summary_path = out / "pipeline_summary.md"
    summary_path.write_text(summary)
    print(f"Summary saved to {summary_path}", file=sys.stderr)

    # Also save raw job data as JSON
    jobs_data = [
        {
            "name": j.name,
            "stage": j.stage,
            "status": j.status,
            "duration": j.duration,
            "allow_failure": j.allow_failure,
            "web_url": j.web_url,
        }
        for j in jobs
    ]
    json_path = out / "pipeline_jobs.json"
    json_path.write_text(json.dumps(jobs_data, indent=2))

    print(summary)


if __name__ == "__main__":
    main()
