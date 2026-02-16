"""Sync CI pipeline test artifacts to the database.

Fetches output.xml artifacts from recent GitLab CI pipeline jobs
and imports them into the test database (PostgreSQL/Superset).

Reuses:
  - GitLab API patterns from dashboard/monitoring.py
  - Import logic from scripts/import_test_results.py
  - Database from src/rfc/test_database.py

Environment variables:
  GITLAB_API_URL     - GitLab instance base URL
  GITLAB_PROJECT_ID  - Numeric project ID
  GITLAB_TOKEN       - API token with read_api scope
  DATABASE_URL       - PostgreSQL connection string (for Superset)
"""

import argparse
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

import requests

# Add src and scripts to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from import_test_results import import_results
from rfc.test_database import TestDatabase

_log = logging.getLogger(__name__)


class GitLabArtifactFetcher:
    """Fetch pipeline artifacts from the GitLab API.

    Resolution priority for GitLab settings:
    1. Explicit constructor parameters
    2. CI_API_V4_URL / CI_PROJECT_ID (inside GitLab CI)
    3. GITLAB_API_URL / GITLAB_PROJECT_ID env vars
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        project_id: Optional[str] = None,
        token: Optional[str] = None,
    ) -> None:
        self._api_url, self._project_id, self._token = self._resolve_settings(
            api_url, project_id, token
        )
        if not self._api_url or not self._project_id:
            raise ValueError(
                "GitLab API URL and project ID are required. "
                "Set GITLAB_API_URL/GITLAB_PROJECT_ID env vars, "
                "or pass api_url/project_id to constructor."
            )

    @property
    def api_url(self) -> str:
        """Return the resolved GitLab API base URL."""
        return self._api_url

    @property
    def project_id(self) -> str:
        """Return the resolved GitLab project ID."""
        return self._project_id

    @property
    def has_token(self) -> bool:
        """Return True if a private token is configured."""
        return bool(self._token)

    def _resolve_settings(
        self,
        api_url: Optional[str],
        project_id: Optional[str],
        token: Optional[str],
    ) -> tuple[str, str, str]:
        """Resolve GitLab API settings from params or environment."""
        # Explicit params take priority
        resolved_token = (
            token if token is not None else os.environ.get("GITLAB_TOKEN", "")
        )
        if api_url and project_id:
            return api_url.rstrip("/"), project_id, resolved_token

        # CI_API_V4_URL / CI_PROJECT_ID (inside GitLab CI)
        ci_api = os.environ.get("CI_API_V4_URL", "")
        ci_pid = os.environ.get("CI_PROJECT_ID", "")
        if ci_api and ci_pid:
            # CI_API_V4_URL is like https://gitlab.example.com/api/v4
            base_url = ci_api.rsplit("/api/v4", 1)[0]
            return base_url, ci_pid, resolved_token

        # GITLAB_API_URL / GITLAB_PROJECT_ID env vars
        env_api = os.environ.get("GITLAB_API_URL", "")
        env_pid = os.environ.get("GITLAB_PROJECT_ID", "")
        if env_api and env_pid:
            return env_api.rstrip("/"), env_pid, resolved_token

        return "", "", resolved_token

    def _headers(self) -> dict[str, str]:
        """Build HTTP headers for GitLab API requests."""
        headers: dict[str, str] = {}
        if self._token:
            headers["PRIVATE-TOKEN"] = self._token
        return headers

    def check_connection(self) -> dict[str, Any]:
        """Check GitLab API connectivity.

        Returns:
            Dictionary with status, status_code, and message.
        """
        url = f"{self._api_url}/api/v4/projects/{self._project_id}"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=10)
            if resp.status_code == 200:
                project = resp.json()
                return {
                    "ok": True,
                    "status_code": 200,
                    "message": f"Connected to {project.get('name_with_namespace', self._project_id)}",
                }
            return {
                "ok": False,
                "status_code": resp.status_code,
                "message": f"HTTP {resp.status_code}",
            }
        except requests.exceptions.RequestException as exc:
            _log.warning("Connection check failed: %s", exc)
            return {
                "ok": False,
                "status_code": 0,
                "message": f"Unreachable: {exc}",
            }

    def fetch_recent_pipelines(
        self,
        ref: Optional[str] = None,
        status: str = "success",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Fetch recent pipelines from GitLab API.

        Args:
            ref: Optional branch filter.
            status: Pipeline status filter (default: success).
            limit: Maximum number of pipelines to return.

        Returns:
            List of pipeline dictionaries.
        """
        url = (
            f"{self._api_url}/api/v4/projects/{self._project_id}"
            f"/pipelines?status={status}&per_page={limit}"
            f"&order_by=updated_at&sort=desc"
        )
        if ref:
            url += f"&ref={ref}"

        try:
            resp = requests.get(url, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as exc:
            _log.warning("Failed to fetch pipelines: %s", exc)
            return []

    def fetch_pipeline_jobs(
        self,
        pipeline_id: int,
        scope: str = "success",
    ) -> list[dict[str, Any]]:
        """Fetch jobs from a specific pipeline.

        Args:
            pipeline_id: GitLab pipeline ID.
            scope: Job scope filter (default: success).

        Returns:
            List of job dictionaries.
        """
        url = (
            f"{self._api_url}/api/v4/projects/{self._project_id}"
            f"/pipelines/{pipeline_id}/jobs?scope[]={scope}&per_page=100"
        )

        try:
            resp = requests.get(url, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as exc:
            _log.warning("Failed to fetch jobs for pipeline %d: %s", pipeline_id, exc)
            return []

    def download_job_artifact(
        self,
        job_id: int,
        output_dir: str,
        artifact_path: str = "output.xml",
    ) -> Optional[str]:
        """Download a specific artifact file from a job.

        Args:
            job_id: GitLab job ID.
            output_dir: Directory to save the artifact.
            artifact_path: Path within artifacts archive (default: output.xml).

        Returns:
            Path to downloaded file, or None if not found.
        """
        url = (
            f"{self._api_url}/api/v4/projects/{self._project_id}"
            f"/jobs/{job_id}/artifacts/{artifact_path}"
        )

        try:
            resp = requests.get(url, headers=self._headers(), timeout=60)
            resp.raise_for_status()
        except requests.exceptions.RequestException as exc:
            _log.debug("Artifact download failed for job %d: %s", job_id, exc)
            return None

        # Sanitize artifact_path: slashes would create subdirectories
        safe_name = artifact_path.replace("/", "_")
        out_path = os.path.join(output_dir, f"job_{job_id}_{safe_name}")
        with open(out_path, "wb") as f:
            f.write(resp.content)
        return out_path


# Known artifact paths where output.xml may be stored in CI jobs.
# The generated pipeline stores results under results/<suite>/.
# We try each path in order until one succeeds.
_ARTIFACT_PATHS = [
    "output.xml",
    "results/math/output.xml",
    "results/docker/output.xml",
    "results/safety/output.xml",
    "results/dashboard/output.xml",
]


def sync_ci_results(
    fetcher: GitLabArtifactFetcher,
    db: TestDatabase,
    pipeline_limit: int = 5,
    ref: Optional[str] = None,
    artifact_paths: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Fetch recent CI pipeline artifacts and import into database.

    Args:
        fetcher: Configured GitLab API client.
        db: Database instance.
        pipeline_limit: Number of recent pipelines to process.
        ref: Optional branch filter.
        artifact_paths: Artifact paths to try per job (default: _ARTIFACT_PATHS).

    Returns:
        Dictionary with sync results.
    """
    paths_to_try = artifact_paths if artifact_paths is not None else _ARTIFACT_PATHS

    result: dict[str, Any] = {
        "pipelines_checked": 0,
        "artifacts_downloaded": 0,
        "runs_imported": 0,
        "errors": [],
    }

    pipelines = fetcher.fetch_recent_pipelines(
        ref=ref, status="success", limit=pipeline_limit
    )

    # Get existing pipeline URLs to avoid duplicates
    recent_runs = db.get_recent_runs(limit=100)
    existing_urls = {run.get("pipeline_url", "") for run in recent_runs if run}

    with tempfile.TemporaryDirectory() as tmpdir:
        for pipeline in pipelines:
            result["pipelines_checked"] += 1
            pipeline_url = pipeline.get("web_url", "")

            # Skip already-imported pipelines
            if pipeline_url and pipeline_url in existing_urls:
                continue

            pipeline_id = pipeline["id"]
            jobs = fetcher.fetch_pipeline_jobs(pipeline_id)

            for job in jobs:
                job_id = job["id"]

                # Try each known artifact path until one succeeds
                xml_path = None
                for artifact_path in paths_to_try:
                    xml_path = fetcher.download_job_artifact(
                        job_id=job_id,
                        output_dir=tmpdir,
                        artifact_path=artifact_path,
                    )
                    if xml_path is not None:
                        _log.debug(
                            "Found artifact for job %d at %s", job_id, artifact_path
                        )
                        break

                if xml_path is None:
                    continue

                result["artifacts_downloaded"] += 1

                try:
                    import_results(xml_path, db)
                    result["runs_imported"] += 1
                except Exception as e:
                    result["errors"].append(f"Failed to import job {job_id}: {e}")

    return result


def verify_sync(db: TestDatabase, min_runs: int = 1) -> dict[str, Any]:
    """Verify that data was successfully synced to the database.

    Args:
        db: Database instance to verify.
        min_runs: Minimum number of recent runs expected.

    Returns:
        Dictionary with verification results.
    """
    recent = db.get_recent_runs(limit=min_runs)
    models_found = list({run["model_name"] for run in recent if run.get("model_name")})
    latest_ts = recent[0]["timestamp"] if recent else None

    return {
        "success": len(recent) >= min_runs,
        "recent_runs": len(recent),
        "latest_timestamp": str(latest_ts) if latest_ts else None,
        "models_found": models_found,
    }


# ── CLI subcommand handlers ──────────────────────────────────────────


def _cmd_status(args: argparse.Namespace) -> None:
    """Check GitLab API connectivity."""
    fetcher = _make_fetcher()
    info = fetcher.check_connection()
    print(f"API:     {fetcher.api_url}")
    print(f"Project: {fetcher.project_id}")
    print(f"Token:   {'set' if fetcher.has_token else 'NOT set'}")
    print(f"Status:  {'OK' if info['ok'] else 'FAIL'} - {info['message']}")
    sys.exit(0 if info["ok"] else 1)


def _cmd_list_pipelines(args: argparse.Namespace) -> None:
    """List recent pipelines."""
    fetcher = _make_fetcher()
    pipelines = fetcher.fetch_recent_pipelines(ref=args.ref, limit=args.limit)
    if not pipelines:
        print("No pipelines found.")
        return
    for p in pipelines:
        print(
            f"  #{p['id']:>8}  {p.get('status', '?'):>10}  "
            f"{p.get('ref', '?'):<20}  {p.get('web_url', '')}"
        )


def _cmd_list_jobs(args: argparse.Namespace) -> None:
    """List jobs in a pipeline."""
    fetcher = _make_fetcher()
    jobs = fetcher.fetch_pipeline_jobs(args.pipeline_id, scope=args.scope)
    if not jobs:
        print(f"No jobs found for pipeline {args.pipeline_id}.")
        return
    for j in jobs:
        print(
            f"  #{j['id']:>8}  {j.get('status', '?'):>10}  "
            f"{j.get('name', '?')}"
        )


def _cmd_fetch_artifact(args: argparse.Namespace) -> None:
    """Download a single artifact."""
    fetcher = _make_fetcher()
    out_dir = args.output or "."
    path = fetcher.download_job_artifact(
        job_id=args.job_id,
        output_dir=out_dir,
        artifact_path=args.artifact_path,
    )
    if path:
        print(f"Downloaded: {path}")
    else:
        print(f"Artifact not found for job {args.job_id}.")
        sys.exit(1)


def _cmd_sync(args: argparse.Namespace) -> None:
    """Full sync + verify."""
    fetcher = _make_fetcher()
    db = _make_db(args)

    result = sync_ci_results(fetcher, db, pipeline_limit=args.limit, ref=args.ref)

    print("Sync complete:")
    print(f"  Pipelines checked: {result['pipelines_checked']}")
    print(f"  Artifacts downloaded: {result['artifacts_downloaded']}")
    print(f"  Runs imported: {result['runs_imported']}")
    if result["errors"]:
        print(f"  Errors ({len(result['errors'])}):")
        for err in result["errors"]:
            print(f"    - {err}")
        sys.exit(1)

    # Auto-verify after sync
    vresult = verify_sync(db)
    print(f"  Verify: {'PASS' if vresult['success'] else 'FAIL'}")


def _cmd_verify(args: argparse.Namespace) -> None:
    """Check database contents."""
    db = _make_db(args)
    result = verify_sync(db, min_runs=args.min_runs)
    print(f"Database verification: {'PASS' if result['success'] else 'FAIL'}")
    print(f"  Recent runs: {result['recent_runs']}")
    print(f"  Latest timestamp: {result['latest_timestamp']}")
    print(f"  Models found: {', '.join(result['models_found'])}")
    sys.exit(0 if result["success"] else 1)


# ── Helpers ───────────────────────────────────────────────────────────


def _make_fetcher() -> GitLabArtifactFetcher:
    """Create a GitLabArtifactFetcher, exiting on config error."""
    try:
        return GitLabArtifactFetcher()
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def _make_db(args: argparse.Namespace) -> TestDatabase:
    """Create a TestDatabase from CLI args."""
    if getattr(args, "db", None):
        return TestDatabase(db_path=args.db)
    return TestDatabase()


def main() -> None:
    """CLI entry point for CI pipeline sync."""
    parser = argparse.ArgumentParser(
        description="Sync CI pipeline test results to database"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging to stderr"
    )
    sub = parser.add_subparsers(dest="command")

    # status
    sub.add_parser("status", help="Check GitLab API connectivity")

    # list-pipelines
    lp = sub.add_parser("list-pipelines", help="List recent pipelines")
    lp.add_argument("-n", "--limit", type=int, default=10)
    lp.add_argument("--ref", help="Filter by branch")

    # list-jobs
    lj = sub.add_parser("list-jobs", help="List jobs in a pipeline")
    lj.add_argument("pipeline_id", type=int)
    lj.add_argument("--scope", default="success")

    # fetch-artifact
    fa = sub.add_parser("fetch-artifact", help="Download a single artifact")
    fa.add_argument("job_id", type=int)
    fa.add_argument("--artifact-path", default="output.xml")
    fa.add_argument("-o", "--output", help="Output directory (default: .)")

    # sync
    sp = sub.add_parser("sync", help="Full sync + verify")
    sp.add_argument("-n", "--limit", type=int, default=5)
    sp.add_argument("--ref", help="Filter by branch")
    sp.add_argument("--db", help="Database path")

    # verify
    vp = sub.add_parser("verify", help="Check database contents")
    vp.add_argument("--db", help="Database path")
    vp.add_argument("--min-runs", type=int, default=1)

    args = parser.parse_args()

    # Set up logging
    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=level, format="%(levelname)s: %(message)s", stream=sys.stderr
    )

    dispatch = {
        "status": _cmd_status,
        "list-pipelines": _cmd_list_pipelines,
        "list-jobs": _cmd_list_jobs,
        "fetch-artifact": _cmd_fetch_artifact,
        "sync": _cmd_sync,
        "verify": _cmd_verify,
    }

    if args.command in dispatch:
        dispatch[args.command](args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
