"""Backward-compatible re-export. Use rfc.ollama instead."""

from .ollama import OllamaClient as LLMClient

__all__ = ["LLMClient"]
