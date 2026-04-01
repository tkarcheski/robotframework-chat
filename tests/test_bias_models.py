"""Tests for rfc.bias_models."""

import pytest

from rfc.bias_models import BiasResult, DemographicScenario


class TestBiasResult:
    def test_valid_result(self):
        result = BiasResult(
            parity_score=0.85,
            flagged_responses=["group_a"],
            pairwise_scores={"a vs b": 0.85},
            reason="ok",
        )
        assert result.parity_score == 0.85

    def test_score_coerced_from_int(self):
        result = BiasResult(
            parity_score=1,
            flagged_responses=[],
            pairwise_scores={},
            reason="perfect",
        )
        assert isinstance(result.parity_score, float)

    def test_score_below_zero_rejected(self):
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            BiasResult(
                parity_score=-0.1,
                flagged_responses=[],
                pairwise_scores={},
                reason="bad",
            )

    def test_score_above_one_rejected(self):
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            BiasResult(
                parity_score=1.1,
                flagged_responses=[],
                pairwise_scores={},
                reason="bad",
            )

    def test_invalid_score_type(self):
        with pytest.raises(TypeError, match="parity_score must be a float"):
            BiasResult(
                parity_score="high",
                flagged_responses=[],
                pairwise_scores={},
                reason="bad",
            )

    def test_invalid_flagged_type(self):
        with pytest.raises(TypeError, match="flagged_responses must be a list"):
            BiasResult(
                parity_score=0.5,
                flagged_responses="not a list",
                pairwise_scores={},
                reason="bad",
            )

    def test_invalid_pairwise_type(self):
        with pytest.raises(TypeError, match="pairwise_scores must be a dict"):
            BiasResult(
                parity_score=0.5,
                flagged_responses=[],
                pairwise_scores="not a dict",
                reason="bad",
            )

    def test_invalid_reason_type(self):
        with pytest.raises(TypeError, match="reason must be a str"):
            BiasResult(
                parity_score=0.5,
                flagged_responses=[],
                pairwise_scores={},
                reason=123,
            )

    def test_default_details(self):
        result = BiasResult(
            parity_score=0.5,
            flagged_responses=[],
            pairwise_scores={},
            reason="ok",
        )
        assert result.details == {}


class TestDemographicScenario:
    def test_valid_scenario(self):
        scenario = DemographicScenario(
            id="test_1",
            template="Should {name} be hired?",
            markers={
                "group_a": {"name": "James"},
                "group_b": {"name": "Maria"},
            },
            category="hiring",
        )
        assert scenario.parity_threshold == 0.8

    def test_render_prompt(self):
        scenario = DemographicScenario(
            id="test_1",
            template="Advise {name} from {location}.",
            markers={
                "a": {"name": "James", "location": "NYC"},
                "b": {"name": "Maria", "location": "LA"},
            },
            category="financial",
        )
        assert scenario.render_prompt("a") == "Advise James from NYC."
        assert scenario.render_prompt("b") == "Advise Maria from LA."

    def test_render_unknown_label_raises(self):
        scenario = DemographicScenario(
            id="test_1",
            template="Hello {name}",
            markers={"a": {"name": "A"}, "b": {"name": "B"}},
            category="test",
        )
        with pytest.raises(KeyError):
            scenario.render_prompt("unknown")

    def test_empty_id_rejected(self):
        with pytest.raises(ValueError, match="non-empty"):
            DemographicScenario(
                id="",
                template="test",
                markers={"a": {"name": "A"}, "b": {"name": "B"}},
                category="test",
            )

    def test_empty_template_rejected(self):
        with pytest.raises(ValueError, match="non-empty"):
            DemographicScenario(
                id="test",
                template="",
                markers={"a": {"name": "A"}, "b": {"name": "B"}},
                category="test",
            )

    def test_fewer_than_two_markers_rejected(self):
        with pytest.raises(ValueError, match="at least 2"):
            DemographicScenario(
                id="test",
                template="test",
                markers={"a": {"name": "A"}},
                category="test",
            )

    def test_invalid_threshold_rejected(self):
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            DemographicScenario(
                id="test",
                template="test",
                markers={"a": {"name": "A"}, "b": {"name": "B"}},
                category="test",
                parity_threshold=1.5,
            )
