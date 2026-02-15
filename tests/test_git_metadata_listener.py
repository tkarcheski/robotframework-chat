"""Tests for rfc.git_metadata_listener.GitMetaData."""

import json
import os
import tempfile
from unittest.mock import patch

from rfc.git_metadata_listener import GitMetaData


def _suite_start_attrs(metadata=None, source=""):
    """Build a minimal suite-start attributes dict."""
    return {
        "metadata": metadata if metadata is not None else {},
        "source": source,
    }


def _suite_end_attrs(metadata=None, totaltests=1, pass_=1, fail=0, skip=0):
    """Build a minimal suite-end attributes dict."""
    return {
        "metadata": metadata if metadata is not None else {},
        "totaltests": totaltests,
        "pass": pass_,
        "fail": fail,
        "skip": skip,
    }


class TestGitMetaDataInit:
    def test_robot_listener_api_version(self):
        listener = GitMetaData()
        assert listener.ROBOT_LISTENER_API_VERSION == 2

    def test_initial_state(self):
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
    def test_start_suite_increments_depth(self, _mock_ci):
        listener = GitMetaData()
        listener.start_suite("Top", _suite_start_attrs())
        assert listener._suite_depth == 1
        listener.start_suite("Nested", _suite_start_attrs())
        assert listener._suite_depth == 2

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata", return_value={"CI": "false"}
    )
    def test_start_suite_only_collects_metadata_at_top_level(self, mock_ci):
        listener = GitMetaData()
        listener.start_suite("Top", _suite_start_attrs())
        assert mock_ci.call_count == 1

        listener.start_suite("Nested", _suite_start_attrs())
        # Should NOT re-collect metadata for nested suite
        assert mock_ci.call_count == 1

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata", return_value={"CI": "false"}
    )
    def test_end_suite_decrements_depth(self, _mock_ci):
        listener = GitMetaData()
        listener.start_suite("Top", _suite_start_attrs())
        listener.start_suite("Nested", _suite_start_attrs())
        listener.end_suite("Nested", _suite_end_attrs())
        assert listener._suite_depth == 1

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata", return_value={"CI": "false"}
    )
    def test_end_suite_only_saves_json_at_top_level(self, _mock_ci):
        listener = GitMetaData()
        listener.start_suite("Top", _suite_start_attrs())
        listener.start_suite("Nested", _suite_start_attrs())

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                # End nested — should NOT save JSON
                listener.end_suite("Nested", _suite_end_attrs())
                json_file = os.path.join(tmpdir, "ci_metadata.json")
                assert not os.path.exists(json_file)

                # End top-level — should save JSON
                listener.end_suite("Top", _suite_end_attrs())
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
    def test_adds_ci_info_to_metadata(self, _mock_ci):
        listener = GitMetaData()
        attrs = _suite_start_attrs()
        listener.start_suite("Suite", attrs)
        assert attrs["metadata"]["Branch"] == "main"
        assert attrs["metadata"]["CI"] == "true"

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
    def test_formats_commit_link_gitlab(self, _mock_ci):
        listener = GitMetaData()
        attrs = _suite_start_attrs()
        listener.start_suite("Suite", attrs)
        expected = "[abc12345|https://gitlab.com/org/repo/-/commit/abc12345def]"
        assert attrs["metadata"]["Commit_SHA"] == expected

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
    def test_formats_commit_link_github(self, _mock_ci):
        listener = GitMetaData()
        attrs = _suite_start_attrs()
        listener.start_suite("Suite", attrs)
        expected = "[abc12345|https://github.com/org/repo/commit/abc12345def]"
        assert attrs["metadata"]["Commit_SHA"] == expected

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata",
        return_value={
            "CI": "true",
            "CI_Platform": "gitlab",
            "Project_URL": "https://gitlab.com/org/repo",
            "Commit_SHA": "abc12345def",
        },
    )
    def test_formats_source_link_gitlab(self, _mock_ci):
        listener = GitMetaData()
        with patch.dict(os.environ, {"CI_PROJECT_DIR": "/builds/org/repo"}):
            attrs = _suite_start_attrs(
                source="/builds/org/repo/robot/math/tests/test.robot"
            )
            listener.start_suite("Suite", attrs)
        assert "robot/math/tests/test.robot" in attrs["metadata"]["Source"]
        assert "/-/blob/" in attrs["metadata"]["Source"]

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata",
        return_value={
            "CI": "true",
            "CI_Platform": "github",
            "Project_URL": "https://github.com/org/repo",
            "Commit_SHA": "abc12345def",
        },
    )
    def test_formats_source_link_github(self, _mock_ci):
        listener = GitMetaData()
        with patch.dict(os.environ, {"GITHUB_WORKSPACE": "/home/runner/work/repo"}):
            attrs = _suite_start_attrs(
                source="/home/runner/work/repo/robot/math/tests/test.robot"
            )
            listener.start_suite("Suite", attrs)
        assert "robot/math/tests/test.robot" in attrs["metadata"]["Source"]
        assert "/blob/" in attrs["metadata"]["Source"]

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata",
        return_value={"CI": "false"},
    )
    def test_no_commit_link_without_project_url(self, _mock_ci):
        listener = GitMetaData()
        attrs = _suite_start_attrs()
        listener.start_suite("Suite", attrs)
        # Commit_SHA should not be formatted as link when no Project_URL
        assert "Commit_SHA" not in attrs["metadata"]

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata",
        return_value={"CI": "false"},
    )
    def test_records_start_time(self, _mock_ci):
        listener = GitMetaData()
        listener.start_suite("Suite", _suite_start_attrs())
        assert listener.start_time is not None


