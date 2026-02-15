"""Robot Framework listener that timestamps all Ollama chat interactions.

Records start/end times and duration for every Ollama-related keyword
call (Ask LLM, Set LLM Model, Wait For LLM, etc.) and saves a JSON
log at the end of the top-level suite.

Usage:
    robot --listener rfc.ollama_timestamp_listener.OllamaTimestampListener tests/
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from robot.api import logger  # type: ignore

# Keywords that represent Ollama interactions worth timestamping.
_TRACKED_KEYWORDS = frozenset(
    {
        "Ask LLM",
        "Set LLM Endpoint",
        "Set LLM Model",
        "Set LLM Parameters",
        "Wait For LLM",
        "Get Running Models",
        "LLM Is Busy",
    }
)


class OllamaTimestampListener:
    """Listener that timestamps all Ollama chat keyword calls.

    Hooks into ``start_keyword`` / ``end_keyword`` to record when each
    Ollama-related keyword begins and finishes.  At the end of the
    top-level suite the collected timestamps are saved to
    ``ollama_timestamps.json`` in the output directory.

    Usage:
        robot --listener rfc.ollama_timestamp_listener.OllamaTimestampListener tests/
    """

    ROBOT_LISTENER_API_VERSION = 2

    def __init__(self) -> None:
        self._chats: List[Dict[str, Any]] = []
        self._current_keyword: Optional[Dict[str, Any]] = None
        self._suite_depth: int = 0

    def start_suite(self, name: str, attributes: Dict[str, Any]) -> None:
        """Track suite nesting depth."""
        self._suite_depth += 1

    def start_keyword(self, name: str, attributes: Dict[str, Any]) -> None:
        """Record the start time when an Ollama keyword begins."""
        if name not in _TRACKED_KEYWORDS:
            return

        args = attributes.get("args", [])
        prompt = args[0] if args else ""

        self._current_keyword = {
            "keyword": name,
            "prompt": prompt,
            "start_time": datetime.utcnow().isoformat() + "Z",
        }

    def end_keyword(self, name: str, attributes: Dict[str, Any]) -> None:
        """Record the end time and compute duration for Ollama keywords."""
        if self._current_keyword is None:
            return
        if self._current_keyword["keyword"] != name:
            return

        end_time = datetime.utcnow()
        end_iso = end_time.isoformat() + "Z"

        start_dt = datetime.fromisoformat(
            self._current_keyword["start_time"].rstrip("Z")
        )
        duration = (end_time - start_dt).total_seconds()

        self._current_keyword["end_time"] = end_iso
        self._current_keyword["duration_seconds"] = round(duration, 3)

        self._chats.append(self._current_keyword)
        self._current_keyword = None

        logger.info(f"Ollama call '{name}' completed in {duration:.3f}s")

    def end_suite(self, name: str, attributes: Dict[str, Any]) -> None:
        """Save the timestamp log when the top-level suite ends."""
        self._suite_depth -= 1
        if self._suite_depth > 0:
            return

        if not self._chats:
            return

        self._save_timestamps_json(name)

    def _save_timestamps_json(self, suite_name: str) -> None:
        """Write collected timestamps to a JSON file.

        Args:
            suite_name: Name of the suite that just finished.
        """
        output_dir = os.getenv("ROBOT_OUTPUT_DIR", ".")
        output_file = os.path.join(output_dir, "ollama_timestamps.json")

        data = {
            "suite": suite_name,
            "total_chats": len(self._chats),
            "chats": self._chats,
        }

        try:
            with open(output_file, "w") as f:
                json.dump(data, f, indent=2)
            logger.info(
                f"Ollama timestamps saved to: {output_file} ({len(self._chats)} calls)"
            )
        except Exception as e:
            logger.warn(f"Could not save Ollama timestamps: {e}")
