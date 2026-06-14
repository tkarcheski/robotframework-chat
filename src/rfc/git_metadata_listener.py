"""Robot Framework listener for Git/CI metadata collection.

This listener automatically collects metadata from GitHub Actions
and adds it to Robot Framework test results.
"""

import json
import os
from datetime import datetime, UTC
from typing import Any, Dict, Optional

from robot.api import logger  # type: ignore
from .base_listener import BaseListener
from .git_metadata import collect_ci_metadata


class GitMetaData(BaseListener):
    """Listener that collects Git/CI metadata and adds it to test results.

    Auto-detects GitHub Actions and formats links appropriately for
    the detected platform.

    Unlike other listeners, ``start_suite`` and ``end_suite`` operate
    at *every* suite level (not just top-level) because metadata must
    be attached to every suite result.  Top-level-only work (CI
    metadata collection, JSON save) uses the ``on_suite_start`` /
    ``on_suite_end`` hooks.

    Usage:
        robot --listener rfc.git_metadata_listener.GitMetaData tests/
    """

    def __init__(self) -> None:
        """Initialize the listener."""
        super().__init__()
        self.metadata: Dict[str, Any] = {}
        self.start_time: Optional[datetime] = None
        self.ci_info: Dict[str, str] = {}
        self.platform: Optional[str] = None

    # ------------------------------------------------------------------
    # Overridden Listener API methods (per-suite work)
    # ------------------------------------------------------------------

    def start_suite(self, data: Any, result: Any) -> None:
        """Collect CI metadata at top level, add metadata at every level.

        Calls ``super().start_suite()`` for depth tracking and the
        ``on_suite_start`` hook, then decorates every suite result with
        CI metadata and formatted links.
        """
        super().start_suite(data, result)
        self._add_metadata_to_suite(data, result)

    def end_suite(self, data: Any, result: Any) -> None:
        """Add timing/statistics at every level, save JSON at top level.

        Adds execution timing and statistics to every suite result,
        then calls ``super().end_suite()`` for depth tracking and the
        ``on_suite_end`` hook (which saves JSON at top level).
        """
        self._add_timing_and_stats(data, result)
        super().end_suite(data, result)

    # ------------------------------------------------------------------
    # BaseListener hooks (top-level only)
    # ------------------------------------------------------------------

    def on_suite_start(self, data: Any, result: Any) -> None:
        self.start_time = datetime.now(UTC)
        self.ci_info = collect_ci_metadata()
        self.platform = self.ci_info.get("CI_Platform")

    def on_suite_end(self, data: Any, result: Any) -> None:
        self._save_metadata_json(result.metadata)

    # ------------------------------------------------------------------
    # Per-suite helpers
    # ------------------------------------------------------------------

    def _add_metadata_to_suite(self, data: Any, result: Any) -> None:
        """Add CI metadata and formatted links to a suite result."""
        # Log CI information
        if self.ci_info.get("CI"):
            logger.info(
                f"Running in CI environment: "
                f"{self.ci_info.get('Project_URL', 'Unknown')}"
            )
            logger.info(f"Commit: {self.ci_info.get('Commit_SHA', 'Unknown')[:8]}")
            logger.info(f"Branch: {self.ci_info.get('Branch', 'Unknown')}")

        # Add metadata to suite result
        metadata = result.metadata
        metadata.update(self.ci_info)

        project_url = self.ci_info.get("Project_URL", "")
        commit_sha = self.ci_info.get("Commit_SHA", "")
        commit_short = self.ci_info.get(
            "Commit_Short_SHA", commit_sha[:8] if commit_sha else ""
        )

        # Format Commit_SHA as a clickable link
        if project_url and commit_sha:
            metadata["Commit_SHA"] = self._format_commit_link(
                project_url, commit_sha, commit_short
            )

        # Format Job_URL as a clickable link
        job_url = self.ci_info.get("Job_URL", "")
        job_name = self.ci_info.get("Job_Name", "")
        job_id = self.ci_info.get("Job_ID", "")
        if job_url:
            label = job_name or (f"Job #{job_id}" if job_id else "Job")
            metadata["Job_URL"] = f"[{label}|{job_url}]"

        # Format Source as a clickable link to the file at the commit
        source = str(data.source) if data.source else ""
        if source and project_url and commit_sha:
            rel_path = self._resolve_relative_path(source)
            metadata["Source"] = self._format_source_link(
                project_url, commit_sha, rel_path
            )

    def _add_timing_and_stats(self, data: Any, result: Any) -> None:
        """Add execution timing and statistics to a suite result."""
        metadata = result.metadata

        end_time = datetime.now(UTC)
        duration = (
            (end_time - self.start_time).total_seconds() if self.start_time else 0
        )

        # Add execution metadata
        metadata["Test_Duration_Seconds"] = str(duration)
        metadata["Test_End_Time"] = end_time.replace(tzinfo=None).isoformat() + "Z"
        metadata["Test_Start_Time"] = (
            self.start_time.replace(tzinfo=None).isoformat() + "Z"
            if self.start_time
            else ""
        )

        # Add summary statistics
        stats = result.statistics
        metadata["Total_Tests"] = str(stats.total)
        metadata["Passed_Tests"] = str(stats.passed)
        metadata["Failed_Tests"] = str(stats.failed)
        metadata["Skipped_Tests"] = str(stats.skipped)

        logger.info(
            f"Suite '{data.name}' completed: {stats.passed} passed, "
            f"{stats.failed} failed, "
            f"{stats.skipped} skipped"
        )

    def _format_commit_link(self, project_url: str, sha: str, short_sha: str) -> str:
        """Format a commit SHA as a clickable GitHub link."""
        return f"[{short_sha}|{project_url}/commit/{sha}]"

    def _format_source_link(self, project_url: str, sha: str, rel_path: str) -> str:
        """Format a source file path as a clickable GitHub link."""
        return f"[{rel_path}|{project_url}/blob/{sha}/{rel_path}]"

    def _resolve_relative_path(self, source: str) -> str:
        """Resolve a source path to a repository-relative path."""
        workspace = os.getenv("GITHUB_WORKSPACE", "")
        if workspace and source.startswith(workspace):
            return source[len(workspace) :].lstrip(os.sep)
        return source

    def _save_metadata_json(self, metadata: Dict[str, str]) -> None:
        """Save metadata to a JSON file for external tools."""
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

    def start_suite(self, suite: Any) -> None:  # type: ignore[override]
        """Modify suite with CI metadata.

        Called by Robot Framework before execution.
        """
        self.start_time = datetime.now(UTC)
        self.ci_info = collect_ci_metadata()
        self.platform = self.ci_info.get("CI_Platform")

        # Add metadata to suite
        for key, value in self.ci_info.items():
            suite.metadata[key] = value

        logger.info(f"Added {len(self.ci_info)} CI metadata items to suite")


def main() -> int:
    """Entry point for testing the listener."""
    metadata = collect_ci_metadata()

    print("CI Metadata collected:")
    print(json.dumps(metadata, indent=2))

    return 0 if metadata.get("CI") == "true" else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
