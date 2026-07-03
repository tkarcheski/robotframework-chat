"""Tests for rfc.harness_snapshot — plugin and skill snapshots."""

import subprocess
from pathlib import Path

from rfc.harness_snapshot import (
    PLUGIN_ALLOWLIST,
    snapshot_plugins,
    snapshot_skills,
    should_include_plugin,
)

RECORDED_AT = "2026-06-11T00:00:00Z"


class TestShouldIncludePlugin:
    def test_robotframework_prefix_included(self):
        assert should_include_plugin("robotframework")
        assert should_include_plugin("robotframework-requests")

    def test_allowlist_included(self):
        for name in ("anthropic", "openai", "ollama"):
            assert name in PLUGIN_ALLOWLIST
            assert should_include_plugin(name)

    def test_other_packages_excluded(self):
        assert not should_include_plugin("requests")
        assert not should_include_plugin("pytest")

    def test_case_insensitive(self):
        assert should_include_plugin("RobotFramework")
        assert should_include_plugin("Anthropic")


class TestSnapshotPlugins:
    def test_returns_robotframework_rows(self):
        plugins = snapshot_plugins("sess-1", RECORDED_AT)
        names = [p.plugin_name for p in plugins]
        assert "robotframework" in names

    def test_rows_carry_session_and_metadata(self):
        plugins = snapshot_plugins("sess-1", RECORDED_AT)
        assert plugins, "expected at least one plugin row"
        for plugin in plugins:
            assert plugin.session_id == "sess-1"
            assert plugin.recorded_at == RECORDED_AT
            assert plugin.source == "pip"
            assert plugin.semver

    def test_no_excluded_packages(self):
        plugins = snapshot_plugins("sess-1", RECORDED_AT)
        names = {p.plugin_name for p in plugins}
        assert "requests" not in names
        assert "pyyaml" not in names


def _init_repo_with_resource(root: Path) -> None:
    """Create a git repo at ``root`` with one committed .resource file."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "root",
        ],
        cwd=root,
        check=True,
    )
    robot_dir = root / "robot" / "tier2" / "safety"
    robot_dir.mkdir(parents=True)
    (robot_dir / "safety.resource").write_text("*** Keywords ***\n")
    (root / "robot" / "untracked.resource").write_text("*** Keywords ***\n")
    subprocess.run(["git", "add", "robot/tier2/safety/safety.resource"], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "-m",
            "add resource",
        ],
        cwd=root,
        check=True,
    )


class TestSnapshotSkills:
    def test_tracked_resource_gets_git_sha(self, tmp_path):
        _init_repo_with_resource(tmp_path)
        skills = snapshot_skills("sess-1", RECORDED_AT, repo_root=str(tmp_path))
        by_path = {s.skill_path: s for s in skills}
        tracked = by_path["robot/tier2/safety/safety.resource"]
        assert tracked.session_id == "sess-1"
        assert tracked.recorded_at == RECORDED_AT
        assert tracked.skill_name == "safety"
        assert len(tracked.git_sha) == 40

    def test_untracked_resource_has_empty_sha(self, tmp_path):
        _init_repo_with_resource(tmp_path)
        skills = snapshot_skills("sess-1", RECORDED_AT, repo_root=str(tmp_path))
        by_path = {s.skill_path: s for s in skills}
        assert by_path["robot/untracked.resource"].git_sha == ""

    def test_missing_robot_dir_returns_empty(self, tmp_path):
        assert snapshot_skills("sess-1", RECORDED_AT, repo_root=str(tmp_path)) == []
