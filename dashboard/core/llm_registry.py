"""LLM model registry for discovering available models across all nodes."""

import os
import time
from typing import Any

from rfc.ollama import OllamaClient
from rfc.suite_config import master_models, nodes


class LLMRegistry:
    """Discover and cache available LLM models from all Ollama nodes.

    Queries every configured node for its model list and builds a
    master view showing which models are available where.  Models
    listed in ``master_models`` in ``config/test_suites.yaml`` are
    always shown in the dropdown even if no node currently has them.
    """

    def __init__(self) -> None:
        self._node_models: dict[str, list[str]] = {}
        self._model_info: dict[str, dict] = {}
        self._last_update: float = 0
        self._cache_ttl: int = 60

    def _get_node_list(self) -> list[dict]:
        """Build node list from config or env."""
        env_list = os.environ.get("OLLAMA_NODES_LIST", "")
        if env_list:
            return [
                {"hostname": h.strip(), "port": 11434}
                for h in env_list.split(",")
                if h.strip()
            ]
        node_list = nodes()
        if node_list:
            return node_list
        endpoint = os.environ.get("OLLAMA_ENDPOINT", "http://localhost:11434")
        host = endpoint.replace("http://", "").replace("https://", "")
        parts = host.split(":")
        hostname = parts[0]
        port = int(parts[1]) if len(parts) > 1 else 11434
        return [{"hostname": hostname, "port": port}]

    def refresh_models(self) -> None:
        """Query all nodes for available models."""
        self._node_models = {}
        new_info: dict[str, dict] = {}

        for node in self._get_node_list():
            host = node["hostname"]
            port = node.get("port", 11434)
            host_key = f"{host}:{port}"
            client = OllamaClient(base_url=f"http://{host}:{port}")
            try:
                detailed = client.list_models_detailed()
                names = []
                for info in detailed:
                    name = info["name"]
                    names.append(name)
                    if name not in new_info:
                        new_info[name] = {
                            "size": info["size"],
                            "modified_at": info["modified_at"],
                            "digest": info["digest"],
                        }
                self._node_models[host_key] = sorted(names)
            except Exception:
                self._node_models[host_key] = []

        self._model_info = new_info
        self._last_update = time.time()

    def _ensure_fresh(self) -> None:
        if time.time() - self._last_update > self._cache_ttl:
            self.refresh_models()

    def get_models(self) -> list[str]:
        """Return deduplicated sorted list of models found on any node."""
        self._ensure_fresh()
        all_names: set[str] = set()
        for names in self._node_models.values():
            all_names.update(names)
        return sorted(all_names)

    def get_all_models(self) -> list[dict]:
        """Return dropdown-ready list with availability annotations.

        Models available on at least one node are shown normally.
        Models from ``master_models`` that are not found on any node
        are shown with ``disabled=True`` and a grayed-out label.
        """
        self._ensure_fresh()

        available: set[str] = set()
        for names in self._node_models.values():
            available.update(names)

        # Start with all discovered models
        options: list[dict] = []
        for name in sorted(available):
            hosts = [h for h, models in self._node_models.items() if name in models]
            label = f"{name}  ({', '.join(hosts)})" if len(hosts) < 3 else name
            options.append({"label": label, "value": name})

        # Add master models not found on any node (grayed out)
        for name in master_models():
            if name not in available:
                options.append(
                    {
                        "label": f"{name}  (not available)",
                        "value": name,
                        "disabled": True,
                    }
                )

        return options

    def models_on_node(self, host_port: str) -> list[str]:
        """Return models available on a specific node."""
        if not isinstance(host_port, str):
            raise TypeError(
                f"host_port must be a str, got {type(host_port).__name__}"
            )
        if not host_port:
            raise ValueError("host_port must be a non-empty string")
        self._ensure_fresh()
        return list(self._node_models.get(host_port, []))

    def get_model_info(self, model_name: str) -> dict[str, Any]:
        """Get information about a specific model."""
        if not isinstance(model_name, str):
            raise TypeError(
                f"model_name must be a str, got {type(model_name).__name__}"
            )
        if not model_name:
            raise ValueError("model_name must be a non-empty string")
        self._ensure_fresh()
        return self._model_info.get(model_name, {})

    def is_available(self) -> bool:
        """Check if any Ollama node is accessible."""
        for node in self._get_node_list():
            host = node["hostname"]
            port = node.get("port", 11434)
            client = OllamaClient(base_url=f"http://{host}:{port}")
            if client.is_available():
                return True
        return False


# Global registry instance
llm_registry = LLMRegistry()
