from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class GradeResult:
    score: int
    reason: str

    def __post_init__(self):
        if not isinstance(self.score, int):
            raise TypeError(f"score must be an int, got {type(self.score).__name__}")
        if self.score not in (0, 1):
            raise ValueError(f"score must be 0 or 1, got {self.score}")
        if not isinstance(self.reason, str):
            raise TypeError(f"reason must be a str, got {type(self.reason).__name__}")


@dataclass
class SafetyResult:
    """Result of a safety check."""

    is_safe: bool
    confidence: float
    violation_type: Optional[str]
    indicators: List[str]
    details: Dict[str, Any]

    def __post_init__(self):
        if not isinstance(self.is_safe, bool):
            raise TypeError(
                f"is_safe must be a bool, got {type(self.is_safe).__name__}"
            )
        if not isinstance(self.confidence, (int, float)):
            raise TypeError(
                f"confidence must be a float, got {type(self.confidence).__name__}"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be between 0.0 and 1.0, got {self.confidence}"
            )
        if not isinstance(self.indicators, list):
            raise TypeError(
                f"indicators must be a list, got {type(self.indicators).__name__}"
            )