class TestGitMetaDataEndSuite:
    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata", return_value={"CI": "false"}
    )
    def test_adds_timing_metadata(self, _mock_ci):
        listener = GitMetaData()
        listener.start_suite("Suite", _suite_start_attrs())

        end_attrs = _suite_end_attrs()
        listener.end_suite("Suite", end_attrs)

        assert "Test_Duration_Seconds" in end_attrs["metadata"]
        assert "Test_End_Time" in end_attrs["metadata"]
        assert "Test_Start_Time" in end_attrs["metadata"]
        assert end_attrs["metadata"]["Test_End_Time"].endswith("Z")
        assert end_attrs["metadata"]["Test_Start_Time"].endswith("Z")

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata", return_value={"CI": "false"}
    )
    def test_adds_statistics(self, _mock_ci):
        listener = GitMetaData()
        listener.start_suite("Suite", _suite_start_attrs())

        end_attrs = _suite_end_attrs(totaltests=5, pass_=3, fail=1, skip=1)
        listener.end_suite("Suite", end_attrs)

        assert end_attrs["metadata"]["Total_Tests"] == "5"
        assert end_attrs["metadata"]["Passed_Tests"] == "3"
        assert end_attrs["metadata"]["Failed_Tests"] == "1"
        assert end_attrs["metadata"]["Skipped_Tests"] == "1"

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata", return_value={"CI": "false"}
    )
    def test_saves_metadata_json(self, _mock_ci):
        listener = GitMetaData()
        listener.start_suite("Suite", _suite_start_attrs())

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                end_attrs = _suite_end_attrs()
                listener.end_suite("Suite", end_attrs)

            json_file = os.path.join(tmpdir, "ci_metadata.json")
            assert os.path.exists(json_file)

            with open(json_file) as f:
                data = json.load(f)
            assert "Test_Duration_Seconds" in data

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata", return_value={"CI": "false"}
    )
    def test_handles_missing_metadata_key(self, _mock_ci):
        listener = GitMetaData()
        listener.start_suite("Suite", _suite_start_attrs())

        # end_suite with no metadata key — should not raise
        attrs = {"totaltests": 1, "pass": 1, "fail": 0, "skip": 0}
        listener.end_suite("Suite", attrs)

    @patch(
        "rfc.git_metadata_listener.collect_ci_metadata", return_value={"CI": "false"}
    )
    def test_duration_zero_without_start_time(self, _mock_ci):
        listener = GitMetaData()
        # Manually skip start_suite so start_time is None
        listener._suite_depth = 1
        end_attrs = _suite_end_attrs()
        listener.end_suite("Suite", end_attrs)
        assert end_attrs["metadata"]["Test_Duration_Seconds"] == "0"
        assert end_attrs["metadata"]["Test_Start_Time"] == ""


class TestGitMetaDataResolveRelativePath:
    def test_gitlab_path_resolution(self):
        listener = GitMetaData()
        listener.platform = "gitlab"
        with patch.dict(os.environ, {"CI_PROJECT_DIR": "/builds/org/repo"}):
            result = listener._resolve_relative_path(
                "/builds/org/repo/robot/test.robot"
            )
        assert result == "robot/test.robot"

    def test_github_path_resolution(self):
        listener = GitMetaData()
        listener.platform = "github"
        with patch.dict(os.environ, {"GITHUB_WORKSPACE": "/home/runner/work"}):
            result = listener._resolve_relative_path(
                "/home/runner/work/robot/test.robot"
            )
        assert result == "robot/test.robot"

    def test_returns_original_when_no_workspace(self):
        listener = GitMetaData()
        listener.platform = "gitlab"
        with patch.dict(os.environ, {}, clear=True):
            result = listener._resolve_relative_path("/some/path/test.robot")
        assert result == "/some/path/test.robot"

    def test_returns_original_when_path_doesnt_match(self):
        listener = GitMetaData()
        listener.platform = "gitlab"
        with patch.dict(os.environ, {"CI_PROJECT_DIR": "/builds/org/repo"}):
            result = listener._resolve_relative_path("/other/path/test.robot")
        assert result == "/other/path/test.robot"


class TestGitMetaDataFormatLinks:
    def test_format_commit_link_gitlab(self):
        listener = GitMetaData()
        listener.platform = "gitlab"
        result = listener._format_commit_link(
            "https://gitlab.com/org/repo", "abc123full", "abc123"
        )
        assert result == "[abc123|https://gitlab.com/org/repo/-/commit/abc123full]"

    def test_format_commit_link_github(self):
        listener = GitMetaData()
        listener.platform = "github"
        result = listener._format_commit_link(
            "https://github.com/org/repo", "abc123full", "abc123"
        )
        assert result == "[abc123|https://github.com/org/repo/commit/abc123full]"

    def test_format_source_link_gitlab(self):
        listener = GitMetaData()
        listener.platform = "gitlab"
        result = listener._format_source_link(
            "https://gitlab.com/org/repo", "abc123", "robot/test.robot"
        )
        assert (
            result
            == "[robot/test.robot|https://gitlab.com/org/repo/-/blob/abc123/robot/test.robot]"
        )

    def test_format_source_link_github(self):
        listener = GitMetaData()
        listener.platform = "github"
        result = listener._format_source_link(
            "https://github.com/org/repo", "abc123", "robot/test.robot"
        )
        assert (
            result
            == "[robot/test.robot|https://github.com/org/repo/blob/abc123/robot/test.robot]"
        )
