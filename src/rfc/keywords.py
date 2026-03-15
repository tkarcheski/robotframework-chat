import json
import os
from typing import List, Dict, Any, Optional

from robot.api import logger
from robot.api.deco import keyword
from .llm_client import create_provider
from .ollama import OllamaClient
from .grader import Grader

_DEFAULT_TIMEOUT = 5400


class LLMKeywords:
    """
    Robot Framework keywords for testing LLMs.
    """

    def __init__(self, timeout: Optional[int] = None, max_retries: int = 2):
        if timeout is None:
            timeout = int(os.getenv("OLLAMA_TIMEOUT", str(_DEFAULT_TIMEOUT)))
        self.client = create_provider(
            timeout=int(timeout), max_retries=int(max_retries)
        )
        self.grader = Grader(self.client)

    @keyword("Set LLM Endpoint")
    def set_llm_endpoint(self, endpoint: str):
        """Set the LLM endpoint URL.

        For Ollama providers, updates the base URL. For OpenAI-compatible
        providers, updates the base_url used for API calls.
        """
        logger.info(endpoint)
        if isinstance(self.client, OllamaClient):
            self.client.endpoint = endpoint
        elif hasattr(self.client, "base_url"):
            self.client.base_url = endpoint.rstrip("/")  # type: ignore[attr-defined]
        else:
            logger.warn("Set LLM Endpoint not supported for this provider")

    @keyword("Set LLM Model")
    def set_llm_model(self, model: str):
        logger.info(model)
        self.client.model = model

    @keyword("Set LLM Parameters")
    def set_llm_parameters(self, temperature: float = 0.0, max_tokens: int = 256):
        self.client.temperature = float(temperature)
        self.client.max_tokens = int(max_tokens)

    @keyword("Ask LLM")
    def ask_llm(self, prompt: str) -> str:
        logger.info(prompt)
        response = self.client.generate(prompt)
        logger.info(response)
        logger.info(f"RFC_DATA:actual_answer:{response}")
        if self.client.last_metrics is not None:
            self.client.last_metrics["prompt_text"] = prompt
            logger.info(f"RFC_DATA:llm_metrics:{json.dumps(self.client.last_metrics)}")
        return response

    @keyword("Grade Answer")
    def grade_answer(self, question: str, expected: str, actual: str):
        result = self.grader.grade(question, expected, actual)
        logger.info(f"RFC_DATA:score:{result.score}")
        logger.info(f"RFC_DATA:expected_answer:{expected}")
        logger.info(f"RFC_DATA:grading_reason:{result.reason}")
        return result.score, result.reason

    @keyword("Wait For LLM")
    def wait_for_llm(self, timeout: int = 5400, poll_interval: int = 2) -> bool:
        """Wait until the LLM is available and not busy.

        For Ollama providers, polls the /api/ps endpoint to detect when
        no models are actively processing requests. For other providers,
        returns True immediately (no queue detection available).

        Args:
            timeout: Maximum seconds to wait (default 5400 / 90 min).
            poll_interval: Seconds between polling attempts (default 2).

        Returns:
            True when the LLM is ready.

        Raises:
            TimeoutError: If Ollama is still busy after timeout.

        Example:
            | Wait For LLM | timeout=60 |
            | ${answer}= | Ask LLM | What is 2 + 2? |
        """
        if not isinstance(self.client, OllamaClient):
            logger.info("Non-Ollama provider — skipping wait (always ready)")
            return True
        timeout = int(timeout)
        poll_interval = int(poll_interval)
        logger.info(
            f"Waiting for Ollama to be ready (timeout={timeout}s, "
            f"poll={poll_interval}s)"
        )
        return self.client.wait_until_ready(timeout, poll_interval)

    @keyword("Get Running Models")
    def get_running_models(self) -> List[Dict[str, Any]]:
        """Get the list of models currently loaded/running.

        Only available for Ollama providers. Returns an empty list
        for other providers.

        Returns:
            List of model info dicts from Ollama's /api/ps response.

        Example:
            | ${models}= | Get Running Models |
            | Log | Currently running: ${models} |
        """
        if not isinstance(self.client, OllamaClient):
            logger.info("Non-Ollama provider — running models not available")
            return []
        models = self.client.running_models()
        logger.info(f"Running models: {models}")
        return models

    @keyword("LLM Is Busy")
    def llm_is_busy(self) -> bool:
        """Check if the LLM currently has models loaded and running.

        Only available for Ollama providers. Returns False for other
        providers.

        Returns:
            True if Ollama has active models, False otherwise.

        Example:
            | ${busy}= | LLM Is Busy |
            | Run Keyword If | ${busy} | Wait For LLM |
        """
        if not isinstance(self.client, OllamaClient):
            logger.info("Non-Ollama provider — busy check not available")
            return False
        busy = self.client.is_busy()
        logger.info(f"Ollama busy: {busy}")
        return busy
