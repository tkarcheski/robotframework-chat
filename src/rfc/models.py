from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class GradeResult:
    score: int
    reason: str


@dataclass
class SafetyResult:
    """Result of a safety check."""

    is_safe: bool
    confidence: float
    violation_type: Optional[str]
    indicators: List[str]
    details: Dict[str, Any]
