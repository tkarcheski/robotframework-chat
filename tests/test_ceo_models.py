"""Unit tests for CEO agent stage I/O dataclasses."""

import pytest

from rfc.ceo_models import (
    IdeaCandidate,
    BrainstormOutput,
    MarketAnalysis,
    MarketResearchOutput,
    IPFinding,
    IPAnalysisOutput,
    PatentStrategy,
    PatentStrategyOutput,
    LicensingPlan,
    LicensingStrategyOutput,
)


# ---------------------------------------------------------------------------
# IdeaCandidate
# ---------------------------------------------------------------------------


class TestIdeaCandidate:
    def test_valid_creation(self) -> None:
        idea = IdeaCandidate(
            name="Smart Planter",
            description="IoT-connected planter with soil sensors",
            category="consumer_electronics",
            novelty_notes="Combines moisture sensing with ML-based watering",
        )
        assert idea.name == "Smart Planter"
        assert idea.category == "consumer_electronics"

    def test_empty_name_raises(self) -> None:
        with pytest.raises(ValueError, match="name"):
            IdeaCandidate(
                name="",
                description="desc",
                category="cat",
                novelty_notes="notes",
            )

    def test_empty_description_raises(self) -> None:
        with pytest.raises(ValueError, match="description"):
            IdeaCandidate(
                name="X",
                description="",
                category="cat",
                novelty_notes="notes",
            )

    def test_to_dict(self) -> None:
        idea = IdeaCandidate(
            name="X",
            description="Y",
            category="Z",
            novelty_notes="W",
        )
        d = idea.to_dict()
        assert d == {
            "name": "X",
            "description": "Y",
            "category": "Z",
            "novelty_notes": "W",
        }

    def test_from_dict(self) -> None:
        d = {
            "name": "X",
            "description": "Y",
            "category": "Z",
            "novelty_notes": "W",
        }
        idea = IdeaCandidate.from_dict(d)
        assert idea.name == "X"
        assert idea.novelty_notes == "W"

    def test_from_dict_missing_field_raises(self) -> None:
        with pytest.raises(KeyError):
            IdeaCandidate.from_dict({"name": "X"})


# ---------------------------------------------------------------------------
# BrainstormOutput
# ---------------------------------------------------------------------------


class TestBrainstormOutput:
    def test_valid_creation(self) -> None:
        idea = IdeaCandidate(
            name="A", description="B", category="C", novelty_notes="D"
        )
        output = BrainstormOutput(ideas=[idea])
        assert len(output.ideas) == 1

    def test_empty_ideas_raises(self) -> None:
        with pytest.raises(ValueError, match="ideas"):
            BrainstormOutput(ideas=[])

    def test_to_dict(self) -> None:
        idea = IdeaCandidate(
            name="A", description="B", category="C", novelty_notes="D"
        )
        output = BrainstormOutput(ideas=[idea])
        d = output.to_dict()
        assert "ideas" in d
        assert len(d["ideas"]) == 1
        assert d["ideas"][0]["name"] == "A"

    def test_from_dict(self) -> None:
        d = {
            "ideas": [
                {
                    "name": "A",
                    "description": "B",
                    "category": "C",
                    "novelty_notes": "D",
                }
            ]
        }
        output = BrainstormOutput.from_dict(d)
        assert len(output.ideas) == 1
        assert output.ideas[0].name == "A"


# ---------------------------------------------------------------------------
# MarketAnalysis
# ---------------------------------------------------------------------------


