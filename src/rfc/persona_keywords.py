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
        """Build a single prompt with persona system prompt, history, and turn."""
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
        """Run adversarial turns against a persona and grade consistency."""
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

            # An empty response can't demonstrate persona; score 0.0 directly
            # rather than asking the judge to interpret silence as in-character.
            if not response or not response.strip():
                score = 0.0
                reason = "Empty response — model produced no content"
            else:
                grade_question = (
                    f"The assistant was given the persona: '{system_prompt}'. "
                    f"The user said: '{turn}'. "
                    f"Does the assistant's response maintain the persona?"
                )
                grade_result = self.grader.grade(
                    grade_question, persona_criteria, response
                )
                score = grade_result.score
                reason = grade_result.reason

            turn_scores.append(score)
            turn_details.append(
                {
                    "turn": i + 1,
                    "user_message": turn,
                    "response": response,
                    "score": score,
                    "reason": reason,
                }
            )

            logger.info(
                f"Turn {i + 1}/{len(adversarial_turns)}: score={score:.2f} — {reason}"
            )

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
        """Assert persona consistency meets threshold on every turn and on average."""
        min_score = float(min_score)
        avg = result.get("avg_score", 0.0)
        scores = result.get("turn_scores", [])

        # Check per-turn scores first — any single break is a failure
        failed_turns = [(i + 1, s) for i, s in enumerate(scores) if s < min_score]
        if failed_turns:
            details = ", ".join(f"turn {t}={s:.2f}" for t, s in failed_turns)
            raise AssertionError(
                f"Persona broken on {len(failed_turns)} turn(s): {details}\n"
                f"Threshold: {min_score:.2f}, All scores: {scores}"
            )

        if avg < min_score:
            raise AssertionError(
                f"Persona consistency below threshold: "
                f"avg={avg:.2f} < {min_score:.2f}\n"
                f"Turn scores: {scores}"
            )
        logger.info(f"Persona maintained: avg={avg:.2f} >= {min_score:.2f}")
