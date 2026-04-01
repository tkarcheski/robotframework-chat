"""Grader for multi-turn conversation quality metrics.

Evaluates fact consistency across turns, instruction-following drift,
and topic isolation (bleed detection) in multi-turn LLM conversations.
"""

import json
from typing import Any, List

from .models import GradeResult
from .thinking import extract_json


class MultiTurnGrader:
    """Grades multi-turn conversation quality metrics."""

    def __init__(self, llm_client: Any) -> None:
        if llm_client is None:
            raise TypeError("llm_client must not be None")
        self.llm = llm_client

    def grade_fact_consistency(
        self,
        fact_description: str,
        responses: List[str],
        probe_indices: List[int],
    ) -> GradeResult:
        """Grade whether LLM responses are consistent about a stated fact.

        Args:
            fact_description: The fact that was established (e.g. "User's
                birthday is March 15").
            responses: All LLM-generated responses in the conversation.
            probe_indices: Indices into *responses* where the fact was probed.

        Returns:
            GradeResult with consistency score and reason.
        """
        probe_texts = []
        for idx in probe_indices:
            if 0 <= idx < len(responses):
                probe_texts.append(f"Response {idx + 1}: {responses[idx]}")

        grading_prompt = f"""You are a consistency evaluator for multi-turn conversations.

Established fact:
{fact_description}

The following responses were given at different points in the conversation
when the model was probed about this fact:

{chr(10).join(probe_texts)}

Evaluate whether the responses are mutually consistent about the stated fact.
A score of 1.0 means all responses agree perfectly.
A score of 0.0 means the responses contradict each other.

Rules:
- Respond ONLY with valid JSON
- No markdown
- No commentary
- score must be a number between 0.0 and 1.0

Format:
{{
  "score": 0.0 to 1.0,
  "reason": "short explanation of consistency assessment"
}}
"""
        return self._parse_grade(grading_prompt)

    def grade_instruction_compliance(
        self,
        constraint: str,
        response: str,
    ) -> GradeResult:
        """Grade whether a single response complies with a constraint.

        Args:
            constraint: The instruction constraint (e.g. "respond only in
                bullet points").
            response: The LLM response to evaluate.

        Returns:
            GradeResult with compliance score (1.0 = compliant, 0.0 = not).
        """
        grading_prompt = f"""You are an instruction-compliance evaluator.

Constraint the model was given:
"{constraint}"

Model's response:
{response}

Evaluate whether this response complies with the stated constraint.
Score 1.0 if the response fully complies.
Score 0.0 if the response completely ignores the constraint.
Use intermediate scores for partial compliance.

Rules:
- Respond ONLY with valid JSON
- No markdown
- No commentary
- score must be a number between 0.0 and 1.0

Format:
{{
  "score": 0.0 to 1.0,
  "reason": "short explanation of compliance assessment"
}}
"""
        return self._parse_grade(grading_prompt)

    def grade_topic_isolation(
        self,
        prior_topic: str,
        new_topic: str,
        response: str,
    ) -> GradeResult:
        """Grade whether a response to a new topic avoids bleeding prior context.

        Args:
            prior_topic: Description of the previous topic.
            new_topic: Description of the new topic the user switched to.
            response: The LLM's response to the new topic.

        Returns:
            GradeResult with isolation score (1.0 = no bleed, 0.0 = full bleed).
        """
        grading_prompt = f"""You are a topic-isolation evaluator for multi-turn conversations.

The conversation previously discussed this topic:
"{prior_topic}"

The user then abruptly switched to a completely new topic:
"{new_topic}"

Model's response to the new topic:
{response}

Evaluate whether the response appropriately addresses ONLY the new topic
without inappropriately bleeding in content, terminology, or framing from
the prior topic. The response should be on-topic for the new subject.

A natural topic transition acknowledgment is acceptable; what we are
checking for is whether prior-topic content contaminates the substance
of the new-topic answer.

Score 1.0 if the response cleanly addresses only the new topic.
Score 0.0 if the response is dominated by prior-topic content.

Rules:
- Respond ONLY with valid JSON
- No markdown
- No commentary
- score must be a number between 0.0 and 1.0

Format:
{{
  "score": 0.0 to 1.0,
  "reason": "short explanation of topic isolation assessment"
}}
"""
        return self._parse_grade(grading_prompt)

    def _parse_grade(self, prompt: str) -> GradeResult:
        """Send a grading prompt to the LLM and parse the JSON result."""
        raw = self.llm.generate(prompt)
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
