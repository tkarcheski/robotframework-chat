"""Tests for scripts/pipeline_summary.py — pure-function helpers.

Tests for GitLab API-dependent functions are omitted since they require
a live GitLab instance. These tests cover the pure formatting and
aggregation logic.
"""

from __future__ import annotations

from scripts.pipeline_summary import (
    PipelineInfo,
    JobInfo,
    JUnitSuite,
    SuiteCounts,
    aggregate_test_counts,
    format_duration,
    format_status_emoji,
    generate_summary,
)


class TestFormatDuration:
    def test_seconds_only(self) -> None:
        assert format_duration(45.0) == "45s"

    def test_minutes_and_seconds(self) -> None:
        assert format_duration(125.0) == "2m 5s"

    def test_zero(self) -> None:
        assert format_duration(0.0) == "0s"

    def test_exact_minute(self) -> None:
        assert format_duration(60.0) == "1m 0s"

    def test_none(self) -> None:
        assert format_duration(None) == "-"


class TestFormatStatusEmoji:
    def test_success(self) -> None:
        assert format_status_emoji("success") == ":white_check_mark:"

    def test_failed(self) -> None:
        assert format_status_emoji("failed") == ":x:"

    def test_running(self) -> None:
        assert format_status_emoji("running") == ":arrows_counterclockwise:"

    def test_skipped(self) -> None:
        assert format_status_emoji("skipped") == ":fast_forward:"

    def test_unknown(self) -> None:
        assert format_status_emoji("something_else") == ":grey_question:"

    def test_created(self) -> None:
        assert format_status_emoji("created") == ":new:"

    def test_canceled(self) -> None:
        assert format_status_emoji("canceled") == ":no_entry_sign:"

    def test_manual(self) -> None:
        assert format_status_emoji("manual") == ":hand:"

    def test_pending(self) -> None:
        assert format_status_emoji("pending") == ":hourglass:"


class TestAggregateSuiteCounts:
    def test_single_suite(self) -> None:
        suites = [
            JUnitSuite(name="pytest", tests=10, failures=2, errors=1, skipped=1)
        ]
        counts = aggregate_test_counts(suites)
        assert counts == SuiteCounts(total=10, passed=6, failed=2, errors=1, skipped=1)

    def test_multiple_suites(self) -> None:
        suites = [
            JUnitSuite(name="unit", tests=20, failures=1, errors=0, skipped=2),
            JUnitSuite(name="integration", tests=5, failures=0, errors=0, skipped=0),
        ]
        counts = aggregate_test_counts(suites)
        assert counts == SuiteCounts(
            total=25, passed=22, failed=1, errors=0, skipped=2
        )

    def test_empty(self) -> None:
        counts = aggregate_test_counts([])
        assert counts == SuiteCounts(total=0, passed=0, failed=0, errors=0, skipped=0)

    def test_all_failures(self) -> None:
        suites = [JUnitSuite(name="bad", tests=5, failures=3, errors=2, skipped=0)]
        counts = aggregate_test_counts(suites)
        assert counts == SuiteCounts(total=5, passed=0, failed=3, errors=2, skipped=0)


class TestGenerateSummary:
    def _make_pipeline(self) -> PipelineInfo:
        return PipelineInfo(
            pipeline_id=12345,
            project_url="https://gitlab.example.com/group/project",
            ref="feature-branch",
            sha="abc1234def5678",
            short_sha="abc1234",
            status="success",
            source="merge_request_event",
            created_at="2026-02-22T10:00:00Z",
        )

    def _make_jobs(self) -> list[JobInfo]:
        return [
            JobInfo(
                name="lint",
                stage="lint",
                status="success",
                duration=32.5,
                allow_failure=True,
                web_url="https://gitlab.example.com/group/project/-/jobs/100",
            ),
            JobInfo(
                name="dashboard-pytest",
                stage="test",
                status="success",
                duration=45.2,
                allow_failure=False,
                web_url="https://gitlab.example.com/group/project/-/jobs/101",
            ),
            JobInfo(
                name="run-regular-tests",
                stage="test",
                status="failed",
                duration=120.8,
                allow_failure=False,
                web_url="https://gitlab.example.com/group/project/-/jobs/102",
            ),
        ]

    def _make_junit_suites(self) -> list[JUnitSuite]:
        return [
            JUnitSuite(
                name="tests/test_dashboard_layout.py",
                tests=15,
                failures=0,
                errors=0,
                skipped=1,
            ),
            JUnitSuite(
                name="tests/test_dashboard_monitoring.py",
                tests=8,
                failures=1,
                errors=0,
                skipped=0,
            ),
        ]

    def test_contains_header(self) -> None:
        summary = generate_summary(self._make_pipeline(), self._make_jobs())
        assert "## Pipeline Testing Summary" in summary

    def test_contains_pipeline_info(self) -> None:
        summary = generate_summary(self._make_pipeline(), self._make_jobs())
        assert "12345" in summary
        assert "abc1234" in summary
        assert "feature-branch" in summary

    def test_contains_job_table(self) -> None:
        summary = generate_summary(self._make_pipeline(), self._make_jobs())
        assert "| Job | Stage | Status | Duration |" in summary
        assert "lint" in summary
        assert "dashboard-pytest" in summary
        assert "run-regular-tests" in summary

    def test_contains_verdict(self) -> None:
        summary = generate_summary(self._make_pipeline(), self._make_jobs())
        # Pipeline has a failed required job, so verdict should reflect that
        assert "failed" in summary.lower() or "FAILED" in summary

    def test_success_pipeline(self) -> None:
        pipeline = self._make_pipeline()
        jobs = [
            JobInfo(
                name="lint",
                stage="lint",
                status="success",
                duration=30.0,
                allow_failure=True,
                web_url="https://example.com/-/jobs/1",
            ),
            JobInfo(
                name="dashboard-pytest",
                stage="test",
                status="success",
                duration=45.0,
                allow_failure=False,
                web_url="https://example.com/-/jobs/2",
            ),
        ]
        pipeline.status = "success"
        summary = generate_summary(pipeline, jobs)
        assert "passed" in summary.lower() or "PASSED" in summary

    def test_with_junit_suites(self) -> None:
        summary = generate_summary(
            self._make_pipeline(),
            self._make_jobs(),
            junit_suites=self._make_junit_suites(),
        )
        assert "### Test Results" in summary
        assert "23" in summary  # total tests
        assert "test_dashboard_layout" in summary

    def test_without_junit_suites(self) -> None:
        summary = generate_summary(self._make_pipeline(), self._make_jobs())
        # Should not have the test results section when no JUnit data
        assert "### Test Results" not in summary

    def test_empty_jobs(self) -> None:
        summary = generate_summary(self._make_pipeline(), [])
        assert "## Pipeline Testing Summary" in summary
        assert "No jobs found" in summary or "| Job |" in summary

    def test_allow_failure_noted(self) -> None:
        """Jobs with allow_failure should be visually distinct."""
        summary = generate_summary(self._make_pipeline(), self._make_jobs())
        # lint has allow_failure=True - it should be annotated
        assert "allow_failure" in summary.lower() or "optional" in summary.lower()

    def test_failed_required_jobs_listed(self) -> None:
        summary = generate_summary(self._make_pipeline(), self._make_jobs())
        # Should call out which required jobs failed
        assert "run-regular-tests" in summary
