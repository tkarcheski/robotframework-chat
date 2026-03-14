"""Robot Framework keywords for Superset/PostgreSQL connectivity checks.

Provides keywords to verify database connectivity, push host information,
and validate the data pipeline from test execution through to Superset.

Usage in Robot Framework::

    Library    rfc.superset_keywords.SupersetKeywords    WITH NAME    Superset
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from robot.api import logger
from robot.api.deco import keyword

from rfc import __version__
from rfc.host_info import collect_host_info
from rfc.test_database import HostInfo, TestDatabase


class SupersetKeywords:
    """Keywords for verifying Superset/PostgreSQL connectivity and pushing host info."""

    ROBOT_LIBRARY_SCOPE = "SUITE"

    def __init__(self) -> None:
        self._db: TestDatabase | None = None

    def _get_db(self) -> TestDatabase:
        """Return a TestDatabase instance, creating one if needed."""
        if self._db is None:
            database_url = os.environ.get("DATABASE_URL")
            if not database_url:
                raise RuntimeError(
                    "DATABASE_URL is not set. "
                    "Set it in .env or export it in your shell."
                )
            self._db = TestDatabase(database_url=database_url)
        return self._db

    @keyword("Connect To Database")
    def connect_to_database(self) -> str:
        """Verify that the database is reachable and return the PostgreSQL version.

        Raises:
            RuntimeError: If DATABASE_URL is not set or connection fails.

        Returns:
            PostgreSQL version string.
        """
        db = self._get_db()
        version = db.get_version()
        logger.info(f"Connected to database: {version}")
        logger.console(f"  Database: {version}")
        return version

    @keyword("Push Host Info")
    def push_host_info(self) -> Dict[str, Any]:
        """Collect and push host hardware/OS info to the database.

        Performs an upsert on the ``host_info`` table keyed by hostname.

        Returns:
            Dictionary of collected host metrics.
        """
        db = self._get_db()
        info = collect_host_info()
        host = HostInfo(
            hostname=info["hostname"],
            os_name=info["os_name"],
            os_version=info["os_version"],
            cpu_arch=info["cpu_arch"],
            cpu_count=info["cpu_count"],
            total_ram_gb=info["total_ram_gb"],
            gpu_info=info.get("gpu_info"),
            rfc_version=__version__,
        )
        db.add_or_update_host(host)
        logger.info(f"Host info pushed: {info['hostname']}")
        logger.console(f"  Host registered: {info['hostname']}")
        return info

    @keyword("Get All Hosts")
    def get_all_hosts(self) -> List[Dict[str, Any]]:
        """Return all registered hosts from the database.

        Returns:
            List of host info dictionaries.
        """
        db = self._get_db()
        hosts = db.get_hosts()
        for h in hosts:
            logger.info(f"  {h.get('hostname', '?')}: {h}")
        return hosts

    @keyword("Get Table Row Counts")
    def get_table_row_counts(self) -> Dict[str, int]:
        """Return row counts for all RFC tables.

        Returns:
            Dictionary mapping table name to row count.
        """
        db = self._get_db()
        tables = [
            "test_runs",
            "test_results",
            "models",
            "pipeline_results",
            "robot_dry_run_results",
            "keyword_results",
            "ollama_metrics",
            "host_info",
        ]
        counts: Dict[str, int] = {}
        for table in tables:
            try:
                count = db.get_table_row_count(table)
                counts[table] = count
                logger.info(f"  {table}: {count} rows")
            except Exception as e:
                logger.warn(f"  {table}: query failed — {e}")
                counts[table] = -1
        return counts

    @keyword("Get Database URL")
    def get_database_url(self) -> str:
        """Return the masked DATABASE_URL for logging.

        Returns:
            Masked connection string (password replaced with ``****``).
        """
        url = os.environ.get("DATABASE_URL", "")
        if not url:
            return "NOT SET"
        if "@" in url:
            pre, rest = url.split("@", 1)
            if ":" in pre:
                scheme_user = pre.rsplit(":", 1)[0]
                return f"{scheme_user}:****@{rest}"
        return url
