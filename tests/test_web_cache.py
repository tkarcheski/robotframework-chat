"""Unit tests for web search cache."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rfc.web_cache import SearchResult, WebSearchCache


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "test_cache.db"


@pytest.fixture
def cache(tmp_db: Path) -> WebSearchCache:
    return WebSearchCache(db_path=str(tmp_db), ttl_seconds=3600)


# ---------------------------------------------------------------------------
# SearchResult
# ---------------------------------------------------------------------------


class TestSearchResult:
    def test_creation(self) -> None:
        sr = SearchResult(title="Test", url="https://example.com", snippet="A snippet")
        assert sr.title == "Test"
        assert sr.url == "https://example.com"

    def test_to_dict(self) -> None:
        sr = SearchResult(title="T", url="U", snippet="S")
        d = sr.to_dict()
        assert d == {"title": "T", "url": "U", "snippet": "S"}

    def test_from_dict(self) -> None:
        d = {"title": "T", "url": "U", "snippet": "S"}
        sr = SearchResult.from_dict(d)
        assert sr.title == "T"


# ---------------------------------------------------------------------------
# WebSearchCache — database initialization
# ---------------------------------------------------------------------------


class TestCacheInit:
    def test_creates_db_file(self, tmp_db: Path) -> None:
        WebSearchCache(db_path=str(tmp_db))
        assert tmp_db.exists()

    def test_creates_table(self, tmp_db: Path) -> None:
        WebSearchCache(db_path=str(tmp_db))
        conn = sqlite3.connect(str(tmp_db))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='search_cache'"
        )
        assert cursor.fetchone() is not None
        conn.close()


# ---------------------------------------------------------------------------
# WebSearchCache — cache operations
# ---------------------------------------------------------------------------


class TestCacheOperations:
    def test_put_and_get(self, cache: WebSearchCache) -> None:
        results = [SearchResult(title="A", url="U", snippet="S")]
        cache.put("test query", results)
        cached = cache.get("test query")
        assert cached is not None
        assert len(cached) == 1
        assert cached[0].title == "A"

    def test_get_miss_returns_none(self, cache: WebSearchCache) -> None:
        assert cache.get("nonexistent query") is None

    def test_query_normalization(self, cache: WebSearchCache) -> None:
        results = [SearchResult(title="A", url="U", snippet="S")]
        cache.put("  TEST  Query  ", results)
        cached = cache.get("test query")
        assert cached is not None

    def test_ttl_expiry(self, tmp_db: Path) -> None:
        cache = WebSearchCache(db_path=str(tmp_db), ttl_seconds=1)
        results = [SearchResult(title="A", url="U", snippet="S")]
        cache.put("query", results)

        # Should be in cache
        assert cache.get("query") is not None

        # Wait for expiry
        time.sleep(1.1)
        assert cache.get("query") is None

    def test_clear_cache(self, cache: WebSearchCache) -> None:
        results = [SearchResult(title="A", url="U", snippet="S")]
        cache.put("q1", results)
        cache.put("q2", results)
        cache.clear()
        assert cache.get("q1") is None
        assert cache.get("q2") is None

    def test_warm_cache(self, cache: WebSearchCache) -> None:
        entries = {
            "query1": [SearchResult(title="A", url="U", snippet="S")],
            "query2": [SearchResult(title="B", url="V", snippet="T")],
        }
        cache.warm(entries)
        assert cache.get("query1") is not None
        assert cache.get("query2") is not None
        assert cache.get("query1")[0].title == "A"

    def test_multiple_results_per_query(self, cache: WebSearchCache) -> None:
        results = [
            SearchResult(title="A", url="U1", snippet="S1"),
            SearchResult(title="B", url="U2", snippet="S2"),
            SearchResult(title="C", url="U3", snippet="S3"),
        ]
        cache.put("multi", results)
        cached = cache.get("multi")
        assert len(cached) == 3
        assert cached[2].title == "C"


# ---------------------------------------------------------------------------
# WebSearchCache — search with fetch fallback
# ---------------------------------------------------------------------------


class TestCacheSearch:
    def test_search_returns_cached(self, cache: WebSearchCache) -> None:
        results = [SearchResult(title="Cached", url="U", snippet="S")]
        cache.put("my query", results)
        found = cache.search("my query")
        assert found[0].title == "Cached"

    def test_search_fetches_on_miss(self, cache: WebSearchCache) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [{"title": "Fetched", "url": "http://x.com", "snippet": "snip"}]
        }

        with patch("rfc.web_cache.requests.get", return_value=mock_response):
            cache.endpoint = "http://search-api.test/search"
            found = cache.search("new query")

        assert len(found) == 1
        assert found[0].title == "Fetched"
        # Should now be cached
        cached = cache.get("new query")
        assert cached is not None

    def test_search_returns_empty_on_no_endpoint(self, cache: WebSearchCache) -> None:
        cache.endpoint = ""
        found = cache.search("query with no endpoint")
        assert found == []

    def test_format_as_context(self, cache: WebSearchCache) -> None:
        results = [
            SearchResult(title="Result 1", url="http://a.com", snippet="First result"),
            SearchResult(title="Result 2", url="http://b.com", snippet="Second result"),
        ]
        context = cache.format_as_context(results)
        assert "Result 1" in context
        assert "First result" in context
        assert "Result 2" in context

    def test_format_as_context_empty(self, cache: WebSearchCache) -> None:
        """Empty results list returns empty string (line 179)."""
        assert cache.format_as_context([]) == ""

    def test_fetch_and_cache_request_error(self, cache: WebSearchCache) -> None:
        """Request exception returns empty list (lines 165-166)."""
        cache.endpoint = "http://search-api.test/search"
        import requests

        with patch(
            "rfc.web_cache.requests.get",
            side_effect=requests.exceptions.ConnectionError("fail"),
        ):
            result = cache.search("failing query")
        assert result == []
