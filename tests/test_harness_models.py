"""Tests for harness dataclasses (CLAUDE.md: no Optional fields)."""

from rfc.harness_models import (
    METRIC_CACHE_HIT_RATE,
    METRIC_CHURN_RATIO,
    METRIC_GRADER_SCORE,
    METRIC_LATENCY_MS,
    METRIC_PROCESS_VIOLATIONS,
    METRIC_SUITE_RUNTIME_MS,
    METRIC_TASK_SUCCESS,
    METRIC_TOKENS_IN,
    METRIC_TOKENS_OUT,
    RESERVED_METRIC_KEYS,
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
        assert h.scenario_id == ""
        assert h.battery_run_id == ""

    def test_spine_grouping_columns_accept_values(self) -> None:
        h = AgenticHarness(
            session_id="abc123",
            tool_name="opencode",
            started_at="2026-05-09T00:00:00Z",
            scenario_id="tier4_bug_fix",
            battery_run_id="battery-42",
        )
        assert h.scenario_id == "tier4_bug_fix"
        assert h.battery_run_id == "battery-42"


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
            skill_path="robot/20__tier2/safety/safety.resource",
            recorded_at="2026-05-09T00:00:00Z",
        )
        assert s.session_id == "abc123"
        assert s.skill_path == "robot/20__tier2/safety/safety.resource"

    def test_default_fields(self) -> None:
        s = AgenticSkill(
            session_id="abc123",
            skill_path="robot/20__tier2/safety/safety.resource",
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


class TestReservedMetricKeys:
    """RFC-007 section 6.1 reserved agentic_metrics.metric_key vocabulary."""

    def test_new_keys_have_expected_spelling(self) -> None:
        # The scoreboard (S5) and writers must agree on these exact strings.
        assert METRIC_TASK_SUCCESS == "task_success"
        assert METRIC_CHURN_RATIO == "churn_ratio"
        assert METRIC_PROCESS_VIOLATIONS == "process_violations"

    def test_preexisting_keys_named_for_completeness(self) -> None:
        assert METRIC_TOKENS_IN == "tokens_in"
        assert METRIC_TOKENS_OUT == "tokens_out"
        assert METRIC_LATENCY_MS == "latency_ms"
        assert METRIC_GRADER_SCORE == "grader_score"

    def test_efficiency_keys_have_expected_spelling(self) -> None:
        # RFC-010 slice S1 (#258): writer, view, and drift-guard must agree.
        assert METRIC_CACHE_HIT_RATE == "cache_hit_rate"
        assert METRIC_SUITE_RUNTIME_MS == "suite_runtime_ms"

    def test_reserved_set_is_the_nine_keys_in_order(self) -> None:
        assert RESERVED_METRIC_KEYS == (
            "task_success",
            "churn_ratio",
            "process_violations",
            "tokens_in",
            "tokens_out",
            "latency_ms",
            "grader_score",
            "cache_hit_rate",
            "suite_runtime_ms",
        )

    def test_reserved_keys_are_unique(self) -> None:
        assert len(set(RESERVED_METRIC_KEYS)) == len(RESERVED_METRIC_KEYS)
