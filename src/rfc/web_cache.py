"""SQLite-backed web search cache for CEO agent pipeline.

Provides a simple cache layer that stores web search results with
configurable TTL, reducing external API calls during repeated test runs.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


@dataclass
class SearchResult:
    """A single web search result."""

    title: str
    url: str
    snippet: str

    def to_dict(self) -> Dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> SearchResult:
        return cls(title=d["title"], url=d["url"], snippet=d["snippet"])


def _normalize_query(query: str) -> str:
    """Normalize a search query for cache key consistency."""
    return re.sub(r"\s+", " ", query.strip().lower())


class WebSearchCache:
    """SQLite-backed cache for web search results.

    Args:
        db_path: Path to the SQLite database file.
        ttl_seconds: Time-to-live for cache entries in seconds.
        endpoint: URL of the web search API endpoint.
    """

    def __init__(
        self,
        db_path: str = "",
        ttl_seconds: int = 86400,
        endpoint: str = "",
    ) -> None:
        if not db_path:
            cache_dir = Path.home() / ".rfc"
            cache_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(cache_dir / "web_cache.db")

        self.db_path = db_path
        self.ttl_seconds = ttl_seconds
        self.endpoint = endpoint or os.getenv("WEB_SEARCH_ENDPOINT", "")

        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS search_cache (
                query TEXT PRIMARY KEY,
                results TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
            """
        )
        conn.commit()
        conn.close()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def put(self, query: str, results: List[SearchResult]) -> None:
        """Store search results in the cache."""
        key = _normalize_query(query)
        data = json.dumps([r.to_dict() for r in results])
        conn = self._conn()
        conn.execute(
            "INSERT OR REPLACE INTO search_cache (query, results, timestamp) "
            "VALUES (?, ?, ?)",
            (key, data, time.time()),
        )
        conn.commit()
        conn.close()

    def get(self, query: str) -> Optional[List[SearchResult]]:
        """Retrieve cached results, or None if missing/expired."""
        key = _normalize_query(query)
        conn = self._conn()
        cursor = conn.execute(
            "SELECT results, timestamp FROM search_cache WHERE query = ?",
            (key,),
        )
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        results_json, timestamp = row
        if time.time() - timestamp > self.ttl_seconds:
            return None

        items = json.loads(results_json)
        return [SearchResult.from_dict(item) for item in items]

    def clear(self) -> None:
        """Clear all cached entries."""
        conn = self._conn()
        conn.execute("DELETE FROM search_cache")
        conn.commit()
        conn.close()

    def warm(self, entries: Dict[str, List[SearchResult]]) -> None:
        """Pre-populate the cache with known entries.

        Args:
            entries: Mapping of query string to search results.
        """
        for query, results in entries.items():
            self.put(query, results)

    def search(self, query: str) -> List[SearchResult]:
        """Search with cache-first strategy.

        Returns cached results if available and fresh. Otherwise fetches
        from the configured endpoint, caches the results, and returns them.
        Returns an empty list if no endpoint is configured and cache misses.
        """
        cached = self.get(query)
        if cached is not None:
            return cached

        if not self.endpoint:
            return []

        return self._fetch_and_cache(query)

    def _fetch_and_cache(self, query: str) -> List[SearchResult]:
        """Fetch results from the web search API and cache them."""
        try:
            response = requests.get(
                self.endpoint,
                params={"q": query},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            results = [
                SearchResult.from_dict(item)
                for item in data.get("results", [])
            ]
            self.put(query, results)
            return results
        except (requests.RequestException, KeyError, TypeError):
            return []

    @staticmethod
    def format_as_context(results: List[SearchResult]) -> str:
        """Format search results as context text for LLM prompts.

        Args:
            results: List of search results to format.

        Returns:
            Formatted string suitable for injection into prompts.
        """
        if not results:
            return ""

        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] {r.title}")
            lines.append(f"    {r.snippet}")
            lines.append(f"    Source: {r.url}")
            lines.append("")

        return "\n".join(lines)
