"""Prompt templates for CEO agent pipeline stages.

Each function builds a structured prompt that instructs the LLM to return JSON.
No LLM logic lives here — just string construction.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def _require_non_empty(value: Any, name: str) -> None:
    if not value:
        raise ValueError(f"{name} must be non-empty")


def build_brainstorm_prompt(
    domain: str,
    count: int = 3,
    constraints: Optional[str] = None,
) -> str:
    """Build a prompt for idea brainstorming in a given domain.

    Args:
        domain: The product/market domain to brainstorm in.
        count: Number of ideas to generate.
        constraints: Optional additional constraints or focus areas.
    """
    _require_non_empty(domain.strip() if isinstance(domain, str) else "", "domain")

    extra = f"\nAdditional constraints: {constraints}" if constraints else ""

    return f"""You are a product innovation strategist. Generate {count} novel product \
or service ideas in the domain of "{domain}".{extra}

For each idea, provide:
- name: A concise product name
- description: A 2-3 sentence description of the product/service
- category: The product category (e.g. consumer_electronics, saas, biotech)
- novelty_notes: What makes this idea novel or differentiable from existing solutions

Respond ONLY with valid JSON. No markdown, no commentary.

Format:
{{
  "ideas": [
    {{
      "name": "...",
      "description": "...",
      "category": "...",
      "novelty_notes": "..."
    }}
  ]
}}
"""


def build_market_research_prompt(
    ideas: List[Dict[str, Any]],
    web_context: Optional[str] = None,
) -> str:
    """Build a prompt for market research on a list of ideas.

    Args:
        ideas: List of idea dicts (at minimum name + description).
        web_context: Optional web search results to inject as context.
    """
    _require_non_empty(ideas, "ideas")

    ideas_text = json.dumps(ideas, indent=2)
    context_block = ""
    if web_context:
        context_block = f"""
The following market data was gathered from web research. Use it to inform
your analysis:

{web_context}
"""

    return f"""You are a market research analyst. Evaluate the following product ideas \
for market viability.
{context_block}
Ideas to analyze:
{ideas_text}

For each idea, provide:
- idea_name: The name of the idea being analyzed
- demand_score: A score from 0.0 to 1.0 indicating market demand
- market_size: Estimated total addressable market (e.g. "$2.5B")
- competitors: List of existing competitors or similar products
- profitability: Assessment ("low", "medium", "high")

Respond ONLY with valid JSON. No markdown, no commentary.

Format:
{{
  "analyses": [
    {{
      "idea_name": "...",
      "demand_score": 0.0,
      "market_size": "...",
      "competitors": ["..."],
      "profitability": "..."
    }}
  ]
}}
"""


def build_ip_analysis_prompt(
    market_analyses: List[Dict[str, Any]],
    web_context: Optional[str] = None,
) -> str:
    """Build a prompt for IP landscape analysis.

    Args:
        market_analyses: List of market analysis dicts.
        web_context: Optional patent/IP search results to inject.
    """
    _require_non_empty(market_analyses, "market_analyses")

    analyses_text = json.dumps(market_analyses, indent=2)
    context_block = ""
    if web_context:
        context_block = f"""
The following patent and IP data was gathered from research. Use it to
identify prior art gaps and patentable angles:

{web_context}
"""

    return f"""You are a patent analyst specializing in intellectual property strategy. \
Analyze the following market-validated ideas for patentability.
{context_block}
Market analyses:
{analyses_text}

For each idea, provide:
- idea_name: The name of the idea
- patentability_score: A score from 0.0 to 1.0 indicating patentability
- prior_art_gaps: List of areas where no prior art exists
- claim_angles: List of potential patent claim angles

Respond ONLY with valid JSON. No markdown, no commentary.

Format:
{{
  "findings": [
    {{
      "idea_name": "...",
      "patentability_score": 0.0,
      "prior_art_gaps": ["..."],
      "claim_angles": ["..."]
    }}
  ]
}}
"""


def build_patent_strategy_prompt(
    ip_findings: List[Dict[str, Any]],
) -> str:
    """Build a prompt for patent strategy development.

    Args:
        ip_findings: List of IP finding dicts.
    """
    _require_non_empty(ip_findings, "ip_findings")

    findings_text = json.dumps(ip_findings, indent=2)

    return f"""You are a patent attorney developing filing strategies. Based on the \
following IP analysis, develop patent strategies for each idea.

IP findings:
{findings_text}

For each idea, provide:
- idea_name: The name of the idea
- claim_type: One of "utility", "design", "provisional", or "continuation"
- abstract: A patent-style abstract (2-3 sentences)
- key_claims: List of key patent claims (at least 1)
- filing_priority: Priority level ("low", "medium", "high", "critical")

Respond ONLY with valid JSON. No markdown, no commentary.

Format:
{{
  "strategies": [
    {{
      "idea_name": "...",
      "claim_type": "utility",
      "abstract": "...",
      "key_claims": ["..."],
      "filing_priority": "..."
    }}
  ]
}}
"""


def build_licensing_strategy_prompt(
    patent_strategies: List[Dict[str, Any]],
) -> str:
    """Build a prompt for licensing strategy development.

    Args:
        patent_strategies: List of patent strategy dicts.
    """
    _require_non_empty(patent_strategies, "patent_strategies")

    strategies_text = json.dumps(patent_strategies, indent=2)

    return f"""You are a licensing strategist specializing in IP monetization. Based on \
the following patent strategies, develop licensing plans to maximize revenue.

Patent strategies:
{strategies_text}

For each idea, provide:
- idea_name: The name of the idea
- target_licensees: List of companies or industries that would license this IP
- pricing_model: The licensing model (e.g. "royalty_per_unit", "flat_fee", \
"tiered_royalty", "cross_license")
- revenue_projection: Estimated annual licensing revenue
- terms: Key licensing terms summary

Respond ONLY with valid JSON. No markdown, no commentary.

Format:
{{
  "plans": [
    {{
      "idea_name": "...",
      "target_licensees": ["..."],
      "pricing_model": "...",
      "revenue_projection": "...",
      "terms": "..."
    }}
  ]
}}
"""
