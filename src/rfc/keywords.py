import json
import os
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, Tuple, Union

from robot.api import logger
from robot.api.deco import keyword

from .exceptions import EmptyLLMResponseError, ModelNotReadyError
from .grader import Grader
from .llm_client import (
    as_ollama,
    create_judge_provider,
    create_provider,
    resolve_timeout,
    unwrap_provider,
)
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
        hide_thinking: bool | str = True,
    ):
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))
        self.grader = Grader(
            create_judge_provider(
                self.client, timeout=timeout, max_retries=int(max_retries)
            )
        )
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
        ollama = as_ollama(self.client)
        if ollama is not None:
            ollama.endpoint = endpoint
        elif hasattr(self.client, "base_url"):
            self.client.base_url = endpoint.rstrip("/")  # type: ignore[attr-defined]
        else:
            logger.warn("Set LLM Endpoint not supported for this provider")

    @keyword("Set LLM Model")
    def set_llm_model(self, model: str):
        logger.info(model)
        self.client.model = model

    @keyword("Save LLM Model")
    def save_llm_model(self) -> str:
        """Remember the current model so `Restore LLM Model` can put it back.

        Used by the generative fork flow (#359): fork copies switch models
        mid-suite, and without a restore every later test would silently
        run against the last fork model.
        """
        self._saved_model = self.client.model
        logger.info(f"Saved LLM model: {self._saved_model}")
        return self._saved_model

    @keyword("Restore LLM Model")
    def restore_llm_model(self) -> str:
        """Switch back to the model captured by `Save LLM Model` (no-op if
        nothing was saved)."""
        saved = getattr(self, "_saved_model", "")
        if saved:
            self.client.model = saved
            logger.info(f"Restored LLM model: {saved}")
        else:
            logger.warn("Restore LLM Model called without a prior Save LLM Model")
        return saved

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
        think: Union[bool, str, None] = None,
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
        # `think` toggles reasoning-model output (issue #131). It is an
        # Ollama-only control, so set it on the concrete Ollama client (through
        # any cache wrapper); the property there normalizes/validates
        # ("true"/"false"/"1"/"0" or low/medium/high). Other providers ignore it.
        if think is not None:
            ollama = as_ollama(self.client)
            if ollama is not None:
                ollama.think = think
            else:
                logger.info("Set LLM Parameters: 'think' is Ollama-only; ignoring")

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
        self._emit_dialog_turns(prompt, clean_answer)
        return clean_answer

    # Env flag set by rfc.dialog_recorder.DialogRecorder (kept as a literal
    # here to avoid importing the recorder into every LLMKeywords user).
    _DIALOG_RECORDING_ENV_VAR = "RFC_DIALOG_RECORDING_ID"

    def _emit_dialog_turns(self, prompt: str, answer: str) -> None:
        """Emit dialog_turn events when a recording bracket is active (#354)."""
        recording_id = os.environ.get(self._DIALOG_RECORDING_ENV_VAR, "")
        if not recording_id:
            return
        timestamp = datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z"
        emit_rfc_data(
            "dialog_turn",
            json.dumps(
                {
                    "recording_id": recording_id,
                    "role": "user",
                    "content": prompt,
                    "timestamp": timestamp,
                }
            ),
        )
        assistant_turn: Dict[str, Any] = {
            "recording_id": recording_id,
            "role": "assistant",
            "content": answer,
            "timestamp": timestamp,
        }
        metrics = self.client.last_metrics or {}
        if metrics.get("prompt_eval_count") is not None:
            assistant_turn["prompt_tokens"] = int(metrics["prompt_eval_count"])
        if metrics.get("eval_count") is not None:
            assistant_turn["completion_tokens"] = int(metrics["eval_count"])
        if metrics.get("total_duration_ns") is not None:
            assistant_turn["latency_ms"] = float(metrics["total_duration_ns"]) / 1e6
        emit_rfc_data("dialog_turn", json.dumps(assistant_turn))

    @keyword("Unload Model")
    def unload_model(self, model: Optional[str] = None) -> bool:
        """Unload a model from Ollama VRAM.

        Args:
            model: Model name to unload. Defaults to current model.

        Returns:
            True if unloaded successfully.
        """
        ollama = as_ollama(self.client)
        if ollama is None:
            logger.warn("Unload Model is only supported for Ollama providers")
            return False
        return ollama.unload_model(model)

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

            # Empty response or exhausted retries
            break

        emit_rfc_data("token_retry_count", str(retries_used))
        emit_rfc_data("token_retry_max_tokens", str(self.client.max_tokens))

        if not answer.strip():
            logger.info(
                f"LLM returned empty response — skipping "
                f"(max_tokens={self.client.max_tokens})"
            )
            raise EmptyLLMResponseError(
                model=getattr(self.client, "model", "unknown"),
                prompt_snippet=prompt[:80],
            )

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
        ollama = as_ollama(self.client)
        if ollama is None:
            logger.info("Non-Ollama provider — skipping wait (always ready)")
            return True
        timeout = int(timeout)
        poll_interval = int(poll_interval)
        logger.info(
            f"Waiting for Ollama to be ready (timeout={timeout}s, "
            f"poll={poll_interval}s)"
        )
        return ollama.wait_until_ready(timeout, poll_interval)

    @keyword("Ensure Model Ready")
    def ensure_model_ready(self, timeout: Optional[int] = None) -> None:
        """Verify the provider is online and the model is loaded / served.

        Provider-aware pre-flight for a Suite Setup: Ollama warms the model
        into VRAM and proves it emits tokens; vLLM / OpenAI-compatible servers
        confirm the ``/models`` catalog is reachable. On failure it raises an
        ``RFCSkipError`` subclass (``ROBOT_SKIP_EXECUTION``), so the suite is
        *skipped* rather than recording false-positive failures from an empty
        cold-load response.

        Args:
            timeout: Max seconds to wait for readiness. Defaults via
                ``resolve_timeout`` (``OLLAMA_TIMEOUT`` env, then 5400s).

        Raises:
            ProviderOfflineError: endpoint unreachable.
            ModelNotReadyError: model could not be loaded / warm-up was empty.
            OllamaTimeoutError / OllamaModelNotFoundError: Ollama-specific.

        Example:
            | Ensure Model Ready | timeout=120 |
        """
        provider = unwrap_provider(self.client)
        resolved = resolve_timeout(timeout)
        ensure = getattr(provider, "ensure_ready", None)
        if ensure is not None:
            ensure(timeout=resolved)
            return
        # Generic fallback for a provider without a readiness method: a single
        # warm-up generate doubles as load + liveness probe.
        answer = self.client.generate("ping")
        if not answer.strip():
            raise ModelNotReadyError(
                getattr(self.client, "model", "unknown"),
                getattr(self.client, "base_url", "unknown"),
                "warm-up returned empty response",
            )

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
        ollama = as_ollama(self.client)
        if ollama is None:
            logger.info("Non-Ollama provider — running models not available")
            return []
        models = ollama.running_models()
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
        ollama = as_ollama(self.client)
        if ollama is None:
            logger.info("Non-Ollama provider — busy check not available")
            return False
        busy = ollama.is_busy()
        logger.info(f"Ollama busy: {busy}")
        return busy