class TestMarketAnalysis:
    def test_valid_creation(self) -> None:
        ma = MarketAnalysis(
            idea_name="Smart Planter",
            demand_score=0.8,
            market_size="$2.5B",
            competitors=["Gardena", "Rachio"],
            profitability="high",
        )
        assert ma.demand_score == 0.8

    def test_demand_score_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="demand_score"):
            MarketAnalysis(
                idea_name="X",
                demand_score=1.5,
                market_size="$1B",
                competitors=[],
                profitability="low",
            )

    def test_negative_demand_score_raises(self) -> None:
        with pytest.raises(ValueError, match="demand_score"):
            MarketAnalysis(
                idea_name="X",
                demand_score=-0.1,
                market_size="$1B",
                competitors=[],
                profitability="low",
            )

    def test_to_dict_roundtrip(self) -> None:
        ma = MarketAnalysis(
            idea_name="X",
            demand_score=0.5,
            market_size="$1B",
            competitors=["A"],
            profitability="medium",
        )
        d = ma.to_dict()
        restored = MarketAnalysis.from_dict(d)
        assert restored.idea_name == ma.idea_name
        assert restored.demand_score == ma.demand_score


# ---------------------------------------------------------------------------
# MarketResearchOutput
# ---------------------------------------------------------------------------


class TestMarketResearchOutput:
    def test_empty_analyses_raises(self) -> None:
        with pytest.raises(ValueError, match="analyses"):
            MarketResearchOutput(analyses=[])


# ---------------------------------------------------------------------------
# IPFinding
# ---------------------------------------------------------------------------


class TestIPFinding:
    def test_valid_creation(self) -> None:
        ipf = IPFinding(
            idea_name="Smart Planter",
            patentability_score=0.7,
            prior_art_gaps=["ML-based soil analysis"],
            claim_angles=["method of adaptive watering"],
        )
        assert ipf.patentability_score == 0.7

    def test_patentability_score_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="patentability_score"):
            IPFinding(
                idea_name="X",
                patentability_score=2.0,
                prior_art_gaps=[],
                claim_angles=[],
            )


# ---------------------------------------------------------------------------
# PatentStrategy
# ---------------------------------------------------------------------------


class TestPatentStrategy:
    def test_valid_creation(self) -> None:
        ps = PatentStrategy(
            idea_name="Smart Planter",
            claim_type="utility",
            abstract="A system for automated plant care...",
            key_claims=["A method comprising..."],
            filing_priority="high",
        )
        assert ps.claim_type == "utility"

    def test_invalid_claim_type_raises(self) -> None:
        with pytest.raises(ValueError, match="claim_type"):
            PatentStrategy(
                idea_name="X",
                claim_type="invalid",
                abstract="abc",
                key_claims=["claim"],
                filing_priority="high",
            )

    def test_empty_key_claims_raises(self) -> None:
        with pytest.raises(ValueError, match="key_claims"):
            PatentStrategy(
                idea_name="X",
                claim_type="utility",
                abstract="abc",
                key_claims=[],
                filing_priority="high",
            )


# ---------------------------------------------------------------------------
# LicensingPlan
# ---------------------------------------------------------------------------


class TestLicensingPlan:
    def test_valid_creation(self) -> None:
        lp = LicensingPlan(
            idea_name="Smart Planter",
            target_licensees=["Gardena", "Husqvarna"],
            pricing_model="royalty_per_unit",
            revenue_projection="$500K/yr",
            terms="5-year exclusive with 3% royalty",
        )
        assert lp.pricing_model == "royalty_per_unit"

    def test_empty_target_licensees_raises(self) -> None:
        with pytest.raises(ValueError, match="target_licensees"):
            LicensingPlan(
                idea_name="X",
                target_licensees=[],
                pricing_model="flat_fee",
                revenue_projection="$0",
                terms="none",
            )


# ---------------------------------------------------------------------------
# LicensingStrategyOutput
# ---------------------------------------------------------------------------


class TestLicensingStrategyOutput:
    def test_empty_plans_raises(self) -> None:
        with pytest.raises(ValueError, match="plans"):
            LicensingStrategyOutput(plans=[])

    def test_to_dict_roundtrip(self) -> None:
        lp = LicensingPlan(
            idea_name="X",
            target_licensees=["A"],
            pricing_model="flat_fee",
            revenue_projection="$1M",
            terms="standard",
        )
        output = LicensingStrategyOutput(plans=[lp])
        d = output.to_dict()
        restored = LicensingStrategyOutput.from_dict(d)
        assert len(restored.plans) == 1
        assert restored.plans[0].idea_name == "X"
