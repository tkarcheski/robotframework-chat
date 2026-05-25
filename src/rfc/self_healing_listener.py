"""Self-healing event listener for Robot Framework.

Captures self-healing metadata emitted via RFC_DATA by the
:func:`~rfc.self_healing.self_healing` decorator and persists
healing events for nightly analysis and database archival.

Opt-in: add ``--listener rfc.self_healing_listener.SelfHealingListener``
to your Robot Framework invocation when self-healing is active.

Usage in ``config/test_suites.yaml``::

    ci:
      listeners:
        - "rfc.self_healing_listener.SelfHealingListener"
"""

import json
import logging
from typing import Any, ClassVar, Dict, List

from .base_listener import BaseListener

logger = logging.getLogger(__name__)

_HEALING_PREFIX = "self_healing_"


class SelfHealingEvent:
    """A single test's self-healing event data."""

    __slots__ = (
        "test_name",
        "test_status",
        "attempts",
        "strategy",
        "strategies_tried",
        "success",
        "original_error",
        "prompt_history",
        "duration_seconds",
    )

    def __init__(
        self,
        test_name: str,
        test_status: str,
        healing_data: Dict[str, str],
    ) -> None:
        self.test_name = test_name
        self.test_status = test_status
        self.attempts = int(healing_data.get("self_healing_attempts", "0"))
        self.strategy = healing_data.get("self_healing_strategy", "")
        self.success = healing_data.get("self_healing_success", "") == "True"
        self.original_error = healing_data.get("self_healing_original_error", "")
        self.duration_seconds = float(
            healing_data.get("self_healing_duration_seconds", "0.0")
        )

        strategies_raw = healing_data.get("self_healing_strategies_tried", "[]")
        try:
            self.strategies_tried: List[str] = json.loads(strategies_raw)
        except (json.JSONDecodeError, TypeError):
            self.strategies_tried = []

        prompt_raw = healing_data.get("self_healing_prompt_history", "[]")
        try:
            self.prompt_history: List[str] = json.loads(prompt_raw)
        except (json.JSONDecodeError, TypeError):
            self.prompt_history = []

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a dictionary for database storage or JSON export."""
        return {
            "test_name": self.test_name,
            "test_status": self.test_status,
            "attempts": self.attempts,
            "strategy": self.strategy,
            "strategies_tried": self.strategies_tried,
            "success": self.success,
            "original_error": self.original_error,
            "prompt_history": self.prompt_history,
            "duration_seconds": self.duration_seconds,
        }


class SelfHealingListener(BaseListener):
    """Captures self-healing events for database persistence and analysis.

    Listens for RFC_DATA keys prefixed with ``self_healing_`` and collects
    them into :class:`SelfHealingEvent` objects. At suite end, all events
    are available via :attr:`healing_events` for persistence or export.

    This listener is passive — it observes and records. The active healing
    logic lives in :func:`~rfc.self_healing.self_healing`.
    """

    ROBOT_LISTENER_API_VERSION = 3

    TRACKED_KEYWORDS: ClassVar[Dict[str, str]] = {
        "Ask LLM": "input",
        "Grade Answer": "grading",
        "Ask And Grade With Retry": "grading",
    }

    def __init__(self) -> None:
        super().__init__()
        self._healing_events: List[SelfHealingEvent] = []

    @property
    def healing_events(self) -> List[SelfHealingEvent]:
        """All healing events captured during this suite run."""
        return list(self._healing_events)

    def on_test_end(self, data: Any, result: Any) -> None:
        """Capture healing metadata from RFC_DATA at test end."""
        healing_data = {
            k: v
            for k, v in self._current_test_data.items()
            if k.startswith(_HEALING_PREFIX)
        }
        if not healing_data:
            return

        event = SelfHealingEvent(
            test_name=data.name,
            test_status=result.status,
            healing_data=healing_data,
        )
        self._healing_events.append(event)

        logger.info(
            "Self-healing event: test=%s attempts=%d strategy=%s success=%s",
            event.test_name,
            event.attempts,
            event.strategy,
            event.success,
        )

    def on_suite_end(self, data: Any, result: Any) -> None:
        """Log summary of healing events at suite end."""
        if not self._healing_events:
            return

        total = len(self._healing_events)
        successes = sum(1 for e in self._healing_events if e.success)
        logger.info(
            "Self-healing summary: %d events, %d successful, %d exhausted",
            total,
            successes,
            total - successes,
        )


__all__ = ["SelfHealingEvent", "SelfHealingListener"]
