import json
from typing import Any, Dict, List, Optional, Tuple

from robot.api import logger
from robot.api.deco import keyword

from .grader import Grader
from .llm_client import create_provider, resolve_timeout
from .ollama import OllamaClient
from .rfc_data import emit_rfc_data
from .thinking import estimate_token_count, parse_thinking


class LLMKeywords:
    """
    Robot Framework keywords for testing LLMs.
    """

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_retries: int = 2,
        hide_thinking: bool = True,
    ):
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))
        self.grader = Grader(self.client)
        self._hide_thinking: bool = (
            hide_thinking.lower() not in ("false", "0", "no")
            if isinstance(hide_thinking, str)
            else bool(hide_thinking)
        )

    @keyword("Set LLM Endpoint")
    def set_llm_endpoint(self, endpoint: str):
        """Set the LLM endpoint URL.

        For Ollama providers, updates the base URL. For OpenAI-compatible
        providers, updates the base_url used for API calls.
        """
        logger.info(endpoint)
        if isinstance(self.client, OllamaClient):
            self.client.endpoint = endpoint
        elif hasattr(self.client, "base_url"):
            self.client.base_url = endpoint.rstrip("/")  # type: ignore[attr-defined]
        else:
            logger.warn("Set LLM Endpoint not supported for this provider")

    @keyword("Set LLM Model")
    def set_llm_model(self, model: str):
        logger.info(model)
        self.client.model = model

    @keyword("Set LLM Parameters")
    def set_llm_parameters(
        self,
        temperature: float = 0.0,
        max_tokens: int = 256,
        seed: Optional[int] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        num_ctx: Optional[int] = None,
        keep_alive: Optional[str] = None,
    ) -> None:
        self.client.temperature = float(temperature)
        self.client.max_tokens = int(max_tokens)
        if seed is not None:
            self.client.seed = int(seed)
        if top_p is not None:
            self.client.top_p = float(top_p)
        if top_k is not None:
            self.client.top_k = int(top_k)
        if num_ctx is not None:
            self.client.num_ctx = int(num_ctx)
        if keep_alive is not None:
            self.client.keep_alive = str(keep_alive)

    @keyword("Ask LLM")
    def ask_llm(self, prompt: str) -> str:
        logger.info(prompt)
        raw_response = self.client.generate(prompt)
        clean_answer, thinking_text = parse_thinking(
            raw_response, strip_unclosed=self._hide_thinking
        )
        logger.info(clean_answer)
        emit_rfc_data("actual_answer", clean_answer)
        if thinking_text is not None:
            emit_rfc_data("thinking_text", thinking_text)
            thinking_tokens = estimate_token_count(thinking_text)
            emit_rfc_data("thinking_tokens", str(thinking_tokens))
        if self.client.num_ctx is not None:
            emit_rfc_data("num_ctx", str(self.client.num_ctx))
        if self.client.max_tokens is not None:
            emit_rfc_data("num_predict", str(self.client.max_tokens))
        if self.client.last_metrics is not None:
            self.client.last_metrics["prompt_text"] = prompt
            if self.client.num_ctx is not None:
                self.client.last_metrics["num_ctx"] = self.client.num_ctx
            self.client.last_metrics["num_predict"] = self.client.max_tokens
            emit_rfc_data("llm_metrics", json.dumps(self.client.last_metrics))
        return clean_answer

    @keyword("Unload Model")
    def unload_model(self, model: Optional[str] = None) -> bool:
        """Unload a model from Ollama VRAM.

        Args:
            model: Model name to unload. Defaults to current model.

        Returns:
            True if unloaded successfully.
        """
        if not isinstance(self.client, OllamaClient):
            logger.warn("Unload Model is only supported for Ollama providers")
            return False
        return self.client.unload_model(model)

    # Hard ceiling: no retry should exceed this token count.
    _MAX_TOKEN_CEILING = 131072

    @keyword("Ask And Grade With Retry")
    def ask_and_grade_with_retry(
        self,
        prompt: str,
        expected: str,
        grading_question: Optional[str] = None,
        max_retries: int = 3,
    ) -> Tuple[float, str, str]:
        """Ask the LLM and grade; retry with 8x tokens on wrong non-empty answers.

        When the model responds with a non-empty answer that fails grading,
        this keyword multiplies ``max_tokens`` by 8 and retries — up to
        *max_retries* times (e.g. 256 → 2048 → 16384 → 131072).  Empty
        responses are never retried (they indicate a different problem, not
        a token budget issue).

        Token scaling is capped at ``_MAX_TOKEN_CEILING`` (131072) to avoid
        exceeding provider limits.

        Args:
            prompt: The full prompt to send to the LLM (may be large).
            expected: The expected answer for grading.
            grading_question: A shorter question passed to the grader instead
                of the full prompt.  Defaults to *prompt* when not provided.
                Use this when the prompt contains large context (e.g. legal
                agreements) that should not be sent to the grader.
            max_retries: Maximum number of retries with 8x tokens (default 3).

        Returns:
            A tuple of ``(score, reason, answer)`` from the final attempt.
        """
        max_retries = int(max_retries)
        original_max_tokens = self.client.max_tokens
        retries_used = 0
        grade_q = grading_question if grading_question is not None else prompt

        for attempt in range(1 + max_retries):
            answer = self.ask_llm(prompt)
            result = self.grader.grade(grade_q, expected, answer)
            emit_rfc_data("score", str(result.score))
            emit_rfc_data("expected_answer", expected)
            emit_rfc_data("grading_reason", result.reason)

            if result.score >= 1.0:
                # Success — emit retry metadata and return
                emit_rfc_data("token_retry_count", str(retries_used))
                emit_rfc_data("token_retry_max_tokens", str(self.client.max_tokens))
                logger.info(
                    f"Grading passed on attempt {attempt + 1} "
                    f"(max_tokens={self.client.max_tokens})"
                )
                return result.score, result.reason, answer

            # Non-empty but wrong — 8x tokens and retry (capped)
            if answer.strip() and attempt < max_retries:
                retries_used += 1
                new_tokens = self.client.max_tokens * 8
                self.client.max_tokens = min(new_tokens, self._MAX_TOKEN_CEILING)
                logger.warn(
                    f"Grading failed (score={result.score}) with non-empty "
                    f"response on attempt {attempt + 1}. "
                    f"Retrying with max_tokens={self.client.max_tokens} "
                    f"({max_retries - retries_used} retries left)"
                )
                continue

            # Empty response or exhausted retries — return failure
            break

        emit_rfc_data("token_retry_count", str(retries_used))
        emit_rfc_data("token_retry_max_tokens", str(self.client.max_tokens))
        logger.info(
            f"Grading failed after {retries_used} retries "
            f"(final max_tokens={self.client.max_tokens}, "
            f"original={original_max_tokens})"
        )
        return result.score, result.reason, answer

    @keyword("Grade Answer")
    def grade_answer(self, question: str, expected: str, actual: str):
        result = self.grader.grade(question, expected, actual)
        emit_rfc_data("score", str(result.score))
        emit_rfc_data("expected_answer", expected)
        emit_rfc_data("grading_reason", result.reason)
        return result.score, result.reason

    @keyword("Wait For LLM")
    def wait_for_llm(self, timeout: int = 5400, poll_interval: int = 2) -> bool:
        """Wait until the LLM is available and not busy.

        For Ollama providers, polls the /api/ps endpoint to detect when
        no models are actively processing requests. For other providers,
        returns True immediately (no queue detection available).

        Args:
            timeout: Maximum seconds to wait (default 5400 / 90 min).
            poll_interval: Seconds between polling attempts (default 2).

        Returns:
            True when the LLM is ready.

        Raises:
            TimeoutError: If Ollama is still busy after timeout.

        Example:
            | Wait For LLM | timeout=60 |
            | ${answer}= | Ask LLM | What is 2 + 2? |
        """
        if not isinstance(self.client, OllamaClient):
            logger.info("Non-Ollama provider — skipping wait (always ready)")
            return True
        timeout = int(timeout)
        poll_interval = int(poll_interval)
        logger.info(
            f"Waiting for Ollama to be ready (timeout={timeout}s, "
            f"poll={poll_interval}s)"
        )
        return self.client.wait_until_ready(timeout, poll_interval)

    @keyword("Get Running Models")
    def get_running_models(self) -> List[Dict[str, Any]]:
        """Get the list of models currently loaded/running.

        Only available for Ollama providers. Returns an empty list
        for other providers.

        Returns:
            List of model info dicts from Ollama's /api/ps response.

        Example:
            | ${models}= | Get Running Models |
            | Log | Currently running: ${models} |
        """
        if not isinstance(self.client, OllamaClient):
            logger.info("Non-Ollama provider — running models not available")
            return []
        models = self.client.running_models()
        logger.info(f"Running models: {models}")
        return models

    @keyword("LLM Is Busy")
    def llm_is_busy(self) -> bool:
        """Check if the LLM currently has models loaded and running.

        Only available for Ollama providers. Returns False for other
        providers.

        Returns:
            True if Ollama has active models, False otherwise.

        Example:
            | ${busy}= | LLM Is Busy |
            | Run Keyword If | ${busy} | Wait For LLM |
        """
        if not isinstance(self.client, OllamaClient):
            logger.info("Non-Ollama provider — busy check not available")
            return False
        busy = self.client.is_busy()
        logger.info(f"Ollama busy: {busy}")
        return busy
