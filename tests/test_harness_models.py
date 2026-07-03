"""Tests for harness dataclasses (CLAUDE.md: no Optional fields)."""

from rfc.harness_models import (
    AgenticHarness,
    AgenticMetric,
    AgenticPlugin,
    AgenticSkill,
)


class TestAgenticHarness:
    def test_required_fields(self) -> None:
        h = AgenticHarness(
            session_id="abc123",
            tool_name="claude-code",
            started_at="2026-05-09T00:00:00Z",
        )
        assert h.session_id == "abc123"
        assert h.tool_name == "claude-code"
        assert h.started_at == "2026-05-09T00:00:00Z"

    def test_default_fields_are_concrete_not_none(self) -> None:
        h = AgenticHarness(
            session_id="abc123",
            tool_name="claude-code",
            started_at="2026-05-09T00:00:00Z",
        )
        assert h.tool_version == ""
        assert h.model_id == ""
        assert h.rfc_version == ""
        assert h.branch == ""
        assert h.ended_at == ""
        assert h.outcome == ""
        assert h.replay_of_recording_id == ""


class TestAgenticPlugin:
    def test_required_fields(self) -> None:
        p = AgenticPlugin(
            session_id="abc123",
            plugin_name="robotframework-browser",
            recorded_at="2026-05-09T00:00:00Z",
        )
        assert p.session_id == "abc123"
        assert p.plugin_name == "robotframework-browser"
        assert p.recorded_at == "2026-05-09T00:00:00Z"

    def test_default_fields(self) -> None:
        p = AgenticPlugin(
            session_id="abc123",
            plugin_name="robotframework-browser",
            recorded_at="2026-05-09T00:00:00Z",
        )
        assert p.semver == ""
        assert p.source == ""
        assert p.id == ""


class TestAgenticSkill:
    def test_required_fields(self) -> None:
        s = AgenticSkill(
            session_id="abc123",
            skill_path="robot/tier2/safety/safety.resource",
            recorded_at="2026-05-09T00:00:00Z",
        )
        assert s.session_id == "abc123"
        assert s.skill_path == "robot/tier2/safety/safety.resource"

    def test_default_fields(self) -> None:
        s = AgenticSkill(
            session_id="abc123",
            skill_path="robot/tier2/safety/safety.resource",
            recorded_at="2026-05-09T00:00:00Z",
        )
        assert s.git_sha == ""
        assert s.skill_name == ""
        assert s.id == ""


class TestAgenticMetric:
    def test_required_fields(self) -> None:
        m = AgenticMetric(
            session_id="abc123",
            metric_key="tokens_in",
            recorded_at="2026-05-09T00:00:00Z",
        )
        assert m.session_id == "abc123"
        assert m.metric_key == "tokens_in"

    def test_sentinel_defaults_match_test_database_convention(self) -> None:
        m = AgenticMetric(
            session_id="abc123",
            metric_key="tokens_in",
            recorded_at="2026-05-09T00:00:00Z",
        )
        # -1 sentinel matches src/rfc/test_database.py TestRun.id convention.
        assert m.test_run_id == -1
        assert m.test_result_id == -1
        assert m.metric_value == 0.0
        assert m.id == ""
