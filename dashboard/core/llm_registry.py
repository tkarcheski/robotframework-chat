"""LLM model registry for discovering available models."""

import os
import time
from typing import Any

from rfc.ollama import OllamaClient


class LLMRegistry:
    """Discover and cache available LLM models from Ollama.

    Wraps OllamaClient with a TTL cache for use in the dashboard,
    where frequent polling shouldn't hammer the Ollama endpoint.
    """

    def __init__(self, ollama_host: str | None = None):
        if ollama_host is None:
            ollama_host = os.environ.get("OLLAMA_ENDPOINT", "http://localhost:11434")
        self._client = OllamaClient(base_url=ollama_host)
        self._models: list[str] = []
        self._model_info: dict[str, dict] = {}
        self._last_update: float = 0
        self._cache_ttl: int = 60  # Cache for 60 seconds

    def get_models(self) -> list[str]:
        """Return cached or fresh list of models."""
        if time.time() - self._last_update > self._cache_ttl:
            self.refresh_models()
        return self._models

    def refresh_models(self) -> list[str]:
        """Query Ollama API for available models."""
        try:
            detailed = self._client.list_models_detailed()

            self._models = []
            self._model_info = {}

            for info in detailed:
                name = info["name"]
                self._models.append(name)
                self._model_info[name] = {
                    "size": info["size"],
                    "modified_at": info["modified_at"],
                    "digest": info["digest"],
                }

            self._models.sort()
            self._last_update = time.time()

        except ConnectionError:
            self._models = []
        except Exception as e:
            print(f"Error fetching models: {e}")
            if not self._models:
                self._models = []

        return self._models

    def get_model_info(self, model_name: str) -> dict[str, Any]:
        """Get information about a specific model."""
        return self._model_info.get(model_name, {})

    def is_available(self) -> bool:
        """Check if Ollama is accessible."""
        return self._client.is_available()


# Global registry instance
llm_registry = LLMRegistry()
