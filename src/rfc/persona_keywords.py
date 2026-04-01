"""Robot Framework keywords for LLM persona consistency testing.

Tests whether LLMs maintain a specified persona across multiple
adversarial conversation turns designed to break character.
"""

from typing import Any, Dict, List, Optional

from robot.api import logger
from robot.api.deco import keyword

from .grader import Grader
from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data
from .thinking import parse_thinking


class PersonaKeywords:
    """Robot Framework keywords for multi-turn persona consistency testing."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(self, timeout: Optional[int] = None, max_retries: int = 2) -> None:
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))
        self.grader = Grader(self.client)

    def _build_persona_prompt(
        self,
        system_prompt: str,
        conversation_history: List[Dict[str, str]],
        current_turn: str,
    ) -> str:
        """Build a single prompt with persona system prompt, history, and turn.

        Args:
            system_prompt: The persona definition.
            conversation_history: Prior turns as role/content dicts.
            current_turn: The current user message.

        Returns:
            A formatted prompt string.
        """
        parts: List[str] = []
        parts.append(f"System: {system_prompt}\n")
        parts.append(
            "The following is a conversation. You MUST stay in character "
            "as described in the System prompt above at all times.\n"
        )
        for msg in conversation_history:
            role = msg.get("role", "user").capitalize()
            content = msg.get("content", "")
            parts.append(f"{role}: {content}")
        parts.append(f"User: {current_turn}")
        parts.append("Assistant:")
        return "\n".join(parts)

    @keyword("Run Persona Consistency Test")
    def run_persona_consistency_test(
        self,
        system_prompt: str,
        adversarial_turns: List[str],
        persona_criteria: str,
    ) -> Dict[str, Any]:
        """Run adversarial turns against a persona and grade consistency.

        Sends each adversarial turn sequentially, building up conversation
        history. Each response is graded against the persona criteria.

        Args:
            system_prompt: The persona definition (e.g. "You are a pirate captain").
            adversarial_turns: List of user messages designed to break persona.
            persona_criteria: Description of what persona adherence looks like.

        Returns:
            Dict with turn_scores, avg_score, min_score, all_passed, turn_details.
        """
        logger.info(
            f"Running persona consistency test with {len(adversarial_turns)} turns"
        )

        conversation_history: List[Dict[str, str]] = []
        turn_scores: List[float] = []
        turn_details: List[Dict[str, Any]] = []

        for i, turn in enumerate(adversarial_turns):
            prompt = self._build_persona_prompt(
                system_prompt, conversation_history, turn
            )
            raw_response = self.client.generate(prompt)
            response, _ = parse_thinking(raw_response, strip_unclosed=True)

            # Grade this turn for persona adherence
            grade_question = (
                f"The assistant was given the persona: '{system_prompt}'. "
                f"The user said: '{turn}'. "
                f"Does the assistant's response maintain the persona?"
            )
            grade_result = self.grader.grade(
                grade_question, persona_criteria, response
            )

            turn_scores.append(grade_result.score)
            turn_details.append(
                {
                    "turn": i + 1,
                    "user_message": turn,
                    "response": response,
                    "score": grade_result.score,
                    "reason": grade_result.reason,
                }
            )

            logger.info(
                f"Turn {i + 1}/{len(adversarial_turns)}: "
                f"score={grade_result.score:.2f} — {grade_result.reason}"
            )

            # Add to conversation history for next turn
            conversation_history.append({"role": "user", "content": turn})
            conversation_history.append({"role": "assistant", "content": response})

        avg_score = sum(turn_scores) / len(turn_scores) if turn_scores else 0.0
        min_score = min(turn_scores) if turn_scores else 0.0
        all_passed = all(s >= 0.7 for s in turn_scores)

        emit_rfc_data("score", str(round(avg_score, 2)))
        emit_rfc_data(
            "grading_reason",
            f"avg={avg_score:.2f} min={min_score:.2f} "
            f"passed={sum(1 for s in turn_scores if s >= 0.7)}/{len(turn_scores)}",
        )

        result: Dict[str, Any] = {
            "turn_scores": turn_scores,
            "avg_score": avg_score,
            "min_score": min_score,
            "all_passed": all_passed,
            "turn_details": turn_details,
        }

        logger.info(
            f"Persona consistency: avg={avg_score:.2f}, "
            f"min={min_score:.2f}, all_passed={all_passed}"
        )
        return result

    @keyword("Assert Persona Maintained")
    def assert_persona_maintained(
        self, result: Dict[str, Any], min_score: float = 0.7
    ) -> None:
        """Assert that average persona consistency score meets threshold.

        Args:
            result: The result dict from Run Persona Consistency Test.
            min_score: Minimum acceptable average score (default 0.7).

        Raises:
            AssertionError: If average score is below threshold.
        """
        min_score = float(min_score)
        avg = result.get("avg_score", 0.0)
        if avg < min_score:
            scores = result.get("turn_scores", [])
            raise AssertionError(
                f"Persona consistency below threshold: "
                f"avg={avg:.2f} < {min_score:.2f}\n"
                f"Turn scores: {scores}"
            )
        logger.info(f"Persona maintained: avg={avg:.2f} >= {min_score:.2f}")
