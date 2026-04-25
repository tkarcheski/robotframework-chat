from dataclasses import dataclass
from typing import Any, Dict, List, Optional

_VALID_REFUSAL_TYPES = frozenset({"none", "soft", "hard"})


@dataclass
class GradeResult:
    score: float
    reason: str

    def __post_init__(self):
        if not isinstance(self.score, (int, float)):
            raise TypeError(f"score must be a float, got {type(self.score).__name__}")
        self.score = float(self.score)
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"score must be between 0.0 and 1.0, got {self.score}")
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


@dataclass
class AgenticInjectionResult:
    """Result of an agentic prompt injection check.

    Distinguishes three independent signals so a test can pinpoint
    exactly how a model failed: ignored its task, executed an injected
    instruction (canary), or leaked its system prompt.
    """

    resisted: bool
    confidence: float
    signals: Dict[str, bool]
    indicators: List[str]
    details: Dict[str, Any]

    def __post_init__(self):
        if not isinstance(self.resisted, bool):
            raise TypeError(
                f"resisted must be a bool, got {type(self.resisted).__name__}"
            )
        if not isinstance(self.confidence, (int, float)):
            raise TypeError(
                f"confidence must be a float, got {type(self.confidence).__name__}"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be between 0.0 and 1.0, got {self.confidence}"
            )
        if not isinstance(self.signals, dict):
            raise TypeError(
                f"signals must be a dict, got {type(self.signals).__name__}"
            )
        if not isinstance(self.indicators, list):
            raise TypeError(
                f"indicators must be a list, got {type(self.indicators).__name__}"
            )


@dataclass
class CalibrationResult:
    """Result of a refusal-calibration check on a benign-but-edge-case prompt.

    is_calibrated is True when the model engaged appropriately (no refusal or
    soft hedging followed by a real answer). It is False when the model
    refused outright on a legitimate request — i.e., over-refusal.
    """

    is_calibrated: bool
    refusal_type: str
    confidence: float
    category: str
    indicators: List[str]
    details: Dict[str, Any]
    violation_type: Optional[str] = None

    def __post_init__(self):
        if not isinstance(self.is_calibrated, bool):
            raise TypeError(
                f"is_calibrated must be a bool, got {type(self.is_calibrated).__name__}"
            )
        if self.refusal_type not in _VALID_REFUSAL_TYPES:
            raise ValueError(
                f"refusal_type must be one of {sorted(_VALID_REFUSAL_TYPES)}, "
                f"got {self.refusal_type!r}"
            )
        if not isinstance(self.confidence, (int, float)):
            raise TypeError(
                f"confidence must be a float, got {type(self.confidence).__name__}"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be between 0.0 and 1.0, got {self.confidence}"
            )
        if not isinstance(self.category, str):
            raise TypeError(
                f"category must be a str, got {type(self.category).__name__}"
            )
        if not isinstance(self.indicators, list):
            raise TypeError(
                f"indicators must be a list, got {type(self.indicators).__name__}"
            )
