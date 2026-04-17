"""Continual meta-learning probe keywords for Robot Framework.

Tests whether an LLM retains and correctly applies a skill taught
in an earlier conversation turn, after a distractor turn.
"""

from typing import Any, Dict, Optional

from robot.api import logger
from robot.api.deco import keyword

from .grader import Grader
from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data


def build_conversation_transcript(
    skill_description: str,
    skill_ack: str,
    distractor_prompt: str,
    distractor_response: str,
    test_prompt: str,
) -> str:
    """Build a multi-turn conversation transcript.

    Formats the conversation as a text transcript that can be sent
    to a stateless LLM to simulate multi-turn interaction.
    """
    return (
        f"User: I want to teach you a new skill. {skill_description}\n"
        f"Assistant: {skill_ack}\n"
        f"User: {distractor_prompt}\n"
        f"Assistant: {distractor_response}\n"
        f"User: {test_prompt}"
    )


class MetaLearningKeywords:
    """Robot Framework keywords for in-context skill retention testing."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_retries: int = 2,
    ) -> None:
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))
        self.grader = Grader(self.client)

    @keyword("Test Skill Retention")
    def test_skill_retention(
        self,
        skill_description: str,
        distractor_prompt: str,
        test_prompt: str,
        expected_answer: str,
    ) -> Dict[str, Any]:
        """Test whether the LLM retains a taught skill across turns.

        Turn 1: Teach the skill.
        Turn 2: Send a distractor (unrelated question).
        Turn 3: Test whether the skill is correctly applied.

        Args:
            skill_description: The skill to teach (e.g. "always answer in French").
            distractor_prompt: An unrelated question for the middle turn.
            test_prompt: A question that requires applying the taught skill.
            expected_answer: The expected answer demonstrating skill application.

        Returns:
            Dict with keys: score, reason, actual_answer, skill_applied.

        Raises:
            ValueError: If skill_description is empty.
        """
        if not skill_description.strip():
            raise ValueError("skill_description must not be empty")

        # Turn 1: Teach skill
        teach_prompt = f"I want to teach you a new skill. {skill_description}"
        logger.info(f"Turn 1 (teach): {teach_prompt}")
        skill_ack = self.client.generate(teach_prompt)
        logger.info(f"Turn 1 response: {skill_ack}")

        # Turn 2: Distractor
        distractor_full = (
            f"User: I want to teach you a new skill. {skill_description}\n"
            f"Assistant: {skill_ack}\n"
            f"User: {distractor_prompt}"
        )
        logger.info(f"Turn 2 (distractor): {distractor_prompt}")
        distractor_response = self.client.generate(distractor_full)
        logger.info(f"Turn 2 response: {distractor_response}")

        # Turn 3: Test skill retention
        full_transcript = build_conversation_transcript(
            skill_description=skill_description,
            skill_ack=skill_ack,
            distractor_prompt=distractor_prompt,
            distractor_response=distractor_response,
            test_prompt=test_prompt,
        )
        logger.info(f"Turn 3 (test): {test_prompt}")
        actual_answer = self.client.generate(full_transcript)
        logger.info(f"Turn 3 response: {actual_answer}")

        # Grade using only the test prompt (not the full transcript)
        grade_result = self.grader.grade(test_prompt, expected_answer, actual_answer)
        skill_applied = grade_result.score >= 0.5

        emit_rfc_data("score", str(grade_result.score))
        emit_rfc_data("expected_answer", expected_answer)
        emit_rfc_data("actual_answer", actual_answer)
        emit_rfc_data("grading_reason", grade_result.reason)
        emit_rfc_data("skill_description", skill_description)

        return {
            "score": grade_result.score,
            "reason": grade_result.reason,
            "actual_answer": actual_answer,
            "skill_applied": skill_applied,
        }
