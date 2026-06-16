import json

from .models import GradeResult
from .rfc_data import emit_rfc_data
from .thinking import extract_json


class Grader:
    def __init__(self, llm_client):
        if llm_client is None:
            raise TypeError("llm_client must not be None")
        self.llm = llm_client

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
        if not actual.strip():
            # Score absent output as 0 directly rather than asking the
            # LLM judge to interpret silence (judges return charitable
            # partial credit and silently inflate pass rates). Return
            # — don't raise — so callers like
            # LLMKeywords.ask_and_grade_with_retry keep their existing
            # retry / EmptyLLMResponseError contract.
            return GradeResult(
                score=0.0,
                reason="Empty response — model produced no content to evaluate",
            )
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
        last_metrics = getattr(self.llm, "last_metrics", None)
        if isinstance(last_metrics, dict) and last_metrics:
            emit_rfc_data("llm_metrics", json.dumps(last_metrics))

        # Extract JSON from response (handle thinking tags, markdown, etc.)
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
