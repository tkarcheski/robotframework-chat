"""Robot Framework keywords for LLM creativity and humor testing.

Provides keywords for joke generation, conversational context testing,
and creativity grading with automatic token escalation on failure.
"""

from typing import Any, Dict, List, Optional, Tuple

from robot.api import logger
from robot.api.deco import keyword

from .creativity_grader import CreativityGrader
from .exceptions import EmptyLLMResponseError
from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data
from .thinking import parse_thinking


# Hard ceiling: no retry should exceed this token count.
_MAX_TOKEN_CEILING = 131072

# Prompt enrichment hints added on successive retries.
_RETRY_HINTS = [
    "",
    "\n\nBe more creative and detailed in your response. "
    "Make the joke unique and original.",
    "\n\nPut extra effort into creativity. Use wordplay, unexpected twists, "
    "or clever observations. Make sure the joke is complete with a clear "
    "setup and punchline. Be detailed and expressive.",
    "\n\nThis is your final attempt. Write the most creative, original, and "
    "hilarious joke you can. Use vivid language, clever wordplay, and an "
    "unexpected punchline. The joke should be memorable and unique.",
]


class CreativityKeywords:
    """Robot Framework keywords for testing LLM creativity and humor."""

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_retries: int = 2,
        hide_thinking: bool = True,
    ) -> None:
        timeout = resolve_timeout(timeout)
        self.client: Any = create_provider(
            timeout=timeout, max_retries=int(max_retries)
        )
        self.creativity_grader = CreativityGrader(self.client)
        self._hide_thinking: bool = (
            hide_thinking.lower() not in ("false", "0", "no")
            if isinstance(hide_thinking, str)
            else bool(hide_thinking)
        )

    @keyword("Ask For Joke")
    def ask_for_joke(self, prompt: str, max_tokens: int = 512) -> str:
        """Ask the LLM to generate a joke with creativity-tuned parameters.

        Sets temperature to 0.7 for creative generation, then restores
        the original temperature after the call.

        Args:
            prompt: The joke prompt to send to the LLM.
            max_tokens: Maximum tokens for the response.

        Returns:
            The joke text produced by the LLM.
        """
        logger.info(f"Asking for joke: {prompt}")
        original_temperature = self.client.temperature
        original_max_tokens = self.client.max_tokens

        self.client.temperature = 0.7
        self.client.max_tokens = int(max_tokens)

        try:
            raw_response = self.client.generate(prompt)
            clean_answer, thinking_text = parse_thinking(
                raw_response, strip_unclosed=self._hide_thinking
            )
            logger.info(f"Joke response: {clean_answer}")
            emit_rfc_data("joke_response", clean_answer)
            emit_rfc_data("actual_answer", clean_answer)
            if thinking_text is not None:
                emit_rfc_data("thinking_text", thinking_text)
            return clean_answer
        finally:
            self.client.temperature = original_temperature
            self.client.max_tokens = original_max_tokens

    @keyword("Ask With Conversation")
    def ask_with_conversation(self, messages: List[Dict[str, str]]) -> str:
        """Send a multi-turn conversation to the LLM and get the response.

        Builds a single prompt from the conversation history and asks the
        LLM to continue. This simulates multi-turn context awareness.

        Args:
            messages: List of dicts with 'role' and 'content' keys.
                      Roles: 'user', 'assistant', 'system'.

        Returns:
            The LLM's response to the final message in the conversation.
        """
        prompt = self._build_conversation_prompt(messages)
        logger.info(f"Conversation prompt:\n{prompt}")

        raw_response = self.client.generate(prompt)
        clean_answer, thinking_text = parse_thinking(
            raw_response, strip_unclosed=self._hide_thinking
        )
        logger.info(f"Conversation response: {clean_answer}")
        emit_rfc_data("conversation_response", clean_answer)
        emit_rfc_data("actual_answer", clean_answer)
        if thinking_text is not None:
            emit_rfc_data("thinking_text", thinking_text)
        return clean_answer

    @keyword("Grade Joke")
    def grade_joke(
        self, prompt: str, joke: str, expected_traits: str
    ) -> Tuple[float, str]:
        """Grade a joke on humor, creativity, originality, and relevance.

        Args:
            prompt: The original joke prompt.
            joke: The joke text to grade.
            expected_traits: Description of expected traits.

        Returns:
            Tuple of (score, reason).
        """
        result = self.creativity_grader.grade_joke(prompt, joke, expected_traits)
        emit_rfc_data("score", str(result.score))
        emit_rfc_data("grading_reason", result.reason)
        return result.score, result.reason

    @keyword("Grade Context Awareness")
    def grade_context_awareness(
        self,
        scenario_description: str,
        conversation: Any,
        response: str,
        expected: str,
    ) -> Tuple[float, str]:
        """Grade whether the LLM maintained conversational context.

        Args:
            scenario_description: What this test is checking.
            conversation: The conversation history (string or list of message dicts).
            response: The LLM's response to evaluate.
            expected: What the response should demonstrate.

        Returns:
            Tuple of (score, reason).
        """
        if isinstance(conversation, list):
            conversation = self._build_conversation_prompt(conversation)
        result = self.creativity_grader.grade_context(
            scenario_description, str(conversation), response, expected
        )
        emit_rfc_data("score", str(result.score))
        emit_rfc_data("grading_reason", result.reason)
        return result.score, result.reason

    @keyword("Ask And Grade Joke With Retry")
    def ask_and_grade_joke_with_retry(
        self,
        prompt: str,
        expected_traits: str,
        max_retries: int = 3,
    ) -> Tuple[float, str, str]:
        """Ask for a joke and grade it; retry with more tokens and richer prompts.

        On failure, both increases max_tokens by 8x AND enriches the prompt
        with more specific creative instructions.

        Args:
            prompt: The joke prompt.
            expected_traits: Traits to grade against.
            max_retries: Maximum number of retries (default 3).

        Returns:
            Tuple of (score, reason, joke) from the final attempt.
        """
        max_retries = int(max_retries)
        current_max_tokens = 512
        retries_used = 0

        for attempt in range(1 + max_retries):
            hint_idx = min(attempt, len(_RETRY_HINTS) - 1)
            enriched_prompt = prompt + _RETRY_HINTS[hint_idx]

            joke = self.ask_for_joke(enriched_prompt, max_tokens=current_max_tokens)
            score, reason = self.grade_joke(prompt, joke, expected_traits)

            if score >= 0.5:
                emit_rfc_data("token_retry_count", str(retries_used))
                emit_rfc_data("token_retry_max_tokens", str(current_max_tokens))
                logger.info(
                    f"Joke grading passed on attempt {attempt + 1} "
                    f"(max_tokens={current_max_tokens})"
                )
                return score, reason, joke

            # Non-empty but low score — escalate tokens and enrich prompt
            if joke.strip() and attempt < max_retries:
                retries_used += 1
                new_tokens = current_max_tokens * 8
                current_max_tokens = min(new_tokens, _MAX_TOKEN_CEILING)
                logger.warn(
                    f"Joke grading failed (score={score}) on attempt "
                    f"{attempt + 1}. Retrying with max_tokens="
                    f"{current_max_tokens} ({max_retries - retries_used} "
                    f"retries left)"
                )
                continue

            # Empty response or exhausted retries
            break

        emit_rfc_data("token_retry_count", str(retries_used))
        emit_rfc_data("token_retry_max_tokens", str(current_max_tokens))

        if not joke.strip():
            logger.info(
                f"LLM returned empty joke — skipping "
                f"(max_tokens={current_max_tokens})"
            )
            raise EmptyLLMResponseError(
                model=getattr(self.client, "model", "unknown"),
                prompt_snippet=prompt[:80],
            )

        logger.info(
            f"Joke grading failed after {retries_used} retries "
            f"(final max_tokens={current_max_tokens})"
        )
        return score, reason, joke

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
