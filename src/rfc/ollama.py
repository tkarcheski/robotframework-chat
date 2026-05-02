"""Ollama API client for LLM generation and model discovery."""

import os
import time
from typing import Any, Dict, List, Optional

from robot.api import logger
import requests

from .constants import DEFAULT_TIMEOUT
from .exceptions import OllamaModelNotFoundError, OllamaTimeoutError
from .retry import retry_on_transient


def _check_model_not_found(
    response: requests.Response, model: str, endpoint: str
) -> None:
    """Raise OllamaModelNotFoundError on 404, else call raise_for_status()."""
    if response.status_code == 404:
        detail = ""
        try:
            detail = response.json().get("error", "")
        except Exception:
            pass
        raise OllamaModelNotFoundError(model, endpoint, detail)
    response.raise_for_status()


def _compute_rate(count: Optional[int], duration_ns: Optional[int]) -> Optional[float]:
    """Compute tokens/s from token count and nanosecond duration."""
    if count is None or duration_ns is None or duration_ns <= 0:
        return None
    return round(count / (duration_ns / 1e9), 2)


def _extract_metrics(data: Dict[str, Any], model: str) -> Dict[str, Any]:
    """Extract performance metrics from an Ollama generate response."""
    prompt_eval_count = data.get("prompt_eval_count")
    prompt_eval_duration = data.get("prompt_eval_duration")
    eval_count = data.get("eval_count")
    eval_duration = data.get("eval_duration")

    return {
        "model_name": model,
        "total_duration_ns": data.get("total_duration"),
        "load_duration_ns": data.get("load_duration"),
        "prompt_eval_count": prompt_eval_count,
        "prompt_eval_duration_ns": prompt_eval_duration,
        "prompt_eval_rate": _compute_rate(prompt_eval_count, prompt_eval_duration),
        "eval_count": eval_count,
        "eval_duration_ns": eval_duration,
        "eval_rate": _compute_rate(eval_count, eval_duration),
    }


