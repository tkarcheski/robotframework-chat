"""Tests for CEOKeywords lazy init, provider selection, and pipeline stages.

CEOKeywords must not require API keys at instantiation time so that
Robot Framework ``--dryrun`` can discover keywords without env vars.
The pipeline supports a CEO-specific provider override while preserving the
legacy OpenAI behavior for installs that still carry the repo default
``LLM_PROVIDER=ollama`` alongside ``OPENAI_API_KEY``.

Uses stub clients (no mock.patch for pipeline stages) to exercise every
code path without requiring real API keys or network access.
"""

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

from rfc.ceo_keywords import CEOKeywords, _DEFAULT_CEO_MAX_TOKENS
from rfc.multi_grader import MultiGrader
from rfc.web_cache import SearchResult, WebSearchCache


# ---------------------------------------------------------------------------
# Fixtures — valid JSON payloads that each stage's LLM response would return
# ---------------------------------------------------------------------------

_BRAINSTORM_JSON: Dict[str, Any] = {
    "ideas": [
        {
            "name": "Smart Planter",
            "description": "IoT planter with soil sensors",
            "category": "consumer_electronics",
            "novelty_notes": "ML-based watering",
        }
    ]
}

_MARKET_RESEARCH_JSON: Dict[str, Any] = {
    "analyses": [
        {
            "idea_name": "Smart Planter",
            "demand_score": 0.8,
            "market_size": "$2.5B",
            "competitors": ["Gardena"],
            "profitability": "high",
        }
    ]
}

_IP_ANALYSIS_JSON: Dict[str, Any] = {
    "findings": [
        {
            "idea_name": "Smart Planter",
            "patentability_score": 0.7,
            "prior_art_gaps": ["ML soil analysis"],
            "claim_angles": ["adaptive watering method"],
        }
    ]
}

_PATENT_STRATEGY_JSON: Dict[str, Any] = {
    "strategies": [
        {
            "idea_name": "Smart Planter",
            "claim_type": "utility",
            "abstract": "A system for automated plant care",
            "key_claims": ["A method comprising..."],
            "filing_priority": "high",
        }
    ]
}

_LICENSING_STRATEGY_JSON: Dict[str, Any] = {
    "plans": [
        {
            "idea_name": "Smart Planter",
            "target_licensees": ["Gardena"],
            "pricing_model": "royalty_per_unit",
            "revenue_projection": "$500K/yr",
            "terms": "5-year exclusive",
        }
    ]
}


# ---------------------------------------------------------------------------
# Stub client — replaces real LLM provider, no mock.patch needed
# ---------------------------------------------------------------------------


class StubClient:
    """Minimal LLM client stub that returns pre-configured JSON responses.

    Wraps the response in a markdown code block so that Grader._extract_json
    can reliably extract the JSON (the bare-JSON regex uses non-greedy
    matching and breaks with nested objects).
    """

    def __init__(self, response_dict: Dict[str, Any]) -> None:
        self._response = "```json\n" + json.dumps(response_dict) + "\n```"

    def generate(self, prompt: str) -> str:
        return self._response


class StubGraderClient:
    """Stub for grading — returns a valid score/reason JSON."""

    def generate(self, prompt: str) -> str:
        return json.dumps({"score": 1, "reason": "Good quality output"})


# ---------------------------------------------------------------------------
# Helper to build a CEOKeywords with a pre-set stub client
# ---------------------------------------------------------------------------


def _make_kw(response_dict: Dict[str, Any], tmp_path: Path) -> CEOKeywords:
    """Create a CEOKeywords with a stub client and tmp_path-based web cache."""
    kw = CEOKeywords(timeout=10)
    kw._client = StubClient(response_dict)
    kw.web_cache = WebSearchCache(db_path=str(tmp_path / "cache.db"))
    return kw


# ---------------------------------------------------------------------------
# Lazy initialisation
# ---------------------------------------------------------------------------


