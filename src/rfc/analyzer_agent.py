"""Analyzer agent for reviewing test failures and producing recommendations.

Runs as a fresh LLM session (not during test execution). Designed to be
triggered nightly by a cron job or manually via ``scripts/nightly_finetune.py``.

Escalation order:
    1. Suggest prompt improvements
    2. Suggest test input changes
    3. Suggest model parameter changes
    4. Create GitHub issue requesting human help
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _extract_first_json_object(text: str) -> Optional[str]:
    """Extract the first balanced top-level JSON object from a string.

    Scans for the first ``{``, then walks forward tracking brace depth.
    String contents (including escaped quotes) are skipped so braces inside
    strings don't confuse the count. Returns the substring covering the
    balanced object, or ``None`` if no balanced object is found.

    A balanced-brace scan is required (rather than ``re.search(r"\\{[^}]+\\}")``)
    because LLM responses commonly nest objects — e.g.
    ``{"suggested_params": {"temperature": 0.0}}`` — and a non-greedy regex
    that excludes ``}`` truncates at the first inner brace, producing
    invalid JSON.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if in_string:
            if ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


@dataclass
class FailureRecord:
    """A single test failure for analysis."""

    test_name: str
    test_suite: str
    model_name: str
    question: str
    expected_answer: str
    actual_answer: str
    grading_reason: str
    score: float
    self_healing_strategies_tried: List[str] = field(default_factory=list)


@dataclass
class Recommendation:
    """A recommendation from the analyzer agent."""

    recommendation_type: str  # "prompt", "input", "params", "escalate"
    test_name: str
    details: str
    confidence: float  # 0.0-1.0
    suggested_prompt: str = ""
    suggested_params: Dict[str, Any] = field(default_factory=dict)


class AnalyzerAgent:
    """Reviews test failures and recommends improvements.

    Uses an LLM client to analyze failure patterns and produce
    actionable recommendations. The LLM call is made in a fresh
    context (no test execution state).

    Args:
        llm_client: An object satisfying the ``LLMProvider`` protocol.
            Should be a fresh session, not the test execution client.
    """

    def __init__(self, llm_client: Any) -> None:
        if llm_client is None:
            raise TypeError("llm_client must not be None")
        self.llm = llm_client

    def analyze_failures(self, failures: List[FailureRecord]) -> List[Recommendation]:
        """Analyze a batch of test failures and produce recommendations.

        For each failure, the agent attempts escalating analysis:
        1. Can the prompt be improved?
        2. Should the test input change?
        3. Should model parameters change?
        4. Escalate to human review.

        Args:
            failures: List of test failure records.

        Returns:
            List of recommendations, one per failure.
        """
        recommendations: List[Recommendation] = []
        for failure in failures:
            rec = self._analyze_single(failure)
            recommendations.append(rec)
        return recommendations

    def _analyze_single(self, failure: FailureRecord) -> Recommendation:
        """Analyze a single test failure."""
        prompt = self._build_analysis_prompt(failure)
        try:
            raw_response = self.llm.generate(prompt)
            return self._parse_recommendation(failure, raw_response)
        except Exception as exc:
            logger.warning("Analysis failed for %s: %s", failure.test_name, exc)
            return Recommendation(
                recommendation_type="escalate",
                test_name=failure.test_name,
                details=f"Analysis failed: {exc}",
                confidence=0.0,
            )

    def _build_analysis_prompt(self, failure: FailureRecord) -> str:
        """Build the prompt for failure analysis."""
        strategies_note = ""
        if failure.self_healing_strategies_tried:
            strategies_note = (
                f"\nStrategies already tried: "
                f"{', '.join(failure.self_healing_strategies_tried)}"
            )

        return (
            "You are a test failure analyst. A Robot Framework test that "
            "evaluates LLM output has failed. Analyze the failure and "
            "recommend ONE action.\n\n"
            f"Test: {failure.test_name}\n"
            f"Suite: {failure.test_suite}\n"
            f"Model: {failure.model_name}\n"
            f"Score: {failure.score}\n"
            f"{strategies_note}\n\n"
            f"Question:\n{failure.question}\n\n"
            f"Expected answer:\n{failure.expected_answer}\n\n"
            f"Actual answer:\n{failure.actual_answer}\n\n"
            f"Grading reason:\n{failure.grading_reason}\n\n"
            "Respond with ONLY valid JSON:\n"
            "{\n"
            '  "recommendation_type": "prompt" | "input" | "params" | "escalate",\n'
            '  "details": "explanation of what to change",\n'
            '  "confidence": 0.0 to 1.0,\n'
            '  "suggested_prompt": "rewritten prompt (only if type is prompt)",\n'
            '  "suggested_params": {} (only if type is params)\n'
            "}"
        )

    def _parse_recommendation(
        self, failure: FailureRecord, raw_response: str
    ) -> Recommendation:
        """Parse the LLM response into a Recommendation."""
        try:
            parsed = json.loads(raw_response)
        except json.JSONDecodeError:
            extracted = _extract_first_json_object(raw_response)
            if extracted is None:
                return Recommendation(
                    recommendation_type="escalate",
                    test_name=failure.test_name,
                    details=f"Could not parse analysis: {raw_response[:200]}",
                    confidence=0.0,
                )
            try:
                parsed = json.loads(extracted)
            except json.JSONDecodeError:
                return Recommendation(
                    recommendation_type="escalate",
                    test_name=failure.test_name,
                    details=f"Could not parse analysis: {raw_response[:200]}",
                    confidence=0.0,
                )

        rec_type = parsed.get("recommendation_type", "escalate")
        if rec_type not in ("prompt", "input", "params", "escalate"):
            rec_type = "escalate"

        return Recommendation(
            recommendation_type=rec_type,
            test_name=failure.test_name,
            details=str(parsed.get("details", "")),
            confidence=float(parsed.get("confidence", 0.0)),
            suggested_prompt=str(parsed.get("suggested_prompt", "")),
            suggested_params=parsed.get("suggested_params", {}),
        )

    def create_training_pairs(
        self,
        failures: List[FailureRecord],
        recommendations: Optional[List[Recommendation]] = None,
    ) -> List[Dict[str, Any]]:
        """Convert failures into training data pairs for LoRA fine-tuning.

        Each pair is a chat-format entry suitable for JSONL training datasets.

        Args:
            failures: Test failure records.
            recommendations: Optional pre-computed recommendations.

        Returns:
            List of training pair dicts with ``messages`` and ``metadata``.
        """
        pairs: List[Dict[str, Any]] = []
        for failure in failures:
            pair = {
                "messages": [
                    {
                        "role": "user",
                        "content": failure.question,
                    },
                    {
                        "role": "assistant",
                        "content": failure.expected_answer,
                    },
                ],
                "metadata": {
                    "source": "failure",
                    "test_name": failure.test_name,
                    "test_suite": failure.test_suite,
                    "model_name": failure.model_name,
                    "original_score": failure.score,
                    "actual_answer": failure.actual_answer,
                    "grading_reason": failure.grading_reason,
                },
            }
            pairs.append(pair)
        return pairs


__all__ = ["AnalyzerAgent", "FailureRecord", "Recommendation"]