class OllamaClient:
    """HTTP client for the Ollama API.

    Handles both text generation and model discovery, providing a single
    integration point for all Ollama interactions.
    """

    def __init__(
        self,
        base_url: str = "",
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
            base_url = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
        if not model:
            # No hardcoded fallback: a stale default silently mislabels runs.
            # Let the non-empty-string validation below raise instead.
            model = os.getenv("DEFAULT_MODEL", "")
        if timeout is None:
            timeout = int(os.getenv("OLLAMA_TIMEOUT", str(DEFAULT_TIMEOUT)))
        if not isinstance(base_url, str) or not base_url:
            raise ValueError("base_url must be a non-empty string")
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
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self.seed = seed
        self.top_p = top_p
        self.top_k = top_k
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive
        self.response_format = response_format
        self.last_metrics: Optional[Dict[str, Any]] = None

    @property
    def endpoint(self) -> str:
        """Generate endpoint URL (for backward compatibility)."""
        return f"{self.base_url}/api/generate"

    @endpoint.setter
    def endpoint(self, value: str) -> None:
        """Set endpoint by extracting base URL (for backward compatibility)."""
        # Strip /api/generate suffix if present
        if value.endswith("/api/generate"):
            self.base_url = value[: -len("/api/generate")]
        else:
            self.base_url = value.rstrip("/")

    def generate(self, prompt: str) -> str:
        """Send a prompt to the LLM and return the response text.

        Retries on transient errors (ReadTimeout, ConnectionError) with
        exponential backoff.  Non-transient errors are raised immediately.

        Args:
            prompt: The text prompt to send.

        Returns:
            The generated text response, stripped of whitespace.
        """
        if not isinstance(prompt, str):
            raise TypeError(f"prompt must be a str, got {type(prompt).__name__}")
        if not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        options: Dict[str, Any] = {
            "temperature": self.temperature,
            "num_predict": self.max_tokens,
        }
        if self.seed is not None:
            options["seed"] = self.seed
        if self.top_p is not None:
            options["top_p"] = self.top_p
        if self.top_k is not None:
            options["top_k"] = self.top_k
        if self.num_ctx is not None:
            options["num_ctx"] = self.num_ctx

        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": options,
        }
        if self.keep_alive is not None:
            payload["keep_alive"] = self.keep_alive
        if self.response_format is not None:
            payload["format"] = self.response_format

        self.last_metrics = None

        def _do_request() -> str:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
            _check_model_not_found(response, self.model, self.base_url)
            data = response.json()
            text = data["response"].strip()
            self.last_metrics = _extract_metrics(data, self.model)
            logger.info(f"{self.model} >> {text}")
            return text

        return retry_on_transient(_do_request, max_retries=self.max_retries)

    def unload_model(self, model: Optional[str] = None) -> bool:
        """Unload a model from VRAM by sending keep_alive=0.

        Args:
            model: Model name to unload. Defaults to self.model.

        Returns:
            True if the unload request succeeded.
        """
        target = model or self.model
        payload = {
            "model": target,
            "prompt": "",
            "stream": False,
            "keep_alive": 0,
        }
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=30,
            )
            _check_model_not_found(response, target, self.base_url)
            logger.info(f"Unloaded model: {target}")
            return True
        except OllamaModelNotFoundError:
            raise
        except Exception as exc:
            logger.warn(f"Failed to unload model {target}: {exc}")
            return False

    def list_models(self) -> List[str]:
        """Query available models from the Ollama endpoint.

        Returns:
            List of model name strings (without tags).
        """
        response = requests.get(f"{self.base_url}/api/tags", timeout=10)
        response.raise_for_status()

        data = response.json()
        return [
            model.get("name", "").split(":")[0]
            for model in data.get("models", [])
            if model.get("name")
        ]

    def list_models_detailed(self) -> List[Dict[str, Any]]:
        """Query available models with full metadata.

        Returns:
            List of dicts with name, size, modified_at, digest keys.
        """
        response = requests.get(f"{self.base_url}/api/tags", timeout=10)
        response.raise_for_status()

        data = response.json()
        result = []
        for model in data.get("models", []):
            name = model.get("name", "")
            if name:
                result.append(
                    {
                        "name": name,
                        "size": model.get("size", 0),
                        "modified_at": model.get("modified_at", ""),
                        "digest": model.get("digest", "")[:12],
                    }
                )
        return result

    def running_models(self) -> List[Dict[str, Any]]:
        """Query currently running models from the Ollama endpoint.

        Uses the /api/ps endpoint to check which models are loaded
        and actively processing requests.

        Returns:
            List of dicts with model name, size, and expiry info.
        """
        response = requests.get(f"{self.base_url}/api/ps", timeout=10)
        response.raise_for_status()

        data = response.json()
        return data.get("models", [])

    def is_busy(self) -> bool:
        """Check if Ollama is currently processing a request.

        Queries /api/ps and checks if any model has a non-zero
        size_vram, indicating it is loaded and potentially busy.

        Returns:
            True if any model is currently loaded and running.
        """
        try:
            models = self.running_models()
            return len(models) > 0
        except Exception:
            return False

    def is_available(self) -> bool:
        """Check if the Ollama endpoint is accessible.

        Returns:
            True if endpoint responds successfully.
        """
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=2)
            return response.status_code == 200
        except Exception:
            return False

    def wait_until_ready(self, timeout: int = 5400, poll_interval: int = 2) -> bool:
        """Wait until Ollama is available and not busy processing another request.

        Polls the /api/ps endpoint to detect when the LLM is idle.
        This prevents timeout errors caused by sending a request while
        Ollama is still processing a previous one.

        Logs a warning after 1 minute, then every 5 minutes, so long
        waits are visible without flooding the log.

        Args:
            timeout: Maximum seconds to wait (default 5400 / 90 min).
            poll_interval: Seconds between checks.

        Returns:
            True if Ollama became ready within timeout.

        Raises:
            TimeoutError: If Ollama is still busy after timeout expires.
        """
        if timeout < 1:
            raise ValueError(f"timeout must be >= 1, got {timeout}")
        if poll_interval < 1:
            raise ValueError(f"poll_interval must be >= 1, got {poll_interval}")

        start = time.time()
        next_warn_at = 60  # first warning after 1 minute
        warn_interval = 300  # then every 5 minutes
        while time.time() - start < timeout:
            elapsed = int(time.time() - start)

            if not self.is_available():
                if elapsed >= next_warn_at:
                    logger.warn(
                        f"Still waiting for Ollama after {elapsed}s "
                        f"(endpoint unavailable) — "
                        f"timeout in {timeout - elapsed}s "
                        f"| next: {self.model}"
                    )
                    next_warn_at += warn_interval
                logger.info("Ollama endpoint not available yet, waiting...")
                time.sleep(poll_interval)
                continue

            models = []
            try:
                models = self.running_models()
            except Exception:
                # /api/ps may not be available on older Ollama versions
                logger.debug("Could not query /api/ps, assuming idle")
                return True

            if len(models) == 0:
                logger.info("Ollama is idle, no models running")
                return True

            # Log what's running
            names = [m.get("name", "unknown") for m in models]
            if elapsed >= next_warn_at:
                logger.warn(
                    f"Still waiting for Ollama after {elapsed}s — "
                    f"timeout in {timeout - elapsed}s "
                    f"| loaded: [{', '.join(names)}] "
                    f"| next: {self.model}"
                )
                next_warn_at += warn_interval
            logger.info(f"Ollama busy with models: {', '.join(names)} - waiting...")
            time.sleep(poll_interval)

        elapsed = int(time.time() - start)
        raise OllamaTimeoutError(
            elapsed=elapsed,
            models=[m.get("name", "?") for m in models],
        )


# Backward-compatible alias
LLMClient = OllamaClient
