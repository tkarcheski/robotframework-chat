# src/robotframework_chat/keywords.py

from robot.api.deco import keyword
from .llm_client import LLMClient
from .grader import Grader

class LLMKeywords:
    """
    Robot Framework kewords for testing LLMs.
    """

    def __init__(self):
        self.client = LLMClient()
        self.grader = Grader(self.client)

    @keyword("Set LLM Endpoint")
    def set_llm_endpoint(self, endpoint: str):
        self.client.endpoint = endpoint

    @keyword("Set LLM Model")
    def set_llm_model(self, model: str):
        self.client.model = model

    @keyword("Set LLM Parameters")
    def set_llm_parameters(self, temperature: float = 0.0, max_tokens: int = 256):
        self.client.temperature = float(temperature)
        self.client.max_tokens = int(max_tokens)

    @keyword("Ask LLM")
    def ask_llm(self, prompt: str) -> str:
        return self.client.generate(prompt)

    @keyword("Grade Answer")
    def grade_answer(self, question: str, expected: str, actual: str):
        result = self.grader.grade(question, expected, actual)
        return result.score, result.reason
