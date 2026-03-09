"""Unit tests for CEO agent prompt templates."""

import pytest

from rfc.ceo_prompts import (
    build_brainstorm_prompt,
    build_market_research_prompt,
    build_ip_analysis_prompt,
    build_patent_strategy_prompt,
    build_licensing_strategy_prompt,
)


class TestBrainstormPrompt:
    def test_includes_domain(self) -> None:
        prompt = build_brainstorm_prompt(domain="smart agriculture")
        assert "smart agriculture" in prompt

    def test_includes_json_instruction(self) -> None:
        prompt = build_brainstorm_prompt(domain="robotics")
        assert "JSON" in prompt

    def test_includes_required_fields(self) -> None:
        prompt = build_brainstorm_prompt(domain="robotics")
        for field in ("name", "description", "category", "novelty_notes"):
            assert field in prompt

    def test_includes_count(self) -> None:
        prompt = build_brainstorm_prompt(domain="robotics", count=5)
        assert "5" in prompt

    def test_empty_domain_raises(self) -> None:
        with pytest.raises(ValueError, match="domain"):
            build_brainstorm_prompt(domain="")


class TestMarketResearchPrompt:
    def test_includes_ideas(self) -> None:
        ideas = [{"name": "Widget X", "description": "A smart widget"}]
        prompt = build_market_research_prompt(ideas=ideas)
        assert "Widget X" in prompt

    def test_includes_web_context(self) -> None:
        ideas = [{"name": "Y", "description": "Z"}]
        prompt = build_market_research_prompt(
            ideas=ideas,
            web_context="Market size for IoT sensors is $5B globally.",
        )
        assert "$5B" in prompt

    def test_includes_required_fields(self) -> None:
        ideas = [{"name": "Y", "description": "Z"}]
        prompt = build_market_research_prompt(ideas=ideas)
        for field in ("demand_score", "market_size", "competitors", "profitability"):
            assert field in prompt

    def test_empty_ideas_raises(self) -> None:
        with pytest.raises(ValueError, match="ideas"):
            build_market_research_prompt(ideas=[])


class TestIPAnalysisPrompt:
    def test_includes_market_data(self) -> None:
        analyses = [{"idea_name": "Widget X", "demand_score": 0.8}]
        prompt = build_ip_analysis_prompt(market_analyses=analyses)
        assert "Widget X" in prompt

    def test_includes_web_context(self) -> None:
        analyses = [{"idea_name": "Y", "demand_score": 0.5}]
        prompt = build_ip_analysis_prompt(
            market_analyses=analyses,
            web_context="US Patent 9,876,543 covers soil sensors.",
        )
        assert "9,876,543" in prompt

    def test_includes_required_fields(self) -> None:
        analyses = [{"idea_name": "Y", "demand_score": 0.5}]
        prompt = build_ip_analysis_prompt(market_analyses=analyses)
        for field in (
            "patentability_score",
            "prior_art_gaps",
            "claim_angles",
        ):
            assert field in prompt


class TestPatentStrategyPrompt:
    def test_includes_ip_findings(self) -> None:
        findings = [{"idea_name": "Widget X", "patentability_score": 0.9}]
        prompt = build_patent_strategy_prompt(ip_findings=findings)
        assert "Widget X" in prompt

    def test_includes_required_fields(self) -> None:
        findings = [{"idea_name": "Y", "patentability_score": 0.7}]
        prompt = build_patent_strategy_prompt(ip_findings=findings)
        for field in ("claim_type", "abstract", "key_claims", "filing_priority"):
            assert field in prompt

    def test_includes_valid_claim_types(self) -> None:
        findings = [{"idea_name": "Y", "patentability_score": 0.7}]
        prompt = build_patent_strategy_prompt(ip_findings=findings)
        assert "utility" in prompt
        assert "design" in prompt
        assert "provisional" in prompt


class TestLicensingStrategyPrompt:
    def test_includes_patent_strategies(self) -> None:
        strategies = [{"idea_name": "Widget X", "claim_type": "utility"}]
        prompt = build_licensing_strategy_prompt(patent_strategies=strategies)
        assert "Widget X" in prompt

    def test_includes_required_fields(self) -> None:
        strategies = [{"idea_name": "Y", "claim_type": "utility"}]
        prompt = build_licensing_strategy_prompt(patent_strategies=strategies)
        for field in (
            "target_licensees",
            "pricing_model",
            "revenue_projection",
            "terms",
        ):
            assert field in prompt
