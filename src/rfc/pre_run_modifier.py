"""Pre-run modifier for dynamic test configuration based on available models.

This module provides a Robot Framework pre-run modifier that:
1. Queries available models from Ollama endpoint
2. Reads model configuration from YAML
3. Filters tests based on available models
4. Configures test metadata
"""

import os
import sys
from typing import List, Dict, Any, Optional

import yaml
from robot.api import logger  # type: ignore
from robot.running import TestSuite  # type: ignore

from .git_metadata import collect_ci_metadata
from .ollama import OllamaClient


class ModelAwarePreRunModifier:
    """Pre-run modifier that configures tests based on available models."""

    def __init__(
        self,
        ollama_endpoint: Optional[str] = None,
        config_path: Optional[str] = None,
        default_model: Optional[str] = None,
    ):
        """Initialize the modifier.

        Args:
            ollama_endpoint: Ollama API endpoint (default: env OLLAMA_ENDPOINT or localhost:11434)
            config_path: Path to models.yaml config file
            default_model: Default model to use (default: env DEFAULT_MODEL or gpt-oss:20b)
        """
        self.ollama_endpoint = (
            ollama_endpoint or os.getenv("OLLAMA_ENDPOINT") or "http://localhost:11434"
        )
        self.config_path = config_path or "robot/ci/models.yaml"
        self.default_model = default_model or os.getenv("DEFAULT_MODEL") or "gpt-oss:20b"

        self._client = OllamaClient(
            base_url=self.ollama_endpoint, model=self.default_model
        )
        self.available_models: List[str] = []
        self.model_config: Dict[str, Any] = {}
        self.ci_metadata: Dict[str, str] = {}

    def start_suite(self, suite: TestSuite):
        """Modify test suite before execution.

        Called by Robot Framework before test execution starts.
        """
        logger.info(f"Starting ModelAwarePreRunModifier for suite: {suite.name}")

        # Gather CI metadata
        self.ci_metadata = collect_ci_metadata()
        logger.info(f"CI Metadata gathered: {len(self.ci_metadata)} items")

        # Load model configuration
        self._load_model_config()

        # Query available models from Ollama
        self._query_available_models()

        # Filter tests based on available models
        self._filter_tests_by_models(suite)

        # Add metadata to suite
        self._add_metadata(suite)

        logger.info(
            f"Pre-run modifier complete. Available models: {self.available_models}"
        )

    def _load_model_config(self) -> None:
        """Load model configuration from YAML file."""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r") as f:
                    config = yaml.safe_load(f)
                    self.model_config = config.get("models", {})
                logger.info(f"Loaded {len(self.model_config)} models from config")
            else:
                logger.warn(f"Model config not found: {self.config_path}")
        except Exception as e:
            logger.error(f"Error loading model config: {e}")

    def _query_available_models(self) -> None:
        """Query available models from Ollama endpoint."""
        try:
            self.available_models = self._client.list_models()
            logger.info(
                f"Found {len(self.available_models)} models on Ollama: {self.available_models}"
            )
        except Exception as e:
            logger.error(f"Error querying Ollama models: {e}")
            self.available_models = [self.default_model or "gpt-oss:20b"]
            logger.info(
                f"Falling back to default model: {self.default_model or 'gpt-oss:20b'}"
            )

    def _filter_tests_by_models(self, suite: TestSuite) -> None:
        """Filter tests based on available models.

        Removes tests that require models not available on the runner.
        """
        # Get suite configuration for preferred models
        suite_config = self.model_config.get("test_configuration", {}).get(
            "suite_models", {}
        )
        suite_name = suite.name.lower()

        preferred_models = suite_config.get(suite_name, [self.default_model])

        # Find which preferred models are available
        usable_models = [
            model for model in preferred_models if model in self.available_models
        ]

        if not usable_models:
            logger.warn(
                f"No preferred models available for suite {suite.name}. "
                f"Available: {self.available_models}, Preferred: {preferred_models}"
            )
            usable_models = [self.default_model]

        # Store selected model for this suite
        suite.metadata["Selected_Model"] = usable_models[0]
        suite.metadata["Available_Models"] = ", ".join(self.available_models)
        suite.metadata["Usable_Models"] = ", ".join(usable_models)

        logger.info(f"Suite {suite.name} will use models: {usable_models}")

        # Filter test cases if they have specific model requirements
        tests_to_remove = []
        for test in suite.tests:
            # Check if test has model-specific tags
            model_tags = [tag for tag in test.tags if tag.startswith("model:")]

            if model_tags:
                required_models = [tag.split(":")[1] for tag in model_tags]

                # Check if any required model is available
                if not any(model in self.available_models for model in required_models):
                    logger.info(
                        f"Removing test '{test.name}' - requires models {required_models}, "
                        f"but available models are {self.available_models}"
                    )
                    tests_to_remove.append(test)

        # Remove filtered tests
        for test in tests_to_remove:
            suite.tests.remove(test)

        if tests_to_remove:
            logger.info(
                f"Filtered out {len(tests_to_remove)} tests due to model unavailability"
            )

    def _add_metadata(self, suite: TestSuite) -> None:
        """Add CI and model metadata to test suite."""
        # Add CI metadata
        for key, value in self.ci_metadata.items():
            if value:  # Only add non-empty values
                suite.metadata[key] = value

        # Add model metadata
        if self.default_model in self.model_config:
            model_info = self.model_config[self.default_model]
            suite.metadata["Model_Name"] = model_info.get(
                "full_name", self.default_model
            )
            suite.metadata["Model_Release_Date"] = model_info.get(
                "release_date", "Unknown"
            )
            suite.metadata["Model_Parameters"] = model_info.get("parameters", "Unknown")
            suite.metadata["Model_Organization"] = model_info.get(
                "organization", "Unknown"
            )

        # Add available models list
        suite.metadata["All_Available_Models"] = ", ".join(self.available_models)

        logger.info(f"Added {len(suite.metadata)} metadata items to suite")


def main():
    """Entry point for testing the modifier."""
    modifier = ModelAwarePreRunModifier()

    # Test model querying
    modifier._query_available_models()
    print(f"Available models: {modifier.available_models}")

    # Test config loading
    modifier._load_model_config()
    print(f"Loaded {len(modifier.model_config)} models from config")

    return 0 if modifier.available_models else 1


if __name__ == "__main__":
    sys.exit(main())
