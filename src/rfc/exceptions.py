"""Centralised exception hierarchy with Robot Framework ROBOT_SKIP support.

Robot Framework recognises the ``ROBOT_SKIP`` class attribute on exceptions.
When a keyword raises an exception whose class has ``ROBOT_SKIP = True``,
the test is marked **skipped** instead of **failed**.  This module defines
a base class and concrete subclasses for every infrastructure / environment
error that should skip — not fail — a test.
"""

from typing import List


class RFCSkipError(Exception):
    """Base for infrastructure errors that should SKIP, not FAIL.

    All subclasses inherit ``ROBOT_SKIP = True`` so Robot Framework marks
    the enclosing test as *skipped* rather than *failed*.
    """

    ROBOT_SKIP: bool = True


# ── Ollama ────────────────────────────────────────────────────────────


class OllamaModelNotFoundError(RFCSkipError):
    """Raised when Ollama returns 404 for a model that is not pulled."""

    def __init__(self, model: str, endpoint: str, detail: str = "") -> None:
        self.model = model
        self.endpoint = endpoint
        hint = detail or f"model '{model}' not found"
        super().__init__(
            f"{hint}. Run `ollama pull {model}` to download it. (endpoint: {endpoint})"
        )


class EmptyLLMResponseError(RFCSkipError):
    """Raised when the LLM returns an empty / no-token response."""

    def __init__(self, model: str, prompt_snippet: str = "") -> None:
        self.model = model
        self.prompt_snippet = prompt_snippet
        snippet = f" for prompt: {prompt_snippet!r}" if prompt_snippet else ""
        super().__init__(
            f"LLM returned an empty response (model={model}){snippet}. "
            f"Marking test as skipped."
        )


class OllamaTimeoutError(RFCSkipError):
    """Raised when Ollama stays busy or unavailable past the timeout."""

    def __init__(self, elapsed: int, models: List[str]) -> None:
        self.elapsed = elapsed
        self.models = models
        super().__init__(
            f"Ollama still busy after {elapsed}s. Running models: {models}"
        )


# ── Docker ────────────────────────────────────────────────────────────


class DockerNotAvailableError(RFCSkipError):
    """Raised when the Docker daemon is not reachable."""

    def __init__(self) -> None:
        super().__init__(
            "Docker is not available. Please ensure Docker is installed and running."
        )


class PortAllocationError(RFCSkipError):
    """Raised when no free port can be found in the requested range."""

    def __init__(self, start_port: int, end_port: int) -> None:
        self.start_port = start_port
        self.end_port = end_port
        super().__init__(f"No available port found in range {start_port}-{end_port}")


# ── Environment / configuration ──────────────────────────────────────


class MissingDependencyError(RFCSkipError):
    """Raised when an optional Python package is not installed."""

    def __init__(self, package: str, install_hint: str = "") -> None:
        self.package = package
        msg = f"Required package '{package}' is not installed."
        if install_hint:
            msg += f" Install with: {install_hint}"
        super().__init__(msg)


class MissingEnvironmentError(RFCSkipError):
    """Raised when a required environment variable is not set."""

    def __init__(self, variable: str) -> None:
        self.variable = variable
        super().__init__(
            f"{variable} is not set. Set it in .env or export it in your shell."
        )


class MissingProviderConfigError(RFCSkipError):
    """Raised when an LLM provider's credentials are missing."""

    def __init__(self, provider: str, variable: str) -> None:
        self.provider = provider
        self.variable = variable
        super().__init__(
            f"{variable} environment variable must be set "
            f"when using the {provider} provider."
        )
