"""Multi-LLM majority-vote grader for tier:3 verification.

Uses 3+ LLM providers to evaluate a response, returning a majority-vote
result with agreement tracking.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, List, Sequence

from .thinking import parse_thinking


@dataclass
class MultiGradeResult:
    """Result of a multi-LLM grading vote."""

    scores: List[int]
    majority_score: int
    agreement_ratio: float
    reasons: List[str]

    @property
    def passed(self) -> bool:
        return self.majority_score == 1

    @property
    def unanimous(self) -> bool:
        return self.agreement_ratio == 1.0


def _extract_json(text: str) -> str:
    """Extract JSON from text that may contain markdown or thinking tags."""
    text, _ = parse_thinking(text)

    json_block_pattern = r"```(?:json)?\s*(\{.*?\})\s*```"
    matches = re.findall(json_block_pattern, text, re.DOTALL)
    if matches:
        return matches[0]

    json_pattern = r'(\{.*"score".*"reason".*?\})'
    matches = re.findall(json_pattern, text, re.DOTALL)
    if matches:
        return matches[0]

    json_pattern = r"(\{.*?\})"
    matches = re.findall(json_pattern, text, re.DOTALL)
    if matches:
        return max(matches, key=len)

    return text


class MultiGrader:
    """Grades LLM output using majority vote across multiple providers.

    Requires at least 3 providers. Each provider independently evaluates
    the output, and the majority score wins.
    """

    def __init__(self, providers: Sequence[Any]) -> None:
        if len(providers) < 3:
            raise ValueError(
                f"MultiGrader requires at least 3 providers, got {len(providers)}"
            )
        self.providers = list(providers)

    def grade(
        self,
        question: str,
        expected: str,
        actual: str,
        rubric: str = "",
    ) -> MultiGradeResult:
        """Grade a response using all providers and return majority vote.

        Args:
            question: The original question/task.
            expected: The expected output or criteria.
            actual: The actual LLM output to grade.
            rubric: Additional grading rubric or criteria.

        Returns:
            MultiGradeResult with individual scores and majority decision.
        """
        prompt = self._build_prompt(question, expected, actual, rubric)

        scores: List[int] = []
        reasons: List[str] = []

        for provider in self.providers:
            score, reason = self._grade_single(provider, prompt)
            scores.append(score)
            reasons.append(reason)

        ones = sum(scores)
        zeros = len(scores) - ones
        majority_score = 1 if ones > zeros else 0
        majority_count = max(ones, zeros)
        agreement_ratio = majority_count / len(scores)

        return MultiGradeResult(
            scores=scores,
            majority_score=majority_score,
            agreement_ratio=agreement_ratio,
            reasons=reasons,
        )

    def _build_prompt(
        self, question: str, expected: str, actual: str, rubric: str
    ) -> str:
        rubric_block = f"\nGrading rubric:\n{rubric}\n" if rubric else ""

        return f"""You are an automated grader evaluating LLM output quality.

Question/Task:
{question}

Expected output or criteria:
{expected}

Actual output:
{actual}
{rubric_block}
Rules:
- Respond ONLY with valid JSON
- No markdown
- No commentary
- score must be 0 or 1

Format:
{{
  "score": 0 or 1,
  "reason": "short explanation"
}}
"""

    def _grade_single(self, provider: Any, prompt: str) -> tuple[int, str]:
        """Get a single grade from one provider. Returns (0, error) on failure."""
        try:
            raw = provider.generate(prompt)
            json_text = _extract_json(raw)
            parsed = json.loads(json_text)
            score = int(parsed.get("score", 0))
            reason = str(parsed.get("reason", ""))
            if score not in (0, 1):
                score = 0
                reason = f"Invalid score value: {score}"
            return score, reason
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            return 0, f"Grader error: {exc}"
