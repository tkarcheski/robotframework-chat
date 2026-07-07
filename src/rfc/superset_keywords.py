"""Robot Framework keywords for Superset/PostgreSQL connectivity checks."""

from __future__ import annotations

import os
from typing import Dict

from robot.api import logger
from robot.api.deco import keyword

from rfc.test_database import TestDatabase


class SupersetKeywords:
    """Keywords for verifying Superset/PostgreSQL connectivity."""

    ROBOT_LIBRARY_SCOPE = "SUITE"

    def __init__(self) -> None:
        self._db: TestDatabase | None = None

    def _get_db(self) -> TestDatabase:
        """Return a TestDatabase instance, creating one if needed."""
        if self._db is None:
            database_url = os.environ.get("DATABASE_URL")
            if not database_url:
                from .exceptions import MissingEnvironmentError

                raise MissingEnvironmentError(variable="DATABASE_URL")
            self._db = TestDatabase(database_url=database_url)
        return self._db

    @keyword("Connect To Database")
    def connect_to_database(self) -> str:
        """Verify that the database is reachable and return the PostgreSQL version."""
        db = self._get_db()
        version = db.get_version()
        logger.info(f"Connected to database: {version}")
        logger.console(f"  Database: {version}")
        return version

    @keyword("Get Table Row Counts")
    def get_table_row_counts(self) -> Dict[str, int]:
        """Return row counts for all RFC tables."""
        db = self._get_db()
        tables = [
            "test_runs",
            "test_results",
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
        """Return the masked DATABASE_URL for logging (password replaced with ****)."""
        url = os.environ.get("DATABASE_URL", "")
        if not url:
            return "NOT SET"
        if "@" in url:
            pre, rest = url.split("@", 1)
            if ":" in pre:
                scheme_user = pre.rsplit(":", 1)[0]
                return f"{scheme_user}:****@{rest}"
        return url
