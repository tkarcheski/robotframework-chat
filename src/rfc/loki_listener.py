"""Robot Framework listener that pushes log entries to Grafana Loki.

Sends structured log entries for all Ollama interactions directly to
Loki via its HTTP push API.  Entries are batched during the test run
and flushed at the end of the top-level suite.

Labels attached to each log stream:
    job            - always ``robotframework``
    suite          - top-level suite name
    model          - active LLM model name
    event_type     - input | output | config | grading | system

Gracefully degrades when Loki is unreachable — a warning is logged
but test execution is never interrupted.

Usage:
    robot --listener rfc.loki_listener.LokiListener tests/
    robot --listener rfc.loki_listener.LokiListener:loki_url=http://loki:3100 tests/

The listener reads ``LOKI_URL`` from the environment if no explicit
URL is provided.  Default: ``http://localhost:3100``.
"""

import json
import os
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

import requests
from robot.api import logger  # type: ignore

# Keywords worth logging and their event types.
_KEYWORD_TYPES: Dict[str, str] = {
    "Ask LLM": "input",
    "Grade Answer": "grading",
    "Set LLM Endpoint": "config",
    "Set LLM Model": "config",
    "Set LLM Parameters": "config",
    "Wait For LLM": "system",
    "Get Running Models": "system",
    "LLM Is Busy": "system",
}

# Timeout for HTTP push to avoid blocking test execution.
_HTTP_TIMEOUT_SECONDS = 5


class LokiListener:
    """Listener that pushes Robot Framework log entries to Grafana Loki.

    Hooks into keyword start/end events to capture Ollama interactions,
    batches the entries, and pushes them to Loki's ``/loki/api/v1/push``
    endpoint when the top-level suite finishes.

    Usage:
        robot --listener rfc.loki_listener.LokiListener tests/
        robot --listener rfc.loki_listener.LokiListener:loki_url=<URL> tests/
    """

    ROBOT_LISTENER_API_VERSION = 2

    def __init__(self, loki_url: Optional[str] = None) -> None:
        self._loki_url = loki_url or os.getenv("LOKI_URL", "http://localhost:3100")
        self._model: str = os.getenv("DEFAULT_MODEL", "unknown")
        self._entries: List[Dict[str, str]] = []
        self._in_tracked_keyword: Optional[str] = None
        self._suite_depth: int = 0
        self._suite_name: Optional[str] = None

    # ------------------------------------------------------------------
    # Suite tracking
    # ------------------------------------------------------------------

    def start_suite(self, name: str, attributes: Dict[str, Any]) -> None:
        self._suite_depth += 1
        if self._suite_depth == 1:
            self._suite_name = name
            push_url = f"{self._loki_url}/loki/api/v1/push"
            banner = f"LokiListener: pushing logs to {push_url}"
            logger.info(banner)
            logger.console(banner)

    def end_suite(self, name: str, attributes: Dict[str, Any]) -> None:
        self._suite_depth -= 1
        if self._suite_depth > 0:
            return
        if not self._entries:
            return
        self._flush_to_loki()

    # ------------------------------------------------------------------
    # Keyword tracking
    # ------------------------------------------------------------------

    def start_keyword(self, name: str, attributes: Dict[str, Any]) -> None:
        event_type = _KEYWORD_TYPES.get(name)
        if event_type is None:
            return

        self._in_tracked_keyword = name
        args = attributes.get("args", [])

        if name == "Set LLM Model":
            if args:
                self._model = args[0]
            self._add_entry("config", f"model={args[0] if args else 'unknown'}")

        elif name == "Set LLM Endpoint":
            self._add_entry("config", f"endpoint={args[0] if args else 'unknown'}")

        elif name == "Set LLM Parameters":
            params = ", ".join(str(a) for a in args)
            self._add_entry("config", f"parameters={params}")

        elif name == "Ask LLM":
            prompt = args[0] if args else ""
            self._add_entry("input", prompt)

        elif name == "Grade Answer":
            question = args[0] if args else ""
            self._add_entry("grading", question)

        elif name == "Wait For LLM":
            self._add_entry("system", "waiting for LLM")

        elif name == "Get Running Models":
            self._add_entry("system", "querying running models")

        elif name == "LLM Is Busy":
            self._add_entry("system", "checking busy status")

    def end_keyword(self, name: str, attributes: Dict[str, Any]) -> None:
        if self._in_tracked_keyword == name:
            self._in_tracked_keyword = None

    # ------------------------------------------------------------------
    # Log message capture (for LLM responses)
    # ------------------------------------------------------------------

    def log_message(self, message: Dict[str, Any]) -> None:
        """Capture LLM responses logged by OllamaClient.generate().

        The client logs ``"{model} >> {text}"`` on successful generation.
        """
        if self._in_tracked_keyword not in ("Ask LLM", "Grade Answer"):
            return

        text = message.get("message", "")
        if " >> " in text:
            response = text.split(" >> ", 1)[1]
            self._add_entry("output", response)

    # ------------------------------------------------------------------
    # Loki payload building
    # ------------------------------------------------------------------

    def _build_push_payload(self) -> Dict[str, Any]:
        """Build a Loki push API payload from buffered entries.

        Groups entries by ``event_type`` into separate streams, each
        with labels for ``job``, ``suite``, ``model``, and ``event_type``.

        Returns:
            Dict matching the Loki ``/loki/api/v1/push`` JSON schema.
        """
        if not self._entries:
            return {"streams": []}

        # Group entries by event_type for separate label streams.
        grouped: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        for entry in self._entries:
            grouped[entry["event_type"]].append(entry)

        streams = []
        for event_type, entries in grouped.items():
            # Use the model from the first entry in the group.
            model = entries[0]["model"]
            values = [[e["timestamp"], e["message"]] for e in entries]
            streams.append(
                {
                    "stream": {
                        "job": "robotframework",
                        "suite": self._suite_name or "unknown",
                        "model": model,
                        "event_type": event_type,
                    },
                    "values": values,
                }
            )

        return {"streams": streams}

    # ------------------------------------------------------------------
    # HTTP push
    # ------------------------------------------------------------------

    def _flush_to_loki(self) -> None:
        """Push buffered entries to Loki and clear the buffer."""
        payload = self._build_push_payload()
        push_url = f"{self._loki_url}/loki/api/v1/push"

        try:
            resp = requests.post(
                push_url,
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=_HTTP_TIMEOUT_SECONDS,
            )
            if resp.status_code < 300:
                count = len(self._entries)
                summary = f"LokiListener: pushed {count} entries to {push_url}"
                logger.info(summary)
                logger.console(summary)
            else:
                logger.warn(
                    f"LokiListener: Loki returned HTTP {resp.status_code}: "
                    f"{resp.text[:200]}"
                )
        except requests.ConnectionError:
            logger.warn(
                f"LokiListener: could not connect to Loki at {push_url} "
                "(is Loki running?)"
            )
        except requests.Timeout:
            logger.warn(
                f"LokiListener: request to {push_url} timed out "
                f"after {_HTTP_TIMEOUT_SECONDS}s"
            )
        except Exception as e:
            logger.warn(f"LokiListener: failed to push logs: {e}")
        finally:
            self._entries = []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _add_entry(self, event_type: str, message: str) -> None:
        """Append a structured log entry."""
        # Loki expects nanosecond-precision timestamps as strings.
        timestamp_ns = str(int(time.time() * 1_000_000_000))
        self._entries.append(
            {
                "timestamp": timestamp_ns,
                "event_type": event_type,
                "message": message,
                "model": self._model,
            }
        )
