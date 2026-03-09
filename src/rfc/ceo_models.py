"""Typed dataclasses for CEO agent pipeline stage inputs and outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


def _require_non_empty_str(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_score(value: float, name: str) -> None:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a float, got {type(value).__name__}")
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0.0 and 1.0, got {value}")


def _require_non_empty_list(value: List[Any], name: str) -> None:
    if not isinstance(value, list) or len(value) == 0:
        raise ValueError(f"{name} must be a non-empty list")


# ---------------------------------------------------------------------------
# Stage 1: Brainstorming
# ---------------------------------------------------------------------------


@dataclass
class IdeaCandidate:
    name: str
    description: str
    category: str
    novelty_notes: str

    def __post_init__(self) -> None:
        _require_non_empty_str(self.name, "name")
        _require_non_empty_str(self.description, "description")

    def to_dict(self) -> Dict[str, str]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "novelty_notes": self.novelty_notes,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> IdeaCandidate:
        return cls(
            name=d["name"],
            description=d["description"],
            category=d["category"],
            novelty_notes=d["novelty_notes"],
        )


@dataclass
class BrainstormOutput:
    ideas: List[IdeaCandidate]

    def __post_init__(self) -> None:
        _require_non_empty_list(self.ideas, "ideas")

    def to_dict(self) -> Dict[str, Any]:
        return {"ideas": [i.to_dict() for i in self.ideas]}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> BrainstormOutput:
        return cls(ideas=[IdeaCandidate.from_dict(i) for i in d["ideas"]])


# ---------------------------------------------------------------------------
# Stage 2: Market Research
# ---------------------------------------------------------------------------


@dataclass
class MarketAnalysis:
    idea_name: str
    demand_score: float
    market_size: str
    competitors: List[str]
    profitability: str

    def __post_init__(self) -> None:
        _require_non_empty_str(self.idea_name, "idea_name")
        _require_score(self.demand_score, "demand_score")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "idea_name": self.idea_name,
            "demand_score": self.demand_score,
            "market_size": self.market_size,
            "competitors": self.competitors,
            "profitability": self.profitability,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> MarketAnalysis:
        return cls(
            idea_name=d["idea_name"],
            demand_score=float(d["demand_score"]),
            market_size=d["market_size"],
            competitors=d["competitors"],
            profitability=d["profitability"],
        )


@dataclass
class MarketResearchOutput:
    analyses: List[MarketAnalysis]

    def __post_init__(self) -> None:
        _require_non_empty_list(self.analyses, "analyses")

    def to_dict(self) -> Dict[str, Any]:
        return {"analyses": [a.to_dict() for a in self.analyses]}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> MarketResearchOutput:
        return cls(analyses=[MarketAnalysis.from_dict(a) for a in d["analyses"]])


# ---------------------------------------------------------------------------
# Stage 3: IP Analysis
# ---------------------------------------------------------------------------


@dataclass
class IPFinding:
    idea_name: str
    patentability_score: float
    prior_art_gaps: List[str]
    claim_angles: List[str]

    def __post_init__(self) -> None:
        _require_non_empty_str(self.idea_name, "idea_name")
        _require_score(self.patentability_score, "patentability_score")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "idea_name": self.idea_name,
            "patentability_score": self.patentability_score,
            "prior_art_gaps": self.prior_art_gaps,
            "claim_angles": self.claim_angles,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> IPFinding:
        return cls(
            idea_name=d["idea_name"],
            patentability_score=float(d["patentability_score"]),
            prior_art_gaps=d["prior_art_gaps"],
            claim_angles=d["claim_angles"],
        )


@dataclass
class IPAnalysisOutput:
    findings: List[IPFinding]

    def __post_init__(self) -> None:
        _require_non_empty_list(self.findings, "findings")

    def to_dict(self) -> Dict[str, Any]:
        return {"findings": [f.to_dict() for f in self.findings]}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> IPAnalysisOutput:
        return cls(findings=[IPFinding.from_dict(f) for f in d["findings"]])


# ---------------------------------------------------------------------------
# Stage 4: Patent Strategy
# ---------------------------------------------------------------------------

_VALID_CLAIM_TYPES = {"utility", "design", "provisional", "continuation"}


@dataclass
class PatentStrategy:
    idea_name: str
    claim_type: str
    abstract: str
    key_claims: List[str]
    filing_priority: str

    def __post_init__(self) -> None:
        _require_non_empty_str(self.idea_name, "idea_name")
        if self.claim_type not in _VALID_CLAIM_TYPES:
            raise ValueError(
                f"claim_type must be one of {_VALID_CLAIM_TYPES}, got '{self.claim_type}'"
            )
        _require_non_empty_list(self.key_claims, "key_claims")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "idea_name": self.idea_name,
            "claim_type": self.claim_type,
            "abstract": self.abstract,
            "key_claims": self.key_claims,
            "filing_priority": self.filing_priority,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> PatentStrategy:
        return cls(
            idea_name=d["idea_name"],
            claim_type=d["claim_type"],
            abstract=d["abstract"],
            key_claims=d["key_claims"],
            filing_priority=d["filing_priority"],
        )


@dataclass
class PatentStrategyOutput:
    strategies: List[PatentStrategy]

    def __post_init__(self) -> None:
        _require_non_empty_list(self.strategies, "strategies")

    def to_dict(self) -> Dict[str, Any]:
        return {"strategies": [s.to_dict() for s in self.strategies]}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> PatentStrategyOutput:
        return cls(strategies=[PatentStrategy.from_dict(s) for s in d["strategies"]])


# ---------------------------------------------------------------------------
# Stage 5: Licensing Strategy
# ---------------------------------------------------------------------------


@dataclass
class LicensingPlan:
    idea_name: str
    target_licensees: List[str]
    pricing_model: str
    revenue_projection: str
    terms: str

    def __post_init__(self) -> None:
        _require_non_empty_str(self.idea_name, "idea_name")
        _require_non_empty_list(self.target_licensees, "target_licensees")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "idea_name": self.idea_name,
            "target_licensees": self.target_licensees,
            "pricing_model": self.pricing_model,
            "revenue_projection": self.revenue_projection,
            "terms": self.terms,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> LicensingPlan:
        return cls(
            idea_name=d["idea_name"],
            target_licensees=d["target_licensees"],
            pricing_model=d["pricing_model"],
            revenue_projection=d["revenue_projection"],
            terms=d["terms"],
        )


@dataclass
class LicensingStrategyOutput:
    plans: List[LicensingPlan] = field(default_factory=list)

    def __post_init__(self) -> None:
        _require_non_empty_list(self.plans, "plans")

    def to_dict(self) -> Dict[str, Any]:
        return {"plans": [p.to_dict() for p in self.plans]}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> LicensingStrategyOutput:
        return cls(plans=[LicensingPlan.from_dict(p) for p in d["plans"]])
