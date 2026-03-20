"""Reusable base class for Robot Framework Listener API v3 listeners.

Provides:
- Suite depth tracking with template-method hooks at top-level boundaries
- Automatic RFC_DATA structured log message capture per test
- Configurable keyword tracking with type classification

This module intentionally avoids project-specific imports so it can be
extracted into a standalone package in the future.

Usage::

    class MyListener(BaseListener):
        TRACKED_KEYWORDS = {"Ask LLM": "input", "Set LLM Model": "config"}

        def on_suite_start(self, data, result):
            ...  # called once when the top-level suite starts

        def on_test_end(self, data, result):
            metrics = self._current_test_data  # RFC_DATA captured here
            ...
"""

from typing import Any, ClassVar, Dict, Optional

from robot.api.interfaces import ListenerV3  # type: ignore


class BaseListener(ListenerV3):
    """Abstract base for Robot Framework v3 listeners.

    Subclasses override ``on_*`` hooks instead of the raw Listener API
    methods.  Suite depth tracking, RFC_DATA parsing, and keyword
    dispatch are handled automatically.

    Class variables:
        TRACKED_KEYWORDS: Mapping of keyword name → type string.
            Subclasses set this to receive ``on_keyword_start`` /
            ``on_keyword_end`` callbacks for matching keywords.
        RFC_DATA_PREFIX: Prefix for structured log messages.
            Defaults to ``"RFC_DATA:"``.
    """

    ROBOT_LISTENER_API_VERSION = 3

    TRACKED_KEYWORDS: ClassVar[Dict[str, str]] = {}
    RFC_DATA_PREFIX: ClassVar[str] = "RFC_DATA:"

    def __init__(self) -> None:
        self._suite_depth: int = 0
        self._current_test_data: Dict[str, str] = {}
        self._in_tracked_keyword: Optional[str] = None

    # ------------------------------------------------------------------
    # Suite lifecycle (template method)
    # ------------------------------------------------------------------

    def start_suite(self, data: Any, result: Any) -> None:
        """Increment depth; call :meth:`on_suite_start` at top level."""
        self._suite_depth += 1
        if self._suite_depth == 1:
            self.on_suite_start(data, result)

    def end_suite(self, data: Any, result: Any) -> None:
        """Decrement depth; call :meth:`on_suite_end` at top level."""
        self._suite_depth -= 1
        if self._suite_depth == 0:
            self.on_suite_end(data, result)

    # ------------------------------------------------------------------
    # Test lifecycle
    # ------------------------------------------------------------------

    def start_test(self, data: Any, result: Any) -> None:
        """Reset per-test data and call :meth:`on_test_start`."""
        self._current_test_data = {}
        self.on_test_start(data, result)

    def end_test(self, data: Any, result: Any) -> None:
        """Call :meth:`on_test_end` then clear per-test data."""
        self.on_test_end(data, result)
        self._current_test_data = {}

    # ------------------------------------------------------------------
    # Log message capture (RFC_DATA)
    # ------------------------------------------------------------------

    def log_message(self, message: Any) -> None:
        """Parse ``RFC_DATA:`` messages; delegate others to :meth:`on_log_message`."""
        text = message.message
        if not isinstance(text, str):
            return
        prefix = self.RFC_DATA_PREFIX
        if text.startswith(prefix):
            payload = text[len(prefix) :]
            key, _, value = payload.partition(":")
            if key:
                self._current_test_data[key] = value
            return
        self.on_log_message(message)

    # ------------------------------------------------------------------
    # Keyword tracking
    # ------------------------------------------------------------------

    def start_keyword(self, data: Any, result: Any) -> None:
        """Dispatch tracked keywords to :meth:`on_keyword_start`."""
        keyword_type = self.TRACKED_KEYWORDS.get(data.name)
        if keyword_type is None:
            return
        self._in_tracked_keyword = data.name
        self.on_keyword_start(data, result, keyword_type)

    def end_keyword(self, data: Any, result: Any) -> None:
        """Dispatch tracked keyword end to :meth:`on_keyword_end`."""
        if self._in_tracked_keyword is None:
            return
        if self._in_tracked_keyword != data.name:
            return
        self.on_keyword_end(data, result)
        self._in_tracked_keyword = None

    # ------------------------------------------------------------------
    # Template hooks — override in subclasses
    # ------------------------------------------------------------------

    def on_suite_start(self, data: Any, result: Any) -> None:
        """Called once when the top-level suite starts (depth == 1)."""

    def on_suite_end(self, data: Any, result: Any) -> None:
        """Called once when the top-level suite ends (depth == 0)."""

    def on_test_start(self, data: Any, result: Any) -> None:
        """Called at the start of each test case."""

    def on_test_end(self, data: Any, result: Any) -> None:
        """Called at the end of each test case (before data is cleared)."""

    def on_log_message(self, message: Any) -> None:
        """Called for non-RFC_DATA log messages."""

    def on_keyword_start(self, data: Any, result: Any, keyword_type: str) -> None:
        """Called when a tracked keyword starts."""

    def on_keyword_end(self, data: Any, result: Any) -> None:
        """Called when the current tracked keyword ends."""
