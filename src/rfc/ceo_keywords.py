"""Robot Framework keywords for the CEO agent pipeline.

Exposes each pipeline stage as a Robot keyword, plus structural validation
and multi-LLM grading keywords.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from robot.api import logger
from robot.api.deco import keyword

from .ceo_models import (
    BrainstormOutput,
    IPAnalysisOutput,
    LicensingStrategyOutput,
    MarketResearchOutput,
    PatentStrategyOutput,
)
from .ceo_prompts import (
    build_brainstorm_prompt,
    build_ip_analysis_prompt,
    build_licensing_strategy_prompt,
    build_market_research_prompt,
    build_patent_strategy_prompt,
)
from .grader import Grader
from .llm_client import create_provider
from .multi_grader import MultiGrader
from .web_cache import SearchResult, WebSearchCache

_DEFAULT_TIMEOUT = 5400
_DEFAULT_CEO_MAX_TOKENS = 4096
_DEFAULT_LLM_PROVIDER = "ollama"
_COMPAT_OPENAI_PROVIDER = "openai"


class CEOKeywords:
    """Robot Framework keywords for CEO agent agentic workflow testing."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_retries: int = 2,
    ) -> None:
        if timeout is None:
            timeout = int(os.getenv("OLLAMA_TIMEOUT", str(_DEFAULT_TIMEOUT)))
        self._timeout = int(timeout)
        self._max_retries = int(max_retries)
        self._client: Optional[Any] = None
        self.web_cache = WebSearchCache()
        self._multi_grader: Optional[MultiGrader] = None

    def _resolve_ceo_provider(self) -> str:
        """Resolve the provider for CEO stages with backward-compatible fallback.

        Precedence:
        1. ``CEO_LLM_PROVIDER`` when explicitly set.
        2. ``LLM_PROVIDER`` when it is set to a non-default value.
        3. ``openai`` when an OpenAI key is present and the global provider is
           still the repo default ``ollama``.
        4. The global/default provider resolution from ``create_provider``.
        """
        ceo_provider = os.getenv("CEO_LLM_PROVIDER", "").strip().lower()
        if ceo_provider:
            return ceo_provider

        llm_provider = os.getenv("LLM_PROVIDER", _DEFAULT_LLM_PROVIDER).strip().lower()
        if llm_provider != _DEFAULT_LLM_PROVIDER:
            return llm_provider

        if os.getenv("OPENAI_API_KEY", "").strip():
            return _COMPAT_OPENAI_PROVIDER

        return llm_provider

    @property
    def client(self) -> Any:
        """Lazily create the LLM provider on first access.

        This allows Robot Framework ``--dryrun`` to instantiate the library
        and discover keywords without requiring API keys.
        """
        if self._client is None:
            max_tokens = int(os.getenv("CEO_MAX_TOKENS", str(_DEFAULT_CEO_MAX_TOKENS)))
            self._client = create_provider(
                provider=self._resolve_ceo_provider(),
                timeout=self._timeout,
                max_retries=self._max_retries,
                max_tokens=max_tokens,
            )
        return self._client

    def _get_multi_grader(self) -> MultiGrader:
        """Lazily initialize the multi-grader with configured models."""
        if self._multi_grader is not None:
            return self._multi_grader

        models_str = os.getenv("CEO_GRADER_MODELS", "")
        if not models_str:
            raise ValueError(
                "CEO_GRADER_MODELS env var must be set with 3+ comma-separated "
                "model names (e.g. 'qwen2:latest,phi3:latest,gemma2:latest')"
            )

        models = [m.strip() for m in models_str.split(",") if m.strip()]
        if len(models) < 3:
            raise ValueError(
                f"CEO_GRADER_MODELS must contain at least 3 models, got {len(models)}"
            )

        max_tokens = int(os.getenv("CEO_MAX_TOKENS", str(_DEFAULT_CEO_MAX_TOKENS)))
        provider_name = self._resolve_ceo_provider()
        providers = []
        for model in models:
            provider = create_provider(
                provider=provider_name,
                model=model,
                max_tokens=max_tokens,
            )
            providers.append(provider)

        self._multi_grader = MultiGrader(providers=providers)
        return self._multi_grader

    def _extract_json_response(self, raw: str) -> Dict[str, Any]:
        """Extract and parse JSON from LLM response."""
        extractor = Grader(self.client)
        json_text = extractor._extract_json(raw)
        return json.loads(json_text)

    # ------------------------------------------------------------------
    # Stage 1: Brainstorming
    # ------------------------------------------------------------------

    @keyword("Brainstorm Ideas")
    def brainstorm_ideas(
        self,
        domain: str,
        count: int = 3,
        constraints: str = "",
    ) -> Dict[str, Any]:
        """Generate product/service ideas in a domain.

        Args:
            domain: The market domain to brainstorm in.
            count: Number of ideas to generate.
            constraints: Optional focus areas or constraints.

        Returns:
            Dict representation of BrainstormOutput.
        """
        logger.info(f"Brainstorming {count} ideas in domain: {domain}")
        prompt = build_brainstorm_prompt(
            domain=domain,
            count=int(count),
            constraints=constraints or None,
        )
        raw = self.client.generate(prompt)
        logger.info(f"RFC_DATA:brainstorm_raw:{raw}")

        parsed = self._extract_json_response(raw)
        output = BrainstormOutput.from_dict(parsed)
        result = output.to_dict()
        logger.info(f"RFC_DATA:brainstorm_output:{json.dumps(result)}")
        return result

    # ------------------------------------------------------------------
    # Stage 2: Market Research
    # ------------------------------------------------------------------

    @keyword("Research Market")
    def research_market(
        self,
        ideas: Any,
        web_queries: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Evaluate market viability of product ideas.

        Args:
            ideas: List of idea dicts or BrainstormOutput dict.
            web_queries: Optional queries to search for market context.

        Returns:
            Dict representation of MarketResearchOutput.
        """
        if isinstance(ideas, dict) and "ideas" in ideas:
            idea_list = ideas["ideas"]
        elif isinstance(ideas, list):
            idea_list = ideas
        else:
            idea_list = [ideas]

        logger.info(f"Researching market for {len(idea_list)} ideas")

        web_context = None
        if web_queries:
            all_results: List[SearchResult] = []
            for q in web_queries:
                all_results.extend(self.web_cache.search(q))
            if all_results:
                web_context = self.web_cache.format_as_context(all_results)

        prompt = build_market_research_prompt(ideas=idea_list, web_context=web_context)
        raw = self.client.generate(prompt)
        logger.info(f"RFC_DATA:market_research_raw:{raw}")

        parsed = self._extract_json_response(raw)
        output = MarketResearchOutput.from_dict(parsed)
        result = output.to_dict()
        logger.info(f"RFC_DATA:market_research_output:{json.dumps(result)}")
        return result

    # ------------------------------------------------------------------
    # Stage 3: IP Analysis
    # ------------------------------------------------------------------

    @keyword("Analyze IP Landscape")
    def analyze_ip_landscape(
        self,
        market_analyses: Any,
        web_queries: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Analyze IP landscape for market-validated ideas.

        Args:
            market_analyses: List of analysis dicts or MarketResearchOutput dict.
            web_queries: Optional queries to search for patent/IP context.

        Returns:
            Dict representation of IPAnalysisOutput.
        """
        if isinstance(market_analyses, dict) and "analyses" in market_analyses:
            analyses_list = market_analyses["analyses"]
        elif isinstance(market_analyses, list):
            analyses_list = market_analyses
        else:
            analyses_list = [market_analyses]

        logger.info(f"Analyzing IP landscape for {len(analyses_list)} ideas")

        web_context = None
        if web_queries:
            all_results: List[SearchResult] = []
            for q in web_queries:
                all_results.extend(self.web_cache.search(q))
            if all_results:
                web_context = self.web_cache.format_as_context(all_results)

        prompt = build_ip_analysis_prompt(
            market_analyses=analyses_list, web_context=web_context
        )
        raw = self.client.generate(prompt)
        logger.info(f"RFC_DATA:ip_analysis_raw:{raw}")

        parsed = self._extract_json_response(raw)
        output = IPAnalysisOutput.from_dict(parsed)
        result = output.to_dict()
        logger.info(f"RFC_DATA:ip_analysis_output:{json.dumps(result)}")
        return result

    # ------------------------------------------------------------------
    # Stage 4: Patent Strategy
    # ------------------------------------------------------------------

    @keyword("Develop Patent Strategy")
    def develop_patent_strategy(
        self,
        ip_findings: Any,
    ) -> Dict[str, Any]:
        """Develop patent filing strategies for IP findings.

        Args:
            ip_findings: List of IP finding dicts or IPAnalysisOutput dict.

        Returns:
            Dict representation of PatentStrategyOutput.
        """
        if isinstance(ip_findings, dict) and "findings" in ip_findings:
            findings_list = ip_findings["findings"]
        elif isinstance(ip_findings, list):
            findings_list = ip_findings
        else:
            findings_list = [ip_findings]

        logger.info(f"Developing patent strategy for {len(findings_list)} findings")

        prompt = build_patent_strategy_prompt(ip_findings=findings_list)
        raw = self.client.generate(prompt)
        logger.info(f"RFC_DATA:patent_strategy_raw:{raw}")

        parsed = self._extract_json_response(raw)
        output = PatentStrategyOutput.from_dict(parsed)
        result = output.to_dict()
        logger.info(f"RFC_DATA:patent_strategy_output:{json.dumps(result)}")
        return result

    # ------------------------------------------------------------------
    # Stage 5: Licensing Strategy
    # ------------------------------------------------------------------

    @keyword("Plan Licensing Strategy")
    def plan_licensing_strategy(
        self,
        patent_strategies: Any,
    ) -> Dict[str, Any]:
        """Develop licensing strategies for patented IP.

        Args:
            patent_strategies: List of strategy dicts or PatentStrategyOutput dict.

        Returns:
            Dict representation of LicensingStrategyOutput.
        """
        if isinstance(patent_strategies, dict) and "strategies" in patent_strategies:
            strategies_list = patent_strategies["strategies"]
        elif isinstance(patent_strategies, list):
            strategies_list = patent_strategies
        else:
            strategies_list = [patent_strategies]

        logger.info(f"Planning licensing strategy for {len(strategies_list)} patents")

        prompt = build_licensing_strategy_prompt(patent_strategies=strategies_list)
        raw = self.client.generate(prompt)
        logger.info(f"RFC_DATA:licensing_strategy_raw:{raw}")

        parsed = self._extract_json_response(raw)
        output = LicensingStrategyOutput.from_dict(parsed)
        result = output.to_dict()
        logger.info(f"RFC_DATA:licensing_strategy_output:{json.dumps(result)}")
        return result

    # ------------------------------------------------------------------
    # Validation & Grading
    # ------------------------------------------------------------------

    @keyword("Validate Stage Structure")
    def validate_stage_structure(
        self,
        stage_name: str,
        output: Dict[str, Any],
    ) -> bool:
        """Validate that stage output has the required structure.

        Args:
            stage_name: One of brainstorm, market_research, ip_analysis,
                       patent_strategy, licensing_strategy.
            output: The stage output dict to validate.

        Returns:
            True if valid.

        Raises:
            ValueError: If the output structure is invalid.
        """
        logger.info(f"Validating structure for stage: {stage_name}")

        parsers = {
            "brainstorm": BrainstormOutput.from_dict,
            "market_research": MarketResearchOutput.from_dict,
            "ip_analysis": IPAnalysisOutput.from_dict,
            "patent_strategy": PatentStrategyOutput.from_dict,
            "licensing_strategy": LicensingStrategyOutput.from_dict,
        }

        parser = parsers.get(stage_name)
        if parser is None:
            raise ValueError(
                f"Unknown stage: {stage_name}. Valid stages: {list(parsers.keys())}"
            )

        parser(output)
        logger.info(f"Structure validation passed for {stage_name}")
        return True

    @keyword("Grade Stage Output")
    def grade_stage_output(
        self,
        stage_name: str,
        output: Dict[str, Any],
        rubric: str = "",
    ) -> Dict[str, Any]:
        """Grade stage output using multi-LLM majority vote.

        Args:
            stage_name: The pipeline stage name.
            output: The stage output dict to grade.
            rubric: Grading rubric text.

        Returns:
            Dict with scores, majority_score, agreement_ratio, reasons.
        """
        logger.info(f"Grading {stage_name} output with multi-LLM vote")

        grader = self._get_multi_grader()
        result = grader.grade(
            question=f"Evaluate the quality of this {stage_name} output.",
            expected="High-quality, well-structured output with actionable insights.",
            actual=json.dumps(output, indent=2),
            rubric=rubric,
        )

        grade_dict = {
            "scores": result.scores,
            "majority_score": result.majority_score,
            "agreement_ratio": result.agreement_ratio,
            "reasons": result.reasons,
            "passed": result.passed,
            "unanimous": result.unanimous,
        }

        logger.info(f"RFC_DATA:grade_{stage_name}:{json.dumps(grade_dict)}")

        if not result.unanimous:
            logger.warn(
                f"Grader disagreement on {stage_name}: "
                f"agreement={result.agreement_ratio:.0%}, "
                f"scores={result.scores}"
            )

        return grade_dict

    # ------------------------------------------------------------------
    # Web Cache Management
    # ------------------------------------------------------------------

    @keyword("Warm Web Cache")
    def warm_web_cache(self, entries: Dict[str, Any]) -> None:
        """Pre-populate the web search cache.

        Args:
            entries: Dict mapping query strings to lists of result dicts.
        """
        parsed: Dict[str, List[SearchResult]] = {}
        for query, results in entries.items():
            parsed[query] = [SearchResult.from_dict(r) for r in results]
        self.web_cache.warm(parsed)
        logger.info(f"Warmed web cache with {len(entries)} entries")

    @keyword("Clear Web Cache")
    def clear_web_cache(self) -> None:
        """Clear all web cache entries."""
        self.web_cache.clear()
        logger.info("Web cache cleared")
