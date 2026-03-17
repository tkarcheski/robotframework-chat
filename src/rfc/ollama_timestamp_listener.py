"""Robot Framework listener that timestamps all Ollama chat interactions.

Records start/end times and duration for every Ollama-related keyword
call (Ask LLM, Set LLM Model, Wait For LLM, etc.) and saves both a JSON
log and a human-readable audit log at the end of the top-level suite.

Output files (written to ``ROBOT_OUTPUT_DIR``):
    ``ollama_timestamps.json`` — machine-readable JSON with full details.
    ``ollama_audit.log``       — tab-separated audit log for compliance.

Audit log format::

    TIMESTAMP<TAB>ENDPOINT<TAB>MODEL<TAB>KEYWORD<TAB>DURATION_S<TAB>PROMPT

Usage:
    robot --listener rfc.ollama_timestamp_listener.OllamaTimestampListener tests/
"""

import json
import os
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional

from robot.api import logger  # type: ignore
from robot.api.interfaces import ListenerV3  # type: ignore
from robot.result.model import Keyword as ResultKeyword  # type: ignore
from robot.result.model import TestSuite as ResultSuite  # type: ignore
from robot.running.model import Keyword as RunningKeyword  # type: ignore
from robot.running.model import TestSuite as RunningSuite  # type: ignore

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


class OllamaTimestampListener(ListenerV3):
    """Listener that timestamps all Ollama chat keyword calls.

    Hooks into ``start_keyword`` / ``end_keyword`` to record when each
    Ollama-related keyword begins and finishes.  At the end of the
    top-level suite the collected timestamps are saved to
    ``ollama_timestamps.json`` and ``ollama_audit.log`` in the output
    directory.

    The audit log is a human-readable, tab-separated file suitable for
    compliance review.  Each line records the LLM endpoint, model,
    keyword invoked, duration, and prompt — all with ISO 8601 timestamps.

    Usage:
        robot --listener rfc.ollama_timestamp_listener.OllamaTimestampListener tests/
    """

    ROBOT_LISTENER_API_VERSION = 3

    def __init__(self) -> None:
        self._chats: List[Dict[str, Any]] = []
        self._current_keyword: Optional[Dict[str, Any]] = None
        self._suite_depth: int = 0
        self._model: str = os.getenv("DEFAULT_MODEL", "unknown")
        self._endpoint: str = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")

    def start_suite(self, data: RunningSuite, result: ResultSuite) -> None:
        """Track suite nesting depth."""
        self._suite_depth += 1

    def start_keyword(self, data: RunningKeyword, result: ResultKeyword) -> None:
        """Record the start time when an Ollama keyword begins."""
        name = data.name
        if name not in _TRACKED_KEYWORDS:
            return

        args = list(data.args)
        prompt = args[0] if args else ""

        # Track model/endpoint changes from configuration keywords.
        if name == "Set LLM Model" and args:
            self._model = args[0]
        elif name == "Set LLM Endpoint" and args:
            self._endpoint = args[0]

        self._current_keyword = {
            "keyword": name,
            "prompt": prompt,
            "start_time": datetime.now(UTC).isoformat() + "Z",
            "model": self._model,
            "endpoint": self._endpoint,
        }

    def end_keyword(self, data: RunningKeyword, result: ResultKeyword) -> None:
        """Record the end time and compute duration for Ollama keywords."""
        if self._current_keyword is None:
            return
        if self._current_keyword["keyword"] != data.name:
            return

        end_time = datetime.now(UTC)
        end_iso = end_time.isoformat() + "Z"

        start_dt = datetime.fromisoformat(
            self._current_keyword["start_time"].rstrip("Z")
        )
        duration = (end_time - start_dt).total_seconds()

        self._current_keyword["end_time"] = end_iso
        self._current_keyword["duration_seconds"] = round(duration, 3)

        self._chats.append(self._current_keyword)
        self._current_keyword = None

        logger.info(f"Ollama call '{data.name}' completed in {duration:.3f}s")

    def end_suite(self, data: RunningSuite, result: ResultSuite) -> None:
        """Save the timestamp log when the top-level suite ends."""
        self._suite_depth -= 1
        if self._suite_depth > 0:
            return

        if not self._chats:
            return

        self._save_timestamps_json(data.name)
        self._save_audit_log(data.name)

    def _save_timestamps_json(self, suite_name: str) -> None:
        """Write collected timestamps to a JSON file."""
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

    def _save_audit_log(self, suite_name: str) -> None:
        """Write a human-readable, tab-separated audit log.

        Format per line::

            TIMESTAMP\\tENDPOINT\\tMODEL\\tKEYWORD\\tDURATION_S\\tPROMPT
        """
        output_dir = os.getenv("ROBOT_OUTPUT_DIR", ".")
        output_file = os.path.join(output_dir, "ollama_audit.log")

        try:
            with open(output_file, "w") as f:
                f.write("# ollama_audit.log - Auditable Ollama LLM interaction log\n")
                f.write(f"# Suite: {suite_name}\n")
                f.write(f"# Generated: {datetime.now(UTC).isoformat()}Z\n")
                f.write(
                    "# Format: TIMESTAMP\\tENDPOINT\\tMODEL\\tKEYWORD"
                    "\\tDURATION_S\\tPROMPT\n"
                )
                f.write("#\n")
                for chat in self._chats:
                    prompt = chat["prompt"].replace("\n", " ").replace("\r", "").strip()
                    duration = chat.get("duration_seconds", 0)
                    f.write(
                        f"{chat['start_time']}\t"
                        f"{chat['endpoint']}\t"
                        f"{chat['model']}\t"
                        f"{chat['keyword']}\t"
                        f"{duration}\t"
                        f"{prompt}\n"
                    )
            logger.info(
                f"Audit log saved to: {output_file} ({len(self._chats)} entries)"
            )
        except Exception as e:
            logger.warn(f"Could not save audit log: {e}")
