"""Robot Framework keywords for multi-turn conversation testing.

Provides keywords for running incremental multi-turn conversations,
grading fact consistency, scoring instruction-following drift, and
evaluating topic isolation (context bleed detection).
"""

from typing import Any, Dict, List, Optional, Tuple

from robot.api import logger
from robot.api.deco import keyword

from .llm_client import create_provider, resolve_timeout
from .multi_turn_grader import MultiTurnGrader
from .rfc_data import emit_rfc_data
from .thinking import parse_thinking


class MultiTurnKeywords:
    """Robot Framework keywords for multi-turn conversation quality testing."""

    def __init__(
        self,
        timeout: Optional[int] = None,
        hide_thinking: bool | str = True,
    ) -> None:
        timeout = resolve_timeout(timeout)
        self.client: Any = create_provider(timeout=timeout)
        self.grader = MultiTurnGrader(self.client)
        self._hide_thinking: bool = (
            hide_thinking.lower() not in ("false", "0", "no")
            if isinstance(hide_thinking, str)
            else bool(hide_thinking)
        )

    def _build_conversation_prompt(self, messages: List[Dict[str, str]]) -> str:
        """Build a single prompt string from a conversation message list."""
        parts: List[str] = []
        parts.append(
            "The following is a conversation. Continue naturally, "
            "maintaining context from all previous messages.\n"
        )
        for msg in messages:
            role = msg.get("role", "user").capitalize()
            content = msg.get("content", "")
            parts.append(f"{role}: {content}")
        parts.append("Assistant:")
        return "\n".join(parts)

    def _generate_response(self, messages: List[Dict[str, str]]) -> str:
        """Generate a response given conversation history."""
        prompt = self._build_conversation_prompt(messages)
        raw = self.client.generate(prompt)
        clean, thinking = parse_thinking(raw, strip_unclosed=self._hide_thinking)
        if thinking is not None:
            emit_rfc_data("thinking_text", thinking)
        return clean

    @keyword("Run Multi Turn Conversation")
    def run_multi_turn_conversation(self, turns: List[Dict[str, str]]) -> List[str]:
        """Run a multi-turn conversation, generating LLM responses incrementally.

        Walks through the turn list. User turns are added to history as-is.
        When a user turn is followed by another user turn (or is the last
        turn), an LLM response is generated and inserted before proceeding.
        Scripted assistant turns are added to history without calling the LLM.

        Args:
            turns: List of dicts with 'role' ('user', 'assistant', 'system')
                   and 'content' keys.

        Returns:
            List of all LLM-generated responses (in order).
        """
        history: List[Dict[str, str]] = []
        generated_responses: List[str] = []

        for i, turn in enumerate(turns):
            role = turn.get("role", "user")
            content = turn.get("content", "")

            if role == "system":
                history.append({"role": "system", "content": content})
                continue

            if role == "assistant":
                history.append({"role": "assistant", "content": content})
                continue

            # User turn — add to history
            history.append({"role": "user", "content": content})

            # Skip generation when the next turn is scripted (assistant)
            # or a system instruction — only generate when the next turn
            # is another user turn or this is the last turn.
            next_role = turns[i + 1].get("role", "user") if i + 1 < len(turns) else None
            should_generate = next_role not in ("assistant", "system")

            if should_generate:
                # Generate LLM response
                response = self._generate_response(history)
                logger.info(f"Turn {i + 1} response: {response}")
                emit_rfc_data(f"turn_{len(generated_responses) + 1}_response", response)
                if not response or not response.strip():
                    # Surface empty turns explicitly so downstream
                    # graders and reports can distinguish "model said
                    # nothing" from a substantive turn.
                    logger.warn(
                        f"Turn {i + 1} returned empty content — recording "
                        "for visibility; downstream graders will fail it."
                    )
                    emit_rfc_data(f"turn_{len(generated_responses) + 1}_empty", "true")
                history.append({"role": "assistant", "content": response})
                generated_responses.append(response)

        emit_rfc_data("total_generated_responses", str(len(generated_responses)))
        return generated_responses

    @keyword("Grade Fact Consistency")
    def grade_fact_consistency(
        self,
        fact_description: str,
        responses: List[str],
        probe_indices: List[int],
    ) -> Tuple[float, str]:
        """Grade whether LLM responses are consistent about a stated fact.

        Args:
            fact_description: The fact established in the conversation.
            responses: All LLM-generated responses from the conversation.
            probe_indices: 0-based indices of responses that were probed
                          for the fact.

        Returns:
            Tuple of (score, reason). Score 1.0 = fully consistent.
        """
        indices = [int(i) for i in probe_indices]
        result = self.grader.grade_fact_consistency(
            fact_description, responses, indices
        )
        emit_rfc_data("consistency_score", str(result.score))
        emit_rfc_data("consistency_reason", result.reason)
        return result.score, result.reason

    @keyword("Score Instruction Compliance Batch")
    def score_instruction_compliance_batch(
        self,
        constraint: str,
        responses: List[str],
    ) -> Tuple[float, str]:
        """Score how many responses comply with an instruction constraint.

        Grades each response individually and returns the compliance ratio
        along with a summary of per-turn results.

        Args:
            constraint: The instruction constraint to check against.
            responses: List of LLM responses to evaluate.

        Returns:
            Tuple of (compliance_ratio, summary).
            compliance_ratio is 0.0-1.0 representing the fraction of
            turns that scored >= 0.5.
        """
        compliant_count = 0
        per_turn: List[str] = []

        for i, response in enumerate(responses):
            result = self.grader.grade_instruction_compliance(constraint, response)
            is_compliant = result.score >= 0.5
            if is_compliant:
                compliant_count += 1
            status = "PASS" if is_compliant else "FAIL"
            per_turn.append(
                f"Turn {i + 1}: {status} (score={result.score:.2f}, {result.reason})"
            )
            logger.info(per_turn[-1])
            emit_rfc_data(f"compliance_turn_{i + 1}_score", str(result.score))

        ratio = compliant_count / len(responses) if responses else 0.0
        summary = f"{compliant_count}/{len(responses)} turns compliant\n" + "\n".join(
            per_turn
        )
        emit_rfc_data("compliance_ratio", str(ratio))
        emit_rfc_data("compliance_summary", summary)
        return ratio, summary

    @keyword("Grade Topic Isolation")
    def grade_topic_isolation(
        self,
        prior_topic: str,
        new_topic: str,
        response: str,
    ) -> Tuple[float, str]:
        """Grade whether a response avoids bleeding prior topic context.

        Args:
            prior_topic: Description of the prior conversation topic.
            new_topic: Description of the new topic after the switch.
            response: The LLM's response to evaluate.

        Returns:
            Tuple of (score, reason). Score 1.0 = no bleed.
        """
        result = self.grader.grade_topic_isolation(prior_topic, new_topic, response)
        emit_rfc_data("topic_isolation_score", str(result.score))
        emit_rfc_data("topic_isolation_reason", result.reason)
        return result.score, result.reason

    @keyword("Grade Topic Isolation Sliding Window")
    def grade_topic_isolation_sliding_window(
        self,
        prior_topic: str,
        new_topic: str,
        responses: List[str],
        window_start: int,
    ) -> Tuple[float, str]:
        """Grade topic isolation across a sliding window of responses.

        Evaluates all responses from window_start onward (the post-switch
        responses) and returns the average isolation score.

        Args:
            prior_topic: Description of the prior conversation topic.
            new_topic: Description of the new topic after the switch.
            responses: All LLM-generated responses from the conversation.
            window_start: 0-based index of the first post-switch response.

        Returns:
            Tuple of (average_score, summary).
        """
        window_start = int(window_start)
        post_switch = responses[window_start:]
        if not post_switch:
            raise ValueError(
                f"window_start={window_start} is beyond the "
                f"{len(responses)} available responses — no post-switch "
                f"turns to evaluate. Check scenario configuration."
            )

        scores: List[float] = []
        per_turn: List[str] = []

        for i, response in enumerate(post_switch):
            result = self.grader.grade_topic_isolation(prior_topic, new_topic, response)
            scores.append(result.score)
            turn_num = window_start + i + 1
            per_turn.append(
                f"Turn {turn_num}: score={result.score:.2f}, {result.reason}"
            )
            logger.info(per_turn[-1])
            emit_rfc_data(f"isolation_turn_{turn_num}_score", str(result.score))

        avg = sum(scores) / len(scores)
        summary = f"Average isolation: {avg:.2f}\n" + "\n".join(per_turn)
        emit_rfc_data("isolation_avg_score", str(avg))
        emit_rfc_data("isolation_summary", summary)
        return avg, summary
