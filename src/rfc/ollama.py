"""Ollama API client for LLM generation and model discovery."""

import time
from typing import Any, Dict, List

from robot.api import logger
import requests


class OllamaClient:
    """HTTP client for the Ollama API.

    Handles both text generation and model discovery, providing a single
    integration point for all Ollama interactions.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3",
        temperature: float = 0.0,
        max_tokens: int = 256,
        timeout: int = 120,
        max_retries: int = 2,
    ):
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
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries

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
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }

        last_exception: Exception | None = None
        for attempt in range(1 + self.max_retries):
            try:
                response = requests.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                text = response.json()["response"].strip()
                logger.info(f"{self.model} >> {text}")
                return text
            except (
                requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError,
            ) as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    delay = 2 ** (attempt + 1)
                    logger.warn(
                        f"generate() attempt {attempt + 1} failed: {exc}. "
                        f"Retrying in {delay}s "
                        f"({self.max_retries - attempt} retries left)"
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        f"generate() failed after {attempt + 1} attempts: {exc}"
                    )

        raise last_exception  # type: ignore[misc]

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

    def wait_until_ready(self, timeout: int = 120, poll_interval: int = 2) -> bool:
        """Wait until Ollama is available and not busy processing another request.

        Polls the /api/ps endpoint to detect when the LLM is idle.
        This prevents timeout errors caused by sending a request while
        Ollama is still processing a previous one.

        Args:
            timeout: Maximum seconds to wait.
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
        while time.time() - start < timeout:
            if not self.is_available():
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
            logger.info(f"Ollama busy with models: {', '.join(names)} - waiting...")
            time.sleep(poll_interval)

        elapsed = int(time.time() - start)
        raise TimeoutError(
            f"Ollama still busy after {elapsed}s. "
            f"Running models: {[m.get('name', '?') for m in models]}"
        )


# Backward-compatible alias
LLMClient = OllamaClient
