"""Creativity-specific grader for humor and context awareness testing.

Wraps the standard Grader pattern with prompts tuned for evaluating
joke quality, creativity, originality, and conversational context retention.
"""

import json
from typing import Any, Union

from .models import GradeResult
from .multi_grader import MultiGrader
from .thinking import extract_json


class CreativityGrader:
    """Grades LLM creative output (jokes, stories, context awareness)."""

    def __init__(self, llm_client: Union[Any, MultiGrader]) -> None:
        if llm_client is None:
            raise TypeError("llm_client must not be None")
        # Stored as Any so the single-client branch (grade_context, the
        # legacy grade_joke path) keeps type-checking. The MultiGrader
        # branch in grade_joke narrows via isinstance.
        self.llm: Any = llm_client

    def grade_joke(self, prompt: str, joke: str, expected_traits: str) -> GradeResult:
        """Grade a joke on humor, creativity, originality, and relevance."""
        for name, val in [
            ("prompt", prompt),
            ("joke", joke),
            ("expected_traits", expected_traits),
        ]:
            if not isinstance(val, str):
                raise TypeError(f"{name} must be a str, got {type(val).__name__}")
        if not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        if not joke.strip():
            # An empty joke cannot be judged; score 0.0 directly so the
            # caller's retry loop preserves its EmptyLLMResponseError contract.
            return GradeResult(
                score=0.0,
                reason="Empty joke — model produced no content to evaluate",
            )

        if isinstance(self.llm, MultiGrader):
            return self._grade_joke_with_panel(prompt, joke, expected_traits)

        grading_prompt = f"""You are a comedy and creativity judge.

Original joke prompt:
{prompt}

Joke produced:
{joke}

Expected traits:
{expected_traits}

Evaluate the joke on these criteria:
1. Humor - Is it actually funny or amusing?
2. Creativity - Is it original and not a well-known stock joke?
3. Relevance - Does it match the requested prompt and expected traits?
4. Format - Does it follow any requested format (knock-knock, limerick, etc.)?

Rules:
- Respond ONLY with valid JSON
- No markdown
- No commentary
- score must be a number between 0.0 and 1.0
- Be generous with partial credit for genuine attempts at humor

Format:
{{
  "score": 0.0 to 1.0,
  "reason": "short explanation covering humor, creativity, relevance"
}}
"""
        raw = self.llm.generate(grading_prompt)
        json_text = extract_json(raw)

        try:
            parsed = json.loads(json_text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Grader returned invalid JSON: {raw}") from e

        if "score" not in parsed or "reason" not in parsed:
            raise ValueError(f"Grader JSON missing required fields: {parsed}")

        return GradeResult(
            score=float(parsed["score"]),
            reason=str(parsed["reason"]),
        )

    def _grade_joke_with_panel(
        self, prompt: str, joke: str, expected_traits: str
    ) -> GradeResult:
        """Grade a joke using a MultiGrader panel of distinct judge models.

        Eliminates self-grading bias (issue #260) by routing the rubric
        through providers other than the one that generated the joke.
        """
        rubric = (
            "Evaluate the joke on these criteria:\n"
            "1. Humor - Is it actually funny or amusing?\n"
            "2. Creativity - Is it original and not a well-known stock joke?\n"
            "3. Relevance - Does it match the requested prompt and "
            "expected traits?\n"
            "4. Format - Does it follow any requested format "
            "(knock-knock, limerick, etc.)?\n"
            "Be generous with partial credit for genuine attempts at humor."
        )
        question = (
            f"Original joke prompt:\n{prompt}\n\nExpected traits:\n{expected_traits}"
        )
        result = self.llm.grade(
            question=question,
            expected=expected_traits,
            actual=joke,
            rubric=rubric,
        )
        reason = (
            f"panel majority {result.majority_score:.2f} "
            f"(agreement {result.agreement_ratio:.0%}): " + " | ".join(result.reasons)
        )
        return GradeResult(score=result.majority_score, reason=reason)

    def grade_context(
        self,
        scenario_description: str,
        conversation: str,
        response: str,
        expected: str,
    ) -> GradeResult:
        """Grade whether the LLM maintained conversational context."""
        for name, val in [
            ("scenario_description", scenario_description),
            ("conversation", conversation),
            ("response", response),
            ("expected", expected),
        ]:
            if not isinstance(val, str):
                raise TypeError(f"{name} must be a str, got {type(val).__name__}")
        if not scenario_description.strip():
            raise ValueError("scenario_description must be a non-empty string")
        if not response.strip():
            # An empty response cannot demonstrate context retention; score 0
            # directly rather than delegating silence to the LLM judge.
            return GradeResult(
                score=0.0,
                reason="Empty response — model produced no content to evaluate",
            )

        grading_prompt = f"""You are a context awareness evaluator.

Scenario: {scenario_description}

Conversation history:
{conversation}

LLM's response:
{response}

Expected behavior:
{expected}

Evaluate whether the LLM maintained context from the conversation history
and produced a response that correctly references earlier information.

Rules:
- Respond ONLY with valid JSON
- No markdown
- No commentary
- score must be a number between 0.0 and 1.0
- Score 1.0 if the response perfectly maintains context
- Score 0.0 if the response completely ignores prior context

Format:
{{
  "score": 0.0 to 1.0,
  "reason": "short explanation of context awareness quality"
}}
"""
        raw = self.llm.generate(grading_prompt)
        json_text = extract_json(raw)

        try:
            parsed = json.loads(json_text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Grader returned invalid JSON: {raw}") from e

        if "score" not in parsed or "reason" not in parsed:
            raise ValueError(f"Grader JSON missing required fields: {parsed}")

        return GradeResult(
            score=float(parsed["score"]),
            reason=str(parsed["reason"]),
        )
