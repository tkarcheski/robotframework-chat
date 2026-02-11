from robot.api import logger
import requests


class LLMClient:
    def __init__(
        self,
        endpoint: str = "http://localhost:11434/api/generate",
        model: str = "llama3",
        temperature: float = 0.0,
        max_tokens: int = 256,
    ):
        self.endpoint = endpoint
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def generate(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }

        response = requests.post(self.endpoint, json=payload, timeout=60)
        response.raise_for_status()

        logger.info(f"{self.model} >> {response.json()['response'].strip()}")

        return response.json()["response"].strip()
