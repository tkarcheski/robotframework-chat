"""Ollama API client for LLM generation and model discovery."""

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
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

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

        Args:
            prompt: The text prompt to send.

        Returns:
            The generated text response, stripped of whitespace.
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }

        response = requests.post(
            f"{self.base_url}/api/generate", json=payload, timeout=60
        )
        response.raise_for_status()

        text = response.json()["response"].strip()
        logger.info(f"{self.model} >> {text}")
        return text

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


# Backward-compatible alias
LLMClient = OllamaClient
