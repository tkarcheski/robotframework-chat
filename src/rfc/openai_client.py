"""OpenAI Chat Completions API client for LLM generation."""

import os
from typing import Any, Dict, Optional

from robot.api import logger
import requests

from .constants import DEFAULT_TIMEOUT
from .provider_budget import record_env_request
from .retry import retry_on_transient


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
            response = requests.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            # Count every attempt that reached the provider — including 429s
            # that get retried — so the daily budget reflects real spend (#515).
            record_env_request()
            response.raise_for_status()
            data = response.json()
            text = data["choices"][0]["message"]["content"].strip()
            self.last_metrics = _extract_metrics(data, self.model)
            logger.info(f"{self.model} >> {text}")
            return text

        return retry_on_transient(_do_request, max_retries=self.max_retries)


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
