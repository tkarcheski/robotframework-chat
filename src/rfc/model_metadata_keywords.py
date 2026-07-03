"""Robot Framework keywords for fetching LLM model metadata.

Wraps the Browser (Playwright) library and YAML serialisation behind static
Python keywords so ``robot --dryrun`` can resolve every keyword name even
when the optional ``playwright`` extra is not installed.  When the Browser
library is missing, the research keyword raises :class:`SkipExecution` so
the surrounding test is skipped rather than failed.

Pairs with ``robot/tier1/ci/fetch_model_metadata.robot``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml
from robot.api import logger  # type: ignore[import-untyped]
from robot.api.deco import keyword  # type: ignore[import-untyped]
from robot.api.exceptions import SkipExecution  # type: ignore[import-untyped]


_OLLAMA_LIBRARY_URL = "https://ollama.com/library"
_HUGGING_FACE_URL = "https://huggingface.co"


def _ollama_to_hf(model_name: str) -> str:
    """Map an Ollama model name to its Hugging Face equivalent."""
    if model_name == "llama3":
        return "meta-llama/Meta-Llama-3-8B"
    return model_name


def _build_metadata_payload(
    models: dict[str, dict[str, Any]],
    today: str,
) -> dict[str, Any]:
    """Build the dict that gets serialised to YAML."""
    return {"version": "1.0", "generated_at": today, "models": models}


class ModelMetadataKeywords:
    """Keywords for researching model metadata via a headless browser."""

    ROBOT_LIBRARY_SCOPE = "SUITE"

    @keyword("Save Model Metadata Yaml")
    def save_model_metadata_yaml(
        self,
        models: dict[str, dict[str, Any]],
        output_file: str,
        generated_at: str | None = None,
    ) -> str:
        """Serialise ``models`` to a YAML file and return the file path.

        Args:
            models: Mapping of model name to metadata dict.
            output_file: Destination path for the YAML file.
            generated_at: ISO date string; defaults to today if omitted.

        Returns:
            Absolute path to the written file.
        """
        when = generated_at or date.today().isoformat()
        payload = _build_metadata_payload(models, when)
        path = Path(output_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(payload, sort_keys=False))
        logger.info(f"Model metadata saved to {path}")
        return str(path)

    @keyword("Research Models Metadata")
    def research_models_metadata(
        self,
        model_names: list[str],
        ollama_base_url: str = _OLLAMA_LIBRARY_URL,
        hugging_face_base_url: str = _HUGGING_FACE_URL,
    ) -> dict[str, dict[str, Any]]:
        """Drive a headless browser to collect metadata for each model.

        Skips the test if the optional Browser library is not installed.
        """
        try:
            from Browser import Browser  # type: ignore[import-not-found,import-untyped]
        except ImportError as exc:
            raise SkipExecution(
                "Browser library not installed. "
                "Install with: uv sync --extra playwright && rfbrowser init"
            ) from exc

        browser = Browser()
        today = date.today().isoformat()
        results: dict[str, dict[str, Any]] = {}

        try:
            browser.new_browser(browser="chromium", headless=True)
            browser.new_page()
            for model in model_names:
                results[model] = self._research_one(
                    browser,
                    model,
                    today,
                    ollama_base_url,
                    hugging_face_base_url,
                )
        finally:
            try:
                browser.close_browser()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warn(f"Failed to close browser cleanly: {exc}")

        return results

    @staticmethod
    def _research_one(
        browser: Any,
        model: str,
        today: str,
        ollama_base_url: str,
        hugging_face_base_url: str,
    ) -> dict[str, Any]:
        ollama_url = f"{ollama_base_url}/{model}"
        info: dict[str, Any] = {
            "name": model,
            "url": ollama_url,
            "researched_at": today,
        }
        try:
            browser.go_to(ollama_url)
            browser.wait_for_elements_state("h1", "visible", timeout="10s")
            info["title"] = browser.get_text("h1")
        except Exception as exc:
            logger.warn(f"Error researching {model} on Ollama: {exc}")
            info["error"] = str(exc)
            return info

        hf_model = _ollama_to_hf(model)
        hf_url = f"{hugging_face_base_url}/{hf_model}"
        try:
            browser.go_to(hf_url)
            browser.wait_for_elements_state("h1", "visible", timeout="5s")
            info["hugging_face_url"] = hf_url
            info["hugging_face_title"] = browser.get_text("h1")
        except Exception as exc:
            logger.info(f"Could not research Hugging Face for {model}: {exc}")

        return info