class TestCEOKeywordsLazyInit:
    """CEOKeywords should defer provider creation until first use."""

    def test_instantiation_without_provider_keys(self) -> None:
        """CEOKeywords() must succeed even without provider API keys set."""
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("OPENAI_API_KEY", None)
            kw = CEOKeywords()
            assert kw is not None

    def test_client_not_created_at_init(self) -> None:
        kw = CEOKeywords()
        assert kw._client is None

    def test_client_created_on_first_access(self) -> None:
        """The LLM client should be created lazily when first accessed."""
        with patch("rfc.ceo_keywords.create_provider") as mock_create:
            mock_create.return_value = object()  # dummy provider
            CEOKeywords()
            # create_provider should NOT have been called during __init__
            mock_create.assert_not_called()


class TestCEOProviderSelection:
    """CEO pipeline should support override + backward-compatible fallback."""

    def test_client_uses_ceo_provider_override(self) -> None:
        """CEO_LLM_PROVIDER should take precedence over the global provider."""
        env = {"CEO_LLM_PROVIDER": "openai", "LLM_PROVIDER": "ollama"}
        with (
            patch.dict("os.environ", env),
            patch("rfc.ceo_keywords.create_provider") as mock_create,
        ):
            mock_create.return_value = object()
            kw = CEOKeywords()
            _ = kw.client

            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs.get("provider") == "openai"

    def test_client_falls_back_to_openai_for_legacy_env(self) -> None:
        """An OpenAI key should preserve the old CEO default when LLM_PROVIDER stays at ollama."""
        env = {"LLM_PROVIDER": "ollama", "OPENAI_API_KEY": "sk-test-key"}
        with (
            patch.dict("os.environ", env, clear=False),
            patch("rfc.ceo_keywords.create_provider") as mock_create,
        ):
            mock_create.return_value = object()
            kw = CEOKeywords()
            _ = kw.client

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs.get("provider") == "openai"

    def test_client_keeps_non_default_global_provider(self) -> None:
        """A non-default LLM_PROVIDER should still drive the CEO pipeline."""
        env = {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-test-key"}
        with (
            patch.dict("os.environ", env, clear=False),
            patch("rfc.ceo_keywords.create_provider") as mock_create,
        ):
            mock_create.return_value = object()
            kw = CEOKeywords()
            _ = kw.client

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs.get("provider") == "openai"

    def test_client_allows_explicit_ollama_with_openai_key_present(self) -> None:
        """CEO_LLM_PROVIDER=ollama should disable the OpenAI compatibility fallback."""
        env = {
            "CEO_LLM_PROVIDER": "ollama",
            "LLM_PROVIDER": "ollama",
            "OPENAI_API_KEY": "sk-test-key",
        }
        with (
            patch.dict("os.environ", env, clear=False),
            patch("rfc.ceo_keywords.create_provider") as mock_create,
        ):
            mock_create.return_value = object()
            kw = CEOKeywords()
            _ = kw.client

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs.get("provider") == "ollama"

    def test_client_passes_max_tokens(self) -> None:
        """The client property must forward CEO_MAX_TOKENS (default 4096)."""
        with patch("rfc.ceo_keywords.create_provider") as mock_create:
            mock_create.return_value = object()
            kw = CEOKeywords()
            _ = kw.client

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs.get("max_tokens") == _DEFAULT_CEO_MAX_TOKENS

    def test_max_tokens_from_env(self) -> None:
        """CEO_MAX_TOKENS env var should override the default."""
        env = {"CEO_MAX_TOKENS": "2048"}
        with (
            patch.dict("os.environ", env),
            patch("rfc.ceo_keywords.create_provider") as mock_create,
        ):
            mock_create.return_value = object()
            kw = CEOKeywords()
            _ = kw.client

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs.get("max_tokens") == 2048

    def test_grader_uses_resolved_provider(self) -> None:
        """Grader providers should use the same resolved provider as the main client."""
        env = {
            "CEO_GRADER_MODELS": "model-a,model-b,model-c",
            "LLM_PROVIDER": "ollama",
            "OPENAI_API_KEY": "sk-test-key",
        }
        with (
            patch.dict("os.environ", env, clear=False),
            patch("rfc.ceo_keywords.create_provider") as mock_create,
        ):
            mock_create.return_value = object()
            kw = CEOKeywords()
            kw._get_multi_grader()

            assert mock_create.call_count == 3
            for call in mock_create.call_args_list:
                call_kwargs = call.kwargs
                assert call_kwargs.get("provider") == "openai"

    def test_grader_passes_max_tokens(self) -> None:
        """Grader providers must receive CEO_MAX_TOKENS."""
        env = {"CEO_GRADER_MODELS": "model-a,model-b,model-c"}
        with (
            patch.dict("os.environ", env),
            patch("rfc.ceo_keywords.create_provider") as mock_create,
        ):
            mock_create.return_value = object()
            kw = CEOKeywords()
            kw._get_multi_grader()

            for call in mock_create.call_args_list:
                call_kwargs = call.kwargs
                assert call_kwargs.get("max_tokens") == _DEFAULT_CEO_MAX_TOKENS


# ---------------------------------------------------------------------------
# _get_multi_grader (additional tests using monkeypatch)
# ---------------------------------------------------------------------------


class TestGetMultiGrader:
    def test_raises_when_env_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CEO_GRADER_MODELS", raising=False)
        kw = CEOKeywords()
        with pytest.raises(ValueError, match="CEO_GRADER_MODELS"):
            kw._get_multi_grader()

    def test_raises_when_fewer_than_3_models(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CEO_GRADER_MODELS", "a,b")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        kw = CEOKeywords()
        with pytest.raises(ValueError, match="at least 3"):
            kw._get_multi_grader()

    def test_creates_multi_grader_with_3_models(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CEO_GRADER_MODELS", "m1,m2,m3")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        kw = CEOKeywords()
        grader = kw._get_multi_grader()
        assert isinstance(grader, MultiGrader)
        assert len(grader.providers) == 3

    def test_caches_multi_grader(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CEO_GRADER_MODELS", "m1,m2,m3")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        kw = CEOKeywords()
        g1 = kw._get_multi_grader()
        g2 = kw._get_multi_grader()
        assert g1 is g2


# ---------------------------------------------------------------------------
# _extract_json_response
# ---------------------------------------------------------------------------


class TestExtractJsonResponse:
    def test_parses_valid_json(self, tmp_path: Path) -> None:
        kw = _make_kw(_BRAINSTORM_JSON, tmp_path)
        result = kw._extract_json_response('{"ideas": []}')
        assert result == {"ideas": []}


# ---------------------------------------------------------------------------
# Stage 1: brainstorm_ideas
# ---------------------------------------------------------------------------


class TestBrainstormIdeas:
    def test_returns_brainstorm_output(self, tmp_path: Path) -> None:
        kw = _make_kw(_BRAINSTORM_JSON, tmp_path)
        result = kw.brainstorm_ideas(domain="IoT")
        assert "ideas" in result
        assert result["ideas"][0]["name"] == "Smart Planter"

    def test_with_constraints(self, tmp_path: Path) -> None:
        kw = _make_kw(_BRAINSTORM_JSON, tmp_path)
        result = kw.brainstorm_ideas(domain="IoT", count=1, constraints="consumer")
        assert len(result["ideas"]) == 1

    def test_empty_constraints_treated_as_none(self, tmp_path: Path) -> None:
        kw = _make_kw(_BRAINSTORM_JSON, tmp_path)
        result = kw.brainstorm_ideas(domain="IoT", constraints="")
        assert "ideas" in result


# ---------------------------------------------------------------------------
# Stage 2: research_market
# ---------------------------------------------------------------------------


class TestResearchMarket:
    def test_with_brainstorm_output_dict(self, tmp_path: Path) -> None:
        kw = _make_kw(_MARKET_RESEARCH_JSON, tmp_path)
        result = kw.research_market(ideas=_BRAINSTORM_JSON)
        assert "analyses" in result

    def test_with_list_input(self, tmp_path: Path) -> None:
        kw = _make_kw(_MARKET_RESEARCH_JSON, tmp_path)
        result = kw.research_market(ideas=[{"name": "X"}])
        assert "analyses" in result

    def test_with_single_item_input(self, tmp_path: Path) -> None:
        kw = _make_kw(_MARKET_RESEARCH_JSON, tmp_path)
        result = kw.research_market(ideas="single_idea_string")
        assert "analyses" in result

    def test_with_web_queries(self, tmp_path: Path) -> None:
        kw = _make_kw(_MARKET_RESEARCH_JSON, tmp_path)
        # Pre-populate cache so web_queries hit
        kw.web_cache.put(
            "iot market",
            [SearchResult(title="IoT Market", url="https://x.com", snippet="Growing")],
        )
        result = kw.research_market(ideas=_BRAINSTORM_JSON, web_queries=["iot market"])
        assert "analyses" in result

    def test_with_web_queries_no_results(self, tmp_path: Path) -> None:
        kw = _make_kw(_MARKET_RESEARCH_JSON, tmp_path)
        # No cache entries → empty results → web_context stays None
        result = kw.research_market(
            ideas=_BRAINSTORM_JSON, web_queries=["nonexistent query"]
        )
        assert "analyses" in result


# ---------------------------------------------------------------------------
# Stage 3: analyze_ip_landscape
# ---------------------------------------------------------------------------


class TestAnalyzeIPLandscape:
    def test_with_market_research_dict(self, tmp_path: Path) -> None:
        kw = _make_kw(_IP_ANALYSIS_JSON, tmp_path)
        result = kw.analyze_ip_landscape(market_analyses=_MARKET_RESEARCH_JSON)
        assert "findings" in result

    def test_with_list_input(self, tmp_path: Path) -> None:
        kw = _make_kw(_IP_ANALYSIS_JSON, tmp_path)
        result = kw.analyze_ip_landscape(market_analyses=[{"idea_name": "X"}])
        assert "findings" in result

    def test_with_single_item_input(self, tmp_path: Path) -> None:
        kw = _make_kw(_IP_ANALYSIS_JSON, tmp_path)
        result = kw.analyze_ip_landscape(market_analyses="single")
        assert "findings" in result

    def test_with_web_queries(self, tmp_path: Path) -> None:
        kw = _make_kw(_IP_ANALYSIS_JSON, tmp_path)
        kw.web_cache.put(
            "patent search",
            [SearchResult(title="Patents", url="https://p.com", snippet="Prior art")],
        )
        result = kw.analyze_ip_landscape(
            market_analyses=_MARKET_RESEARCH_JSON, web_queries=["patent search"]
        )
        assert "findings" in result


# ---------------------------------------------------------------------------
# Stage 4: develop_patent_strategy
# ---------------------------------------------------------------------------


class TestDevelopPatentStrategy:
    def test_with_ip_analysis_dict(self, tmp_path: Path) -> None:
        kw = _make_kw(_PATENT_STRATEGY_JSON, tmp_path)
        result = kw.develop_patent_strategy(ip_findings=_IP_ANALYSIS_JSON)
        assert "strategies" in result

    def test_with_list_input(self, tmp_path: Path) -> None:
        kw = _make_kw(_PATENT_STRATEGY_JSON, tmp_path)
        result = kw.develop_patent_strategy(ip_findings=[{"idea_name": "X"}])
        assert "strategies" in result

    def test_with_single_item_input(self, tmp_path: Path) -> None:
        kw = _make_kw(_PATENT_STRATEGY_JSON, tmp_path)
        result = kw.develop_patent_strategy(ip_findings="single")
        assert "strategies" in result


# ---------------------------------------------------------------------------
# Stage 5: plan_licensing_strategy
# ---------------------------------------------------------------------------


class TestPlanLicensingStrategy:
    def test_with_patent_strategy_dict(self, tmp_path: Path) -> None:
        kw = _make_kw(_LICENSING_STRATEGY_JSON, tmp_path)
        result = kw.plan_licensing_strategy(patent_strategies=_PATENT_STRATEGY_JSON)
        assert "plans" in result

    def test_with_list_input(self, tmp_path: Path) -> None:
        kw = _make_kw(_LICENSING_STRATEGY_JSON, tmp_path)
        result = kw.plan_licensing_strategy(patent_strategies=[{"idea_name": "X"}])
        assert "plans" in result

    def test_with_single_item_input(self, tmp_path: Path) -> None:
        kw = _make_kw(_LICENSING_STRATEGY_JSON, tmp_path)
        result = kw.plan_licensing_strategy(patent_strategies="single")
        assert "plans" in result


# ---------------------------------------------------------------------------
# validate_stage_structure
# ---------------------------------------------------------------------------


class TestValidateStageStructure:
    def test_valid_brainstorm(self, tmp_path: Path) -> None:
        kw = _make_kw(_BRAINSTORM_JSON, tmp_path)
        assert kw.validate_stage_structure("brainstorm", _BRAINSTORM_JSON) is True

    def test_valid_market_research(self, tmp_path: Path) -> None:
        kw = _make_kw(_BRAINSTORM_JSON, tmp_path)
        assert (
            kw.validate_stage_structure("market_research", _MARKET_RESEARCH_JSON)
            is True
        )

    def test_valid_ip_analysis(self, tmp_path: Path) -> None:
        kw = _make_kw(_BRAINSTORM_JSON, tmp_path)
        assert kw.validate_stage_structure("ip_analysis", _IP_ANALYSIS_JSON) is True

    def test_valid_patent_strategy(self, tmp_path: Path) -> None:
        kw = _make_kw(_BRAINSTORM_JSON, tmp_path)
        assert (
            kw.validate_stage_structure("patent_strategy", _PATENT_STRATEGY_JSON)
            is True
        )

    def test_valid_licensing_strategy(self, tmp_path: Path) -> None:
        kw = _make_kw(_BRAINSTORM_JSON, tmp_path)
        assert (
            kw.validate_stage_structure("licensing_strategy", _LICENSING_STRATEGY_JSON)
            is True
        )

    def test_unknown_stage_raises(self, tmp_path: Path) -> None:
        kw = _make_kw(_BRAINSTORM_JSON, tmp_path)
        with pytest.raises(ValueError, match="Unknown stage"):
            kw.validate_stage_structure("nonexistent", {})


# ---------------------------------------------------------------------------
# grade_stage_output
# ---------------------------------------------------------------------------


class TestGradeStageOutput:
    def test_returns_grade_dict(self, tmp_path: Path) -> None:
        kw = _make_kw(_BRAINSTORM_JSON, tmp_path)
        # Inject a multi_grader with stub providers
        grader = MultiGrader(providers=[StubGraderClient() for _ in range(3)])
        kw._multi_grader = grader

        result = kw.grade_stage_output("brainstorm", _BRAINSTORM_JSON)
        assert "scores" in result
        assert "majority_score" in result
        assert "agreement_ratio" in result
        assert "passed" in result
        assert "unanimous" in result

    def test_disagreement_logged(self, tmp_path: Path) -> None:
        """Non-unanimous results should still return successfully."""
        kw = _make_kw(_BRAINSTORM_JSON, tmp_path)

        # Create a grader where one provider disagrees
        class DisagreeClient:
            def generate(self, prompt: str) -> str:
                return json.dumps({"score": 0, "reason": "Poor quality"})

        grader = MultiGrader(
            providers=[StubGraderClient(), StubGraderClient(), DisagreeClient()]
        )
        kw._multi_grader = grader

        result = kw.grade_stage_output("brainstorm", _BRAINSTORM_JSON)
        assert result["unanimous"] is False
        assert result["majority_score"] == 1


# ---------------------------------------------------------------------------
# warm_web_cache / clear_web_cache
# ---------------------------------------------------------------------------


class TestWebCacheKeywords:
    def test_warm_web_cache(self, tmp_path: Path) -> None:
        kw = _make_kw(_BRAINSTORM_JSON, tmp_path)
        entries = {
            "iot market": [
                {"title": "IoT Report", "url": "https://x.com", "snippet": "Growing"}
            ]
        }
        kw.warm_web_cache(entries)
        cached = kw.web_cache.get("iot market")
        assert cached is not None
        assert len(cached) == 1
        assert cached[0].title == "IoT Report"

    def test_clear_web_cache(self, tmp_path: Path) -> None:
        kw = _make_kw(_BRAINSTORM_JSON, tmp_path)
        kw.web_cache.put(
            "test",
            [SearchResult(title="T", url="u", snippet="s")],
        )
        kw.clear_web_cache()
        assert kw.web_cache.get("test") is None
