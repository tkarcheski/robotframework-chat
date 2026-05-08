"""Causal reasoning grader for tier:2 verification.

Evaluates whether an LLM correctly identifies causes, predicts effects,
reasons counterfactually, or distinguishes correlation from causation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict

from .thinking import extract_json

_VALID_QUESTION_TYPES = frozenset(
    {"cause_id", "effect_pred", "counterfactual", "correlation_vs_causation", "causal_chain"}
)

_QUESTION_TYPE_LABELS = {
    "cause_id": "cause identification",
    "effect_pred": "effect prediction",
    "counterfactual": "counterfactual reasoning",
    "correlation_vs_causation": "correlation vs. causation",
    "causal_chain": "causal chain tracing",
}


@dataclass
class CausalGradeResult:
    """Result of a causal reasoning grading pass."""

    score: float
    reason: str
    question_type: str

    def __post_init__(self) -> None:
        if not isinstance(self.score, (int, float)):
            raise TypeError(f"score must be a float, got {type(self.score).__name__}")
        self.score = float(self.score)
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"score must be between 0.0 and 1.0, got {self.score}")
        if not isinstance(self.reason, str):
            raise TypeError(f"reason must be a str, got {type(self.reason).__name__}")

    @property
    def passed(self) -> bool:
        return self.score >= 0.5


class CausalReasoningGrader:
    """Grades LLM causal reasoning responses using a single LLM judge.

    Covers five question types:
    - cause_id: identify the root cause in a scenario
    - effect_pred: predict the downstream effect of an intervention
    - counterfactual: reason about what would have happened otherwise
    - correlation_vs_causation: distinguish causal from correlational relationships
    - causal_chain: trace a multi-hop A→B→C chain back to the initiating cause
    """

    def __init__(self, llm_client: Any) -> None:
        if llm_client is None:
            raise TypeError("llm_client must not be None")
        self.llm = llm_client

    def grade(
        self,
        scenario: str,
        question: str,
        expected: str,
        actual: str,
        question_type: str,
    ) -> CausalGradeResult:
        """Grade a causal reasoning response.

        Args:
            scenario: The scenario text providing causal context.
            question: The specific causal reasoning question asked.
            expected: The correct answer or grading criteria.
            actual: The LLM's actual response to evaluate.
            question_type: One of the five causal question type keys.

        Returns:
            CausalGradeResult with score (0.0–1.0), reason, and question_type.
        """
        for name, val in [
            ("scenario", scenario),
            ("question", question),
            ("expected", expected),
            ("actual", actual),
            ("question_type", question_type),
        ]:
            if not isinstance(val, str):
                raise TypeError(f"{name} must be a str, got {type(val).__name__}")

        if not actual.strip():
            return CausalGradeResult(
                score=0.0,
                reason="Empty response — model produced no content to evaluate",
                question_type=question_type,
            )

        prompt = self._build_prompt(scenario, question, expected, actual, question_type)
        raw = self.llm.generate(prompt)

        json_text = extract_json(raw)

        try:
            parsed = json.loads(json_text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Grader returned invalid JSON: {raw}") from e

        if "score" not in parsed or "reason" not in parsed:
            raise ValueError(f"Grader JSON missing required fields: {parsed}")

        return CausalGradeResult(
            score=float(parsed["score"]),
            reason=str(parsed["reason"]),
            question_type=question_type,
        )

    def _build_prompt(
        self,
        scenario: str,
        question: str,
        expected: str,
        actual: str,
        question_type: str,
    ) -> str:
        label = _QUESTION_TYPE_LABELS.get(question_type, question_type)
        return f"""You are an automated grader evaluating causal reasoning quality.

Task type: {label}

Scenario:
{scenario}

Question:
{question}

Expected answer or criteria:
{expected}

Model's actual answer:
{actual}

Grading rubric for {label}:
- Score 1.0: The model correctly identified the causal relationship and explained it clearly.
- Score 0.5–0.9: Partial credit — correct direction but missing depth, nuance, or the confounding variable.
- Score 0.1–0.4: Partially wrong — mixed correct and incorrect causal claims.
- Score 0.0: Wrong causal direction, confused correlation with causation, or refused to answer.

Rules:
- Respond ONLY with valid JSON
- No markdown, no commentary
- score must be a number between 0.0 and 1.0

Format:
{{
  "score": 0.0 to 1.0,
  "reason": "short explanation"
}}
"""

    def check_causal_json_structure(self, response: str) -> Dict[str, Any]:
        """Tier 1 deterministic check: verify structured causal JSON output.

        Expects the model to have produced JSON with "cause" and "effect" keys,
        both with non-empty string values.

        Args:
            response: Raw LLM response expected to contain causal JSON.

        Returns:
            Dict with has_cause, has_effect, is_valid, and parsed values.
        """
        result: Dict[str, Any] = {
            "has_cause": False,
            "has_effect": False,
            "is_valid": False,
            "cause": None,
            "effect": None,
        }

        try:
            json_text = extract_json(response)
            parsed = json.loads(json_text)
        except (json.JSONDecodeError, ValueError):
            return result

        cause = parsed.get("cause", "")
        effect = parsed.get("effect", "")

        result["has_cause"] = isinstance(cause, str) and bool(cause.strip())
        result["has_effect"] = isinstance(effect, str) and bool(effect.strip())
        result["cause"] = cause if result["has_cause"] else None
        result["effect"] = effect if result["has_effect"] else None
        result["is_valid"] = result["has_cause"] and result["has_effect"]

        return result
