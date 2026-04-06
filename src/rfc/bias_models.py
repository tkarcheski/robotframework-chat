"""Data models for demographic parity bias testing.

Provides structured result types for bias detection and demographic
scenario definitions used by :class:`~rfc.bias_grader.BiasGrader`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class BiasResult:
    """Result of a demographic parity assessment.

    Attributes:
        parity_score: Overall parity score (0.0–1.0, where 1.0 = perfect parity).
        flagged_responses: Demographic labels whose responses diverged.
        pairwise_scores: Mapping of ``"label_a vs label_b"`` to similarity score.
        reason: Human-readable explanation of the assessment.
        details: Additional metadata (scenario, raw responses, etc.).
    """

    parity_score: float
    flagged_responses: List[str]
    pairwise_scores: Dict[str, float]
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.parity_score, (int, float)):
            raise TypeError(
                f"parity_score must be a float, got {type(self.parity_score).__name__}"
            )
        self.parity_score = float(self.parity_score)
        if not 0.0 <= self.parity_score <= 1.0:
            raise ValueError(
                f"parity_score must be between 0.0 and 1.0, got {self.parity_score}"
            )
        if not isinstance(self.flagged_responses, list):
            raise TypeError(
                f"flagged_responses must be a list, "
                f"got {type(self.flagged_responses).__name__}"
            )
        if not isinstance(self.pairwise_scores, dict):
            raise TypeError(
                f"pairwise_scores must be a dict, "
                f"got {type(self.pairwise_scores).__name__}"
            )
        if not isinstance(self.reason, str):
            raise TypeError(f"reason must be a str, got {type(self.reason).__name__}")


@dataclass
class DemographicScenario:
    """A professional scenario template with swappable demographic markers.

    Attributes:
        id: Unique scenario identifier.
        template: Prompt template with ``{placeholder}`` slots.
        markers: Mapping of demographic label to placeholder values,
                 e.g. ``{"group_a": {"name": "James"}, "group_b": {"name": "Lakisha"}}``.
        category: Bias category (``hiring``, ``financial``, ``medical``, ``performance``).
        parity_threshold: Minimum acceptable parity score for this scenario.
    """

    id: str
    template: str
    markers: Dict[str, Dict[str, str]]
    category: str
    parity_threshold: float = 0.8

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id must be a non-empty string")
        if not self.template:
            raise ValueError("template must be a non-empty string")
        if len(self.markers) < 2:
            raise ValueError("markers must contain at least 2 demographic groups")
        if not 0.0 <= self.parity_threshold <= 1.0:
            raise ValueError(
                f"parity_threshold must be between 0.0 and 1.0, "
                f"got {self.parity_threshold}"
            )

    def render_prompt(self, label: str) -> str:
        """Render the template with the demographic markers for *label*.

        Raises:
            KeyError: If *label* is not found in :attr:`markers`.
        """
        return self.template.format(**self.markers[label])
