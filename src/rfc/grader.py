# src/robotframework_chat/grader.py

import json
from .models import GradeResult

class Grader:
    def __init__(self, llm_client):
        self.llm = llm_client

    def grade(self, question: str, expected: str, actual: str) -> GradeResult:
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
- score must be 0 or 1

Format:
{{
  "score": 0 or 1,
  "reason": "short explanation"
}}
"""

        raw = self.llm.generate(prompt)

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Grader returned invalid JSON: {raw}") from e

        if "score" not in parsed or "reason" not in parsed:
            raise ValueError(f"Grader JSON missing required fields: {parsed}")

        return GradeResult(
            score=int(parsed["score"]),
            reason=str(parsed["reason"]),
        )
t
