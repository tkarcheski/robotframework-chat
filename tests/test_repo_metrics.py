"""Tests for scripts/repo_metrics.py — pure-function helpers.

Tests for git-dependent functions (get_commits, metrics_at_commit, collect_timeline)
are omitted since they require a real git repo. These tests cover the pure logic.
"""

from datetime import datetime

from scripts.repo_metrics import (
    _compute_deltas,
    _thin_indices,
    generate_summary,
    sample_commits,
)


class TestSampleCommits:
    def test_small_list_unchanged(self):
        commits = [(f"sha{i}", datetime(2024, 1, i + 1)) for i in range(5)]
        result = sample_commits(commits, max_points=10)
        assert result == commits

    def test_large_list_sampled(self):
        commits = [(f"sha{i}", datetime(2024, 1, 1)) for i in range(100)]
        result = sample_commits(commits, max_points=10)
        assert len(result) <= 11  # 10 + possibly last

    def test_always_includes_last(self):
        commits = [(f"sha{i}", datetime(2024, 1, 1)) for i in range(100)]
        result = sample_commits(commits, max_points=10)
        assert result[-1] == commits[-1]

    def test_empty_list(self):
        assert sample_commits([], max_points=10) == []

    def test_single_commit(self):
        commits = [("sha0", datetime(2024, 1, 1))]
        assert sample_commits(commits, max_points=10) == commits


class TestThinIndices:
    def test_small_total(self):
        assert _thin_indices(5, 10) == [0, 1, 2, 3, 4]

    def test_exact_match(self):
        assert _thin_indices(10, 10) == list(range(10))

    def test_larger_total(self):
        result = _thin_indices(100, 5)
        assert len(result) <= 6  # 5 + possibly last
        assert result[-1] == 99
        assert result[0] == 0

    def test_always_includes_first_and_last(self):
        result = _thin_indices(50, 3)
        assert result[0] == 0
        assert result[-1] == 49


class TestComputeDeltas:
    def test_two_snapshots(self):
        timeline = [
            {
                "metrics": {
                    "Python (.py)": {"files": 5, "lines": 100, "bytes": 5000},
                    "Other": {"files": 2, "lines": 20, "bytes": 1000},
                }
            },
            {
                "metrics": {
                    "Python (.py)": {"files": 10, "lines": 300, "bytes": 15000},
                    "Other": {"files": 3, "lines": 30, "bytes": 1500},
                }
            },
        ]
        deltas = _compute_deltas(timeline)
        assert deltas["Python (.py)"]["delta_files"] == 5
        assert deltas["Python (.py)"]["delta_lines"] == 200
        assert deltas["Other"]["delta_bytes"] == 500

    def test_single_snapshot_returns_empty(self):
        assert _compute_deltas([{"metrics": {}}]) == {}

    def test_empty_timeline(self):
        assert _compute_deltas([]) == {}


class TestGenerateSummary:
    def _make_timeline(self):
        return [
            {
                "sha": "aaa1111",
                "short_sha": "aaa1111",
                "date": "2024-01-01T12:00:00",
                "metrics": {
                    "Python (.py)": {"files": 5, "lines": 100, "bytes": 5000},
                    "Robot (.robot)": {"files": 2, "lines": 50, "bytes": 2000},
                    "Other": {"files": 1, "lines": 10, "bytes": 500},
                },
            },
            {
                "sha": "bbb2222",
                "short_sha": "bbb2222",
                "date": "2024-06-15T14:30:00",
                "metrics": {
                    "Python (.py)": {"files": 15, "lines": 500, "bytes": 25000},
                    "Robot (.robot)": {"files": 5, "lines": 150, "bytes": 6000},
                    "Other": {"files": 3, "lines": 30, "bytes": 1500},
                },
            },
        ]

    def test_summary_contains_sections(self):
        summary = generate_summary(self._make_timeline())
        assert "## Repository Metrics Report" in summary
        assert "### Current Snapshot" in summary
        assert "### Growth Since First Sampled Commit" in summary
        assert "### Composition" in summary
        assert "### Timeline Highlights" in summary
        assert "### Lines of Code Over Time" in summary

    def test_summary_contains_data(self):
        summary = generate_summary(self._make_timeline())
        assert "bbb2222" in summary
        assert "Python (.py)" in summary

    def test_single_snapshot(self):
        timeline = [
            {
                "sha": "aaa1111",
                "short_sha": "aaa1111",
                "date": "2024-01-01T12:00:00",
                "metrics": {
                    "Python (.py)": {"files": 5, "lines": 100, "bytes": 5000},
                    "Robot (.robot)": {"files": 0, "lines": 0, "bytes": 0},
                    "Other": {"files": 0, "lines": 0, "bytes": 0},
                },
            }
        ]
        summary = generate_summary(timeline)
        assert "## Repository Metrics Report" in summary
