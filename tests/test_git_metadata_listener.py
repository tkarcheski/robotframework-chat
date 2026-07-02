"""Tests for rfc.git_metadata_listener.GitMetaData (Listener API v3)."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rfc.git_metadata_listener import GitMetaData, GitMetaDataModifier, main


def _mock_suite_data(name: str = "Suite", source: str = "") -> MagicMock:
    """Create a mock running.TestSuite (data) object."""
    data = MagicMock()
    data.name = name
    data.source = Path(source) if source else None
    return data


def _mock_suite_result(
    metadata: dict | None = None,
    total: int = 1,
    passed: int = 1,
    failed: int = 0,
    skipped: int = 0,
) -> MagicMock:
    """Create a mock result.TestSuite (result) object."""
    result = MagicMock()
    result.metadata = metadata if metadata is not None else {}
    result.statistics.total = total
    result.statistics.passed = passed
    result.statistics.failed = failed
    result.statistics.skipped = skipped
    return result


class TestGitMetaDataInit:
    def test_robot_listener_api_version(self) -> None:
        listener = GitMetaData()
        assert listener.ROBOT_LISTENER_API_VERSION == 3

    def test_initial_state(self) -> None:
        listener = GitMetaData()
        assert listener.metadata == {}
        assert listener.start_time is None
        assert listener.ci_info == {}
        assert listener.platform is None
        assert listener._suite_depth == 0


class TestGitMetaDataSuiteDepth:
    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata", return_value={"CI": "false"}
    )
    def test_start_suite_increments_depth(self, _mock_ci: MagicMock) -> None:
        listener = GitMetaData()
        listener.start_suite(_mock_suite_data("Top"), _mock_suite_result())
        assert listener._suite_depth == 1
        listener.start_suite(_mock_suite_data("Nested"), _mock_suite_result())
        assert listener._suite_depth == 2

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata", return_value={"CI": "false"}
    )
    def test_start_suite_only_collects_metadata_at_top_level(
        self, mock_ci: MagicMock
    ) -> None:
        listener = GitMetaData()
        listener.start_suite(_mock_suite_data("Top"), _mock_suite_result())
        assert mock_ci.call_count == 1

        listener.start_suite(_mock_suite_data("Nested"), _mock_suite_result())
        # Should NOT re-collect metadata for nested suite
        assert mock_ci.call_count == 1

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata", return_value={"CI": "false"}
    )
    def test_end_suite_decrements_depth(self, _mock_ci: MagicMock) -> None:
        listener = GitMetaData()
        listener.start_suite(_mock_suite_data("Top"), _mock_suite_result())
        listener.start_suite(_mock_suite_data("Nested"), _mock_suite_result())
        listener.end_suite(_mock_suite_data("Nested"), _mock_suite_result())
        assert listener._suite_depth == 1

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata", return_value={"CI": "false"}
    )
    def test_end_suite_only_saves_json_at_top_level(self, _mock_ci: MagicMock) -> None:
        listener = GitMetaData()
        listener.start_suite(_mock_suite_data("Top"), _mock_suite_result())
        listener.start_suite(_mock_suite_data("Nested"), _mock_suite_result())

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                # End nested — should NOT save JSON
                nested_result = _mock_suite_result()
                listener.end_suite(_mock_suite_data("Nested"), nested_result)
                json_file = os.path.join(tmpdir, "ci_metadata.json")
                assert not os.path.exists(json_file)

                # End top-level — should save JSON
                top_result = _mock_suite_result()
                listener.end_suite(_mock_suite_data("Top"), top_result)
                assert os.path.exists(json_file)


class TestGitMetaDataStartSuite:
    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata",
        return_value={
            "CI": "true",
            "CI_Platform": "gitlab",
            "Project_URL": "https://gitlab.com/org/repo",
            "Commit_SHA": "abc12345def",
            "Commit_Short_SHA": "abc12345",
            "Branch": "main",
        },
    )
    def test_adds_ci_info_to_metadata(self, _mock_ci: MagicMock) -> None:
        listener = GitMetaData()
        result = _mock_suite_result()
        listener.start_suite(_mock_suite_data(), result)
        assert result.metadata["Branch"] == "main"
        assert result.metadata["CI"] == "true"

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata",
        return_value={
            "CI": "true",
            "CI_Platform": "gitlab",
            "Project_URL": "https://gitlab.com/org/repo",
            "Commit_SHA": "abc12345def",
            "Commit_Short_SHA": "abc12345",
        },
    )
    def test_formats_commit_link_gitlab(self, _mock_ci: MagicMock) -> None:
        listener = GitMetaData()
        result = _mock_suite_result()
        listener.start_suite(_mock_suite_data(), result)
        expected = "[abc12345|https://gitlab.com/org/repo/-/commit/abc12345def]"
        assert result.metadata["Commit_SHA"] == expected

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata",
        return_value={
            "CI": "true",
            "CI_Platform": "github",
            "Project_URL": "https://github.com/org/repo",
            "Commit_SHA": "abc12345def",
            "Commit_Short_SHA": "abc12345",
        },
    )
    def test_formats_commit_link_github(self, _mock_ci: MagicMock) -> None:
        listener = GitMetaData()
        result = _mock_suite_result()
        listener.start_suite(_mock_suite_data(), result)
        expected = "[abc12345|https://github.com/org/repo/commit/abc12345def]"
        assert result.metadata["Commit_SHA"] == expected

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata",
        return_value={
            "CI": "true",
            "CI_Platform": "gitlab",
            "Project_URL": "https://gitlab.com/org/repo",
            "Commit_SHA": "abc12345def",
        },
    )
    def test_formats_source_link_gitlab(self, _mock_ci: MagicMock) -> None:
        listener = GitMetaData()
        with patch.dict(os.environ, {"CI_PROJECT_DIR": "/builds/org/repo"}):
            data = _mock_suite_data(
                source="/builds/org/repo/robot/math/tests/test.robot"
            )
            result = _mock_suite_result()
            listener.start_suite(data, result)
        assert "robot/math/tests/test.robot" in result.metadata["Source"]
        assert "/-/blob/" in result.metadata["Source"]

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata",
        return_value={
            "CI": "true",
            "CI_Platform": "github",
            "Project_URL": "https://github.com/org/repo",
            "Commit_SHA": "abc12345def",
        },
    )
    def test_formats_source_link_github(self, _mock_ci: MagicMock) -> None:
        listener = GitMetaData()
        with patch.dict(os.environ, {"GITHUB_WORKSPACE": "/home/runner/work/repo"}):
            data = _mock_suite_data(
                source="/home/runner/work/repo/robot/math/tests/test.robot"
            )
            result = _mock_suite_result()
            listener.start_suite(data, result)
        assert "robot/math/tests/test.robot" in result.metadata["Source"]
        assert "/blob/" in result.metadata["Source"]

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata",
        return_value={"CI": "false"},
    )
    def test_no_commit_link_without_project_url(self, _mock_ci: MagicMock) -> None:
        listener = GitMetaData()
        result = _mock_suite_result()
        listener.start_suite(_mock_suite_data(), result)
        # Commit_SHA should not be formatted as link when no Project_URL
        assert "Commit_SHA" not in result.metadata

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata",
        return_value={"CI": "false"},
    )
    def test_records_start_time(self, _mock_ci: MagicMock) -> None:
        listener = GitMetaData()
        listener.start_suite(_mock_suite_data(), _mock_suite_result())
        assert listener.start_time is not None


class TestGitMetaDataEndSuite:
    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata", return_value={"CI": "false"}
    )
    def test_adds_timing_metadata(self, _mock_ci: MagicMock) -> None:
        listener = GitMetaData()
        listener.start_suite(_mock_suite_data(), _mock_suite_result())

        result = _mock_suite_result()
        listener.end_suite(_mock_suite_data(), result)

        assert "Test_Duration_Seconds" in result.metadata
        assert "Test_End_Time" in result.metadata
        assert "Test_Start_Time" in result.metadata
        assert result.metadata["Test_End_Time"].endswith("Z")
        assert "+00:00" not in result.metadata["Test_End_Time"]
        assert result.metadata["Test_Start_Time"].endswith("Z")
        assert "+00:00" not in result.metadata["Test_Start_Time"]

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata", return_value={"CI": "false"}
    )
    def test_adds_statistics(self, _mock_ci: MagicMock) -> None:
        listener = GitMetaData()
        listener.start_suite(_mock_suite_data(), _mock_suite_result())

        result = _mock_suite_result(total=5, passed=3, failed=1, skipped=1)
        listener.end_suite(_mock_suite_data(), result)

        assert result.metadata["Total_Tests"] == "5"
        assert result.metadata["Passed_Tests"] == "3"
        assert result.metadata["Failed_Tests"] == "1"
        assert result.metadata["Skipped_Tests"] == "1"

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata", return_value={"CI": "false"}
    )
    def test_saves_metadata_json(self, _mock_ci: MagicMock) -> None:
        listener = GitMetaData()
        listener.start_suite(_mock_suite_data(), _mock_suite_result())

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                result = _mock_suite_result()
                listener.end_suite(_mock_suite_data(), result)

            json_file = os.path.join(tmpdir, "ci_metadata.json")
            assert os.path.exists(json_file)

            with open(json_file) as f:
                data = json.load(f)
            assert "Test_Duration_Seconds" in data

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata", return_value={"CI": "false"}
    )
    def test_duration_zero_without_start_time(self, _mock_ci: MagicMock) -> None:
        listener = GitMetaData()
        # Manually skip start_suite so start_time is None
        listener._suite_depth = 1
        result = _mock_suite_result()
        listener.end_suite(_mock_suite_data(), result)
        assert result.metadata["Test_Duration_Seconds"] == "0"
        assert result.metadata["Test_Start_Time"] == ""


class TestGitMetaDataResolveRelativePath:
    def test_gitlab_path_resolution(self) -> None:
        listener = GitMetaData()
        listener.platform = "gitlab"
        with patch.dict(os.environ, {"CI_PROJECT_DIR": "/builds/org/repo"}):
            result = listener._resolve_relative_path(
                "/builds/org/repo/robot/test.robot"
            )
        assert result == "robot/test.robot"

    def test_github_path_resolution(self) -> None:
        listener = GitMetaData()
        listener.platform = "github"
        with patch.dict(os.environ, {"GITHUB_WORKSPACE": "/home/runner/work"}):
            result = listener._resolve_relative_path(
                "/home/runner/work/robot/test.robot"
            )
        assert result == "robot/test.robot"

    def test_returns_original_when_no_workspace(self) -> None:
        listener = GitMetaData()
        listener.platform = "gitlab"
        with patch.dict(os.environ, {}, clear=True):
            result = listener._resolve_relative_path("/some/path/test.robot")
        assert result == "/some/path/test.robot"

    def test_returns_original_when_path_doesnt_match(self) -> None:
        listener = GitMetaData()
        listener.platform = "gitlab"
        with patch.dict(os.environ, {"CI_PROJECT_DIR": "/builds/org/repo"}):
            result = listener._resolve_relative_path("/other/path/test.robot")
        assert result == "/other/path/test.robot"


class TestGitMetaDataFormatLinks:
    def test_format_commit_link_gitlab(self) -> None:
        listener = GitMetaData()
        listener.platform = "gitlab"
        result = listener._format_commit_link(
            "https://gitlab.com/org/repo", "abc123full", "abc123"
        )
        assert result == "[abc123|https://gitlab.com/org/repo/-/commit/abc123full]"

    def test_format_commit_link_github(self) -> None:
        listener = GitMetaData()
        listener.platform = "github"
        result = listener._format_commit_link(
            "https://github.com/org/repo", "abc123full", "abc123"
        )
        assert result == "[abc123|https://github.com/org/repo/commit/abc123full]"

    def test_format_source_link_gitlab(self) -> None:
        listener = GitMetaData()
        listener.platform = "gitlab"
        result = listener._format_source_link(
            "https://gitlab.com/org/repo", "abc123", "robot/test.robot"
        )
        assert (
            result
            == "[robot/test.robot|https://gitlab.com/org/repo/-/blob/abc123/robot/test.robot]"
        )

    def test_format_source_link_github(self) -> None:
        listener = GitMetaData()
        listener.platform = "github"
        result = listener._format_source_link(
            "https://github.com/org/repo", "abc123", "robot/test.robot"
        )
        assert (
            result
            == "[robot/test.robot|https://github.com/org/repo/blob/abc123/robot/test.robot]"
        )


# ── Pipeline_URL and Job_URL formatting ──────────────────────────────


class TestGitMetaDataPipelineAndJobLinks:
    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata",
        return_value={
            "CI": "true",
            "CI_Platform": "gitlab",
            "Pipeline_URL": "https://gitlab.com/org/repo/-/pipelines/123",
            "Pipeline_ID": "123",
        },
    )
    def test_pipeline_url_passes_through(self, _mock_ci: MagicMock) -> None:
        listener = GitMetaData()
        result = _mock_suite_result()
        listener.start_suite(_mock_suite_data(), result)
        assert (
            result.metadata["Pipeline_URL"]
            == "https://gitlab.com/org/repo/-/pipelines/123"
        )

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata",
        return_value={
            "CI": "true",
            "CI_Platform": "gitlab",
            "Job_URL": "https://gitlab.com/org/repo/-/jobs/456",
            "Job_Name": "test-math",
            "Job_ID": "456",
        },
    )
    def test_formats_job_url_with_name(self, _mock_ci: MagicMock) -> None:
        listener = GitMetaData()
        result = _mock_suite_result()
        listener.start_suite(_mock_suite_data(), result)
        assert result.metadata["Job_URL"] == (
            "[test-math|https://gitlab.com/org/repo/-/jobs/456]"
        )

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata",
        return_value={
            "CI": "true",
            "CI_Platform": "gitlab",
            "Job_URL": "https://gitlab.com/org/repo/-/jobs/789",
            "Job_ID": "789",
        },
    )
    def test_formats_job_url_with_id_only(self, _mock_ci: MagicMock) -> None:
        listener = GitMetaData()
        result = _mock_suite_result()
        listener.start_suite(_mock_suite_data(), result)
        assert result.metadata["Job_URL"] == (
            "[Job #789|https://gitlab.com/org/repo/-/jobs/789]"
        )


# ── _save_metadata_json error path ──────────────────────────────────


class TestSaveMetadataJsonError:
    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata", return_value={"CI": "false"}
    )
    def test_save_error_does_not_raise(
        self, _mock_ci: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        listener = GitMetaData()
        listener.start_suite(_mock_suite_data(), _mock_suite_result())

        # Point to a non-writable directory
        monkeypatch.setenv("ROBOT_OUTPUT_DIR", "/nonexistent/readonly/dir")
        result = _mock_suite_result()
        # Should not raise
        listener.end_suite(_mock_suite_data(), result)


# ── GitMetaDataModifier ─────────────────────────────────────────────


class TestGitMetaDataModifier:
    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata",
        return_value={
            "CI": "true",
            "Branch": "main",
            "Commit_SHA": "abc123",
        },
    )
    def test_start_suite_adds_metadata(self, _mock_ci: MagicMock) -> None:
        modifier = GitMetaDataModifier()
        suite = MagicMock()
        suite.metadata = {}
        modifier.start_suite(suite)
        assert suite.metadata["CI"] == "true"
        assert suite.metadata["Branch"] == "main"
        assert modifier.start_time is not None

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata", return_value={"CI": "false"}
    )
    def test_sets_platform(self, _mock_ci: MagicMock) -> None:
        modifier = GitMetaDataModifier()
        suite = MagicMock()
        suite.metadata = {}
        modifier.start_suite(suite)
        assert modifier.ci_info == {"CI": "false"}


# ── main() ───────────────────────────────────────────────────────────


class TestGitMetaDataMain:
    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata",
        return_value={"CI": "true", "Branch": "main"},
    )
    def test_main_in_ci_returns_zero(self, _mock_ci: MagicMock) -> None:
        assert main() == 0

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata",
        return_value={"CI": "false"},
    )
    def test_main_outside_ci_returns_one(self, _mock_ci: MagicMock) -> None:
        assert main() == 1
