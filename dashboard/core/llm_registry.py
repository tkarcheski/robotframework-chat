"""LLM model registry for discovering available models."""

import time
from typing import Any

import requests


class LLMRegistry:
    """Discover and cache available LLM models from Ollama."""

    def __init__(self, ollama_host: str = "http://localhost:11434"):
        self.ollama_host = ollama_host
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
            response = requests.get(f"{self.ollama_host}/api/tags", timeout=5)
            response.raise_for_status()
            data = response.json()

            self._models = []
            self._model_info = {}

            for model in data.get("models", []):
                name = model.get("name", "")
                if name:
                    self._models.append(name)
                    self._model_info[name] = {
                        "size": model.get("size", 0),
                        "modified_at": model.get("modified_at", ""),
                        "digest": model.get("digest", "")[:12],
                    }

            # Sort alphabetically
            self._models.sort()
            self._last_update = time.time()

        except requests.exceptions.ConnectionError:
            # Ollama not running, return empty list
            self._models = []
        except Exception as e:
            print(f"Error fetching models: {e}")
            # Keep existing cache if available
            if not self._models:
                self._models = []

        return self._models

    def get_model_info(self, model_name: str) -> dict[str, Any]:
        """Get information about a specific model."""
        return self._model_info.get(model_name, {})

    def is_available(self) -> bool:
        """Check if Ollama is accessible."""
        try:
            response = requests.get(f"{self.ollama_host}/api/tags", timeout=2)
            return response.status_code == 200
        except Exception:
            return False


# Global registry instance
llm_registry = LLMRegistry()
