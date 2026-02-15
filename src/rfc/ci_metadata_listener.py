"""Robot Framework listener for GitLab CI metadata collection.

This listener automatically collects and adds GitLab CI metadata
to Robot Framework test results.
"""

import json
import os
from datetime import datetime
from typing import Dict, Any, Optional
from robot.api import logger  # type: ignore
from robot.result import TestSuite  # type: ignore

from .ci_metadata import collect_ci_metadata


class CiMetadataListener:
    """Listener that collects CI metadata and adds it to test results.

    Usage:
        robot --listener rfc.ci_metadata_listener.CiMetadataListener tests/
    """

    ROBOT_LISTENER_API_VERSION = 2

    def __init__(self):
        """Initialize the listener."""
        self.metadata: Dict[str, Any] = {}
        self.start_time: Optional[datetime] = None
        self.ci_info: Dict[str, str] = {}

    def start_suite(self, name: str, attributes: Dict[str, Any]):
        """Called when a test suite starts.

        Collects CI metadata and adds it to the suite metadata.
        """
        self.start_time = datetime.utcnow()
        self.ci_info = collect_ci_metadata()

        # Log CI information
        if self.ci_info.get("CI"):
            logger.info(
                f"Running in CI environment: {self.ci_info.get('GitLab_URL', 'Unknown')}"
            )
            logger.info(f"Commit: {self.ci_info.get('Commit_SHA', 'Unknown')[:8]}")
            logger.info(f"Branch: {self.ci_info.get('Branch', 'Unknown')}")

        # Add metadata to suite (via attributes)
        if "metadata" in attributes:
            attributes["metadata"].update(self.ci_info)

    def end_suite(self, name: str, attributes: Dict[str, Any]):
        """Called when a test suite ends.

        Adds final metadata and generates summary.
        """
        end_time = datetime.utcnow()
        duration = (
            (end_time - self.start_time).total_seconds() if self.start_time else 0
        )

        # Add execution metadata
        attributes["metadata"]["Test_Duration_Seconds"] = str(duration)
        attributes["metadata"]["Test_End_Time"] = end_time.isoformat() + "Z"
        attributes["metadata"]["Test_Start_Time"] = (
            self.start_time.isoformat() + "Z" if self.start_time else ""
        )

        # Add summary statistics
        attributes["metadata"]["Total_Tests"] = str(attributes.get("totaltests", 0))
        attributes["metadata"]["Passed_Tests"] = str(attributes.get("pass", 0))
        attributes["metadata"]["Failed_Tests"] = str(attributes.get("fail", 0))
        attributes["metadata"]["Skipped_Tests"] = str(attributes.get("skip", 0))

        # Generate metadata JSON file
        self._save_metadata_json(attributes["metadata"])

        logger.info(
            f"Suite '{name}' completed: {attributes.get('pass', 0)} passed, "
            f"{attributes.get('fail', 0)} failed, "
            f"{attributes.get('skip', 0)} skipped"
        )

    def _save_metadata_json(self, metadata: Dict[str, str]):
        """Save metadata to a JSON file for external tools.

        Args:
            metadata: Dictionary of metadata to save
        """
        try:
            output_dir = os.getenv("ROBOT_OUTPUT_DIR", ".")
            metadata_file = os.path.join(output_dir, "ci_metadata.json")

            # Convert any non-string values to strings
            serializable_metadata = {k: str(v) for k, v in metadata.items()}

            with open(metadata_file, "w") as f:
                json.dump(serializable_metadata, f, indent=2)

            logger.info(f"CI metadata saved to: {metadata_file}")

        except Exception as e:
            logger.warn(f"Could not save metadata JSON: {e}")


class CiMetadataModifier(CiMetadataListener):
    """Version of the listener that works as a pre-run modifier."""

    def start_suite(self, suite: TestSuite):  # type: ignore[override]
        """Modify suite with CI metadata.

        Called by Robot Framework before execution.
        """
        self.start_time = datetime.utcnow()
        self.ci_info = collect_ci_metadata()

        # Add metadata to suite
        for key, value in self.ci_info.items():
            suite.metadata[key] = value

        logger.info(f"Added {len(self.ci_info)} CI metadata items to suite")


def main():
    """Entry point for testing the listener."""
    metadata = collect_ci_metadata()

    print("CI Metadata collected:")
    print(json.dumps(metadata, indent=2))

    return 0 if metadata.get("CI") == "true" else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
