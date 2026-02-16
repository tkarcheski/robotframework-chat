"""Robot Framework listener for Git/CI metadata collection.

This listener automatically collects metadata from GitHub Actions
or GitLab CI and adds it to Robot Framework test results.
"""

import json
import os
from datetime import datetime
from typing import Dict, Any, Optional
from robot.api import logger  # type: ignore
from robot.result import TestSuite  # type: ignore

from .git_metadata import collect_ci_metadata


class GitMetaData:
    """Listener that collects Git/CI metadata and adds it to test results.

    Auto-detects GitHub Actions or GitLab CI and formats links
    appropriately for the detected platform.

    Usage:
        robot --listener rfc.git_metadata_listener.GitMetaData tests/
    """

    ROBOT_LISTENER_API_VERSION = 2

    def __init__(self):
        """Initialize the listener."""
        self.metadata: Dict[str, Any] = {}
        self.start_time: Optional[datetime] = None
        self.ci_info: Dict[str, str] = {}
        self.platform: Optional[str] = None
        self._suite_depth: int = 0

    def start_suite(self, name: str, attributes: Dict[str, Any]):
        """Called when a test suite starts.

        Collects CI metadata at the top-level suite and adds it to
        every suite's metadata dict.
        """
        self._suite_depth += 1
        if self._suite_depth == 1:
            self.start_time = datetime.utcnow()
            self.ci_info = collect_ci_metadata()
            self.platform = self.ci_info.get("CI_Platform")

        # Log CI information
        if self.ci_info.get("CI"):
            logger.info(
                f"Running in CI environment: "
                f"{self.ci_info.get('Project_URL', 'Unknown')}"
            )
            logger.info(f"Commit: {self.ci_info.get('Commit_SHA', 'Unknown')[:8]}")
            logger.info(f"Branch: {self.ci_info.get('Branch', 'Unknown')}")

        # Add metadata to suite (via attributes)
        if "metadata" in attributes:
            attributes["metadata"].update(self.ci_info)

            project_url = self.ci_info.get("Project_URL", "")
            commit_sha = self.ci_info.get("Commit_SHA", "")
            commit_short = self.ci_info.get(
                "Commit_Short_SHA", commit_sha[:8] if commit_sha else ""
            )

            # Format Commit_SHA as a clickable link
            if project_url and commit_sha:
                attributes["metadata"]["Commit_SHA"] = self._format_commit_link(
                    project_url, commit_sha, commit_short
                )

            # Format Pipeline_URL as a clickable link
            pipeline_url = self.ci_info.get("Pipeline_URL", "")
            pipeline_id = self.ci_info.get("Pipeline_ID", "")
            if pipeline_url:
                label = f"Pipeline #{pipeline_id}" if pipeline_id else "Pipeline"
                attributes["metadata"]["Pipeline_URL"] = (
                    f"[{label}|{pipeline_url}]"
                )

            # Format Job_URL as a clickable link
            job_url = self.ci_info.get("Job_URL", "")
            job_name = self.ci_info.get("Job_Name", "")
            job_id = self.ci_info.get("Job_ID", "")
            if job_url:
                label = job_name or (f"Job #{job_id}" if job_id else "Job")
                attributes["metadata"]["Job_URL"] = f"[{label}|{job_url}]"

            # Format Source as a clickable link to the file at the commit
            source = attributes.get("source", "")
            if source and project_url and commit_sha:
                rel_path = self._resolve_relative_path(source)
                attributes["metadata"]["Source"] = self._format_source_link(
                    project_url, commit_sha, rel_path
                )

    def end_suite(self, name: str, attributes: Dict[str, Any]):
        """Called when a test suite ends.

        Adds final metadata and generates summary.  The JSON metadata
        file is only written when the top-level suite finishes.
        """
        self._suite_depth -= 1

        metadata = attributes.get("metadata")
        if metadata is None:
            return

        end_time = datetime.utcnow()
        duration = (
            (end_time - self.start_time).total_seconds() if self.start_time else 0
        )

        # Add execution metadata
        metadata["Test_Duration_Seconds"] = str(duration)
        metadata["Test_End_Time"] = end_time.isoformat() + "Z"
        metadata["Test_Start_Time"] = (
            self.start_time.isoformat() + "Z" if self.start_time else ""
        )

        # Add summary statistics
        metadata["Total_Tests"] = str(attributes.get("totaltests", 0))
        metadata["Passed_Tests"] = str(attributes.get("pass", 0))
        metadata["Failed_Tests"] = str(attributes.get("fail", 0))
        metadata["Skipped_Tests"] = str(attributes.get("skip", 0))

        # Only save JSON at the top-level suite
        if self._suite_depth == 0:
            self._save_metadata_json(metadata)

        logger.info(
            f"Suite '{name}' completed: {attributes.get('pass', 0)} passed, "
            f"{attributes.get('fail', 0)} failed, "
            f"{attributes.get('skip', 0)} skipped"
        )

    def _format_commit_link(self, project_url: str, sha: str, short_sha: str) -> str:
        """Format a commit SHA as a clickable link for the detected platform."""
        if self.platform == "github":
            return f"[{short_sha}|{project_url}/commit/{sha}]"
        # GitLab (default)
        return f"[{short_sha}|{project_url}/-/commit/{sha}]"

    def _format_source_link(self, project_url: str, sha: str, rel_path: str) -> str:
        """Format a source file path as a clickable link for the detected platform."""
        if self.platform == "github":
            return f"[{rel_path}|{project_url}/blob/{sha}/{rel_path}]"
        # GitLab (default)
        return f"[{rel_path}|{project_url}/-/blob/{sha}/{rel_path}]"

    def _resolve_relative_path(self, source: str) -> str:
        """Resolve a source path to a repository-relative path."""
        if self.platform == "github":
            workspace = os.getenv("GITHUB_WORKSPACE", "")
            if workspace and source.startswith(workspace):
                return source[len(workspace) :].lstrip(os.sep)
        else:
            project_dir = os.getenv("CI_PROJECT_DIR", "")
            if project_dir and source.startswith(project_dir):
                return source[len(project_dir) :].lstrip(os.sep)
        return source

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


class GitMetaDataModifier(GitMetaData):
    """Version of the listener that works as a pre-run modifier."""

    def start_suite(self, suite: TestSuite):  # type: ignore[override]
        """Modify suite with CI metadata.

        Called by Robot Framework before execution.
        """
        self.start_time = datetime.utcnow()
        self.ci_info = collect_ci_metadata()
        self.platform = self.ci_info.get("CI_Platform")

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
