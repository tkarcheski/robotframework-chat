from typing import List, Dict, Any

from robot.api import logger
from robot.api.deco import keyword
from .ollama import OllamaClient
from .grader import Grader


class LLMKeywords:
    """
    Robot Framework keywords for testing LLMs.
    """

    def __init__(self):
        self.client = OllamaClient()
        self.grader = Grader(self.client)

    @keyword("Set LLM Endpoint")
    def set_llm_endpoint(self, endpoint: str):
        logger.info(endpoint)
        self.client.endpoint = endpoint

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
        return response

    @keyword("Grade Answer")
    def grade_answer(self, question: str, expected: str, actual: str):
        result = self.grader.grade(question, expected, actual)
        return result.score, result.reason

    @keyword("Wait For LLM")
    def wait_for_llm(self, timeout: int = 120, poll_interval: int = 2) -> bool:
        """Wait until the Ollama LLM is available and not busy.

        Polls the /api/ps endpoint to detect when no models are actively
        processing requests. Use this before Ask LLM when Ollama may be
        busy serving another request to avoid timeout errors.

        Args:
            timeout: Maximum seconds to wait (default 120).
            poll_interval: Seconds between polling attempts (default 2).

        Returns:
            True when the LLM is ready.

        Raises:
            TimeoutError: If Ollama is still busy after timeout.

        Example:
            | Wait For LLM | timeout=60 |
            | ${answer}= | Ask LLM | What is 2 + 2? |
        """
        timeout = int(timeout)
        poll_interval = int(poll_interval)
        logger.info(
            f"Waiting for Ollama to be ready (timeout={timeout}s, "
            f"poll={poll_interval}s)"
        )
        return self.client.wait_until_ready(timeout, poll_interval)

    @keyword("Get Running Models")
    def get_running_models(self) -> List[Dict[str, Any]]:
        """Get the list of models currently loaded/running in Ollama.

        Queries the /api/ps endpoint to see which models are active.

        Returns:
            List of model info dicts from Ollama's /api/ps response.

        Example:
            | ${models}= | Get Running Models |
            | Log | Currently running: ${models} |
        """
        models = self.client.running_models()
        logger.info(f"Running models: {models}")
        return models

    @keyword("LLM Is Busy")
    def llm_is_busy(self) -> bool:
        """Check if Ollama currently has models loaded and running.

        Returns:
            True if Ollama has active models, False otherwise.

        Example:
            | ${busy}= | LLM Is Busy |
            | Run Keyword If | ${busy} | Wait For LLM |
        """
        busy = self.client.is_busy()
        logger.info(f"Ollama busy: {busy}")
        return busy
