"""OpenAI Chat Completions API client for LLM generation."""

import os
from typing import Any, Dict, Optional

from robot.api import logger
import requests

from .constants import DEFAULT_TIMEOUT
from .exceptions import ModelNotReadyError, ProviderOfflineError
from .provider_budget import record_env_request
from .retry import retry_on_transient

#: Timeout (seconds) for the lightweight /models readiness probe.
_ONLINE_PROBE_TIMEOUT = 10


class OpenAIClient:
    """HTTP client for the OpenAI Chat Completions API.

    Works with OpenAI, Azure OpenAI, and any OpenAI-compatible API
    (Together, Groq, Fireworks, etc.) by setting base_url.
    """

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        model: str = "",
        temperature: float = 0.0,
        max_tokens: int = 256,
        timeout: Optional[int] = None,
        max_retries: int = 2,
        seed: Optional[int] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        num_ctx: Optional[int] = None,
        keep_alive: Optional[str] = None,
        response_format: Optional[str] = None,
    ):
        if not base_url:
            base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        if not api_key:
            api_key = os.getenv("OPENAI_API_KEY", "")
        if not model:
            model = os.getenv("DEFAULT_MODEL", "gpt-4o-mini")
        if timeout is None:
            timeout = int(os.getenv("OPENAI_TIMEOUT", str(DEFAULT_TIMEOUT)))

        if not isinstance(base_url, str) or not base_url:
            raise ValueError("base_url must be a non-empty string")
        if not isinstance(api_key, str) or not api_key:
            raise ValueError(
                "api_key must be a non-empty string. "
                "Set OPENAI_API_KEY environment variable or pass api_key parameter."
            )
        if not isinstance(model, str) or not model:
            raise ValueError("model must be a non-empty string")
        if temperature < 0:
            raise ValueError(f"temperature must be >= 0, got {temperature}")
        if max_tokens < 1:
            raise ValueError(f"max_tokens must be >= 1, got {max_tokens}")
        if timeout < 1:
            raise ValueError(f"timeout must be >= 1, got {timeout}")
        if max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got {max_retries}")
        if response_format is not None and response_format != "json":
            raise ValueError(
                f"response_format must be None or 'json', got {response_format!r}"
            )

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self.seed = seed
        self.top_p = top_p
        self.top_k = top_k
        self.num_ctx = num_ctx  # Not used by OpenAI, kept for protocol compliance
        self.keep_alive = keep_alive  # Not used by OpenAI, kept for protocol compliance
        self.response_format = response_format
        self.last_metrics: Optional[Dict[str, Any]] = None

    def generate(self, prompt: str) -> str:
        """Send a prompt to the OpenAI Chat Completions API and return the response.

        Uses the /chat/completions endpoint with a single user message.
        Retries on transient errors with exponential backoff.

        Args:
            prompt: The text prompt to send.

        Returns:
            The generated text response, stripped of whitespace.
        """
        if not isinstance(prompt, str):
            raise TypeError(f"prompt must be a str, got {type(prompt).__name__}")
        if not prompt.strip():
            raise ValueError("prompt must be a non-empty string")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.seed is not None:
            payload["seed"] = self.seed
        if self.top_p is not None:
            payload["top_p"] = self.top_p
        if self.top_k is not None:
            payload["top_k"] = self.top_k
        if self.response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        self.last_metrics = None

        def _do_request() -> str:
            # Count BEFORE the call so an attempt that raises (ReadTimeout
            # after the request reached the provider, a 429 that retry_on_
            # transient retries) still counts toward the daily budget — those
            # all consume the provider's allowance (#515).
            record_env_request()
            response = requests.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            text = data["choices"][0]["message"]["content"].strip()
            self.last_metrics = _extract_metrics(data, self.model)
            logger.info(f"{self.model} >> {text}")
            return text

        return retry_on_transient(_do_request, max_retries=self.max_retries)

    def is_online(self) -> bool:
        """Return True if the provider endpoint is reachable and serving.

        Queries the OpenAI-compatible ``{base_url}/models`` catalog with a short
        timeout. Works for OpenAI, vLLM (``/v1/models``), and other compatible
        servers. Any non-200 or network error counts as offline (fail-closed).
        """
        try:
            response = requests.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=_ONLINE_PROBE_TIMEOUT,
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    def ensure_ready(
        self, *, timeout: Optional[int] = None, warmup: bool = False
    ) -> None:
        """Verify the provider is online (and optionally serving the model).

        OpenAI-compatible servers (OpenAI, vLLM, external APIs) load their model
        at startup, so the ``/models`` probe is the readiness gate. *warmup*
        defaults to False to avoid spending a paid/budgeted request; pass True
        to additionally confirm the model emits tokens.

        Raises (``RFCSkipError`` subclasses → test/suite *skipped*, not failed):
            ProviderOfflineError: ``/models`` unreachable or non-200.
            ModelNotReadyError: warm-up returned an empty response.
        """
        del timeout  # online probe uses its own short timeout
        if not self.is_online():
            raise ProviderOfflineError("OpenAI-compatible", self.base_url)
        if not warmup:
            return
        answer = self.generate("ping")
        if not answer.strip():
            raise ModelNotReadyError(
                self.model, self.base_url, "warm-up returned empty response"
            )
        logger.info(f"Model ready: {self.model} online and responding.")


def _extract_metrics(data: Dict[str, Any], model: str) -> Dict[str, Any]:
    """Extract usage metrics from an OpenAI chat completions response.

    Maps prompt_tokens/completion_tokens to Ollama-equivalent names
    (prompt_eval_count/eval_count) for database compatibility. Also
    extracts nested detail fields: reasoning_tokens, cached_tokens,
    accepted_prediction_tokens, rejected_prediction_tokens.
    """
    usage = data.get("usage", {})
    prompt_details = usage.get("prompt_tokens_details") or {}
    completion_details = usage.get("completion_tokens_details") or {}
    return {
        "model_name": model,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        # Map to Ollama-equivalent names for DB compatibility
        "prompt_eval_count": usage.get("prompt_tokens"),
        "eval_count": usage.get("completion_tokens"),
        # Detailed breakdowns
        "reasoning_tokens": completion_details.get("reasoning_tokens"),
        "cached_tokens": prompt_details.get("cached_tokens"),
        "accepted_prediction_tokens": completion_details.get(
            "accepted_prediction_tokens"
        ),
        "rejected_prediction_tokens": completion_details.get(
            "rejected_prediction_tokens"
        ),
    }
