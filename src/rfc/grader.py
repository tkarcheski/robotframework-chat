import json
import re

from .models import GradeResult
from .thinking import parse_thinking


class Grader:
    def __init__(self, llm_client):
        if llm_client is None:
            raise TypeError("llm_client must not be None")
        self.llm = llm_client

    def _extract_json(self, text: str) -> str:
        """Extract JSON from text that may contain markdown or reasoning.

        Handles:
        - Markdown code blocks (```json...```)
        - Thinking tags (<think>...</think> or <thinking>...</thinking>)
        - Text before/after JSON
        """
        # Remove thinking tags (various formats used by different models)
        text, _ = parse_thinking(text)

        # Try to find JSON in markdown code blocks
        json_block_pattern = r"```(?:json)?\s*(\{.*?\})\s*```"
        matches = re.findall(json_block_pattern, text, re.DOTALL)
        if matches:
            return matches[0]

        # Try to find bare JSON object
        json_pattern = r'(\{.*"score".*"reason".*?\})'
        matches = re.findall(json_pattern, text, re.DOTALL)
        if matches:
            return matches[0]

        # Last resort: look for any JSON object
        json_pattern = r"(\{.*?\})"
        matches = re.findall(json_pattern, text, re.DOTALL)
        if matches:
            # Return the largest match (most likely the full JSON)
            return max(matches, key=len)

        return text

    def grade(self, question: str, expected: str, actual: str) -> GradeResult:
        for name, val in [
            ("question", question),
            ("expected", expected),
            ("actual", actual),
        ]:
            if not isinstance(val, str):
                raise TypeError(f"{name} must be a str, got {type(val).__name__}")
        if not question.strip():
            raise ValueError("question must be a non-empty string")
        prompt = f"""
You are an automaed grader.

Question:
{question}

Expected answer:
{expected}

Model answer:
{actual}

Rules:
- Respond ONLY with valid JSON
- No markdown
- No commentary
- score must be a number between 0.0 and 1.0
- use partial credit when the answer is only partially correct

Format:
{{
  "score": 0.0 to 1.0,
  "reason": "short explanation"
}}
"""

        raw = self.llm.generate(prompt)

        # Extract JSON from response (handle thinking tags, markdown, etc.)
        json_text = self._extract_json(raw)

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
