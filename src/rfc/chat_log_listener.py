"""Robot Framework listener that writes a plain-text chat.log of Ollama interactions.

Produces a simple, human-readable log with one line per event:
    TIMESTAMP<TAB>MODEL<TAB>TYPE<TAB>MESSAGE

Types:
    config  - Model/endpoint/parameter changes
    input   - Prompts sent to the LLM
    output  - LLM responses
    grading - Grade Answer invocations
    system  - Operational keywords (wait, busy check, etc.)

Usage:
    robot --listener rfc.chat_log_listener.ChatLogListener tests/
"""

import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from robot.api import logger  # type: ignore

# Keywords worth logging and their prompt types.
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


class ChatLogListener:
    """Listener that writes a plain-text ``chat.log`` of all Ollama interactions.

    Tracks the active model name and classifies each keyword call into a
    prompt type (input, output, config, grading, system).  LLM responses
    are captured via ``log_message`` by detecting the ``model >> text``
    pattern emitted by :class:`~rfc.ollama.OllamaClient.generate`.

    Usage:
        robot --listener rfc.chat_log_listener.ChatLogListener tests/
    """

    ROBOT_LISTENER_API_VERSION = 2

    def __init__(self) -> None:
        self._model: str = os.getenv("DEFAULT_MODEL", "unknown")
        self._entries: List[Tuple[str, str, str, str]] = []
        self._in_tracked_keyword: Optional[str] = None
        self._suite_depth: int = 0

    # ------------------------------------------------------------------
    # Suite tracking
    # ------------------------------------------------------------------

    def start_suite(self, name: str, attributes: Dict[str, Any]) -> None:
        self._suite_depth += 1

    def end_suite(self, name: str, attributes: Dict[str, Any]) -> None:
        self._suite_depth -= 1
        if self._suite_depth > 0:
            return
        if not self._entries:
            return
        self._save_chat_log(name)

    # ------------------------------------------------------------------
    # Keyword tracking
    # ------------------------------------------------------------------

    def start_keyword(self, name: str, attributes: Dict[str, Any]) -> None:
        prompt_type = _KEYWORD_TYPES.get(name)
        if prompt_type is None:
            return

        self._in_tracked_keyword = name
        args = attributes.get("args", [])

        if name == "Set LLM Model":
            if args:
                self._model = args[0]
            self._log("config", f"model={args[0] if args else 'unknown'}")

        elif name == "Set LLM Endpoint":
            self._log("config", f"endpoint={args[0] if args else 'unknown'}")

        elif name == "Set LLM Parameters":
            params = ", ".join(str(a) for a in args)
            self._log("config", f"parameters={params}")

        elif name == "Ask LLM":
            prompt = args[0] if args else ""
            self._log("input", prompt)

        elif name == "Grade Answer":
            question = args[0] if args else ""
            self._log("grading", question)

        elif name == "Wait For LLM":
            self._log("system", "waiting for LLM")

        elif name == "Get Running Models":
            self._log("system", "querying running models")

        elif name == "LLM Is Busy":
            self._log("system", "checking busy status")

    def end_keyword(self, name: str, attributes: Dict[str, Any]) -> None:
        if self._in_tracked_keyword == name:
            self._in_tracked_keyword = None

    # ------------------------------------------------------------------
    # Log message capture (for LLM responses)
    # ------------------------------------------------------------------

    def log_message(self, message: Dict[str, Any]) -> None:
        """Capture LLM responses logged by OllamaClient.generate().

        The client logs ``"{model} >> {text}"`` on successful generation.
        We detect that pattern to record the output.
        """
        if self._in_tracked_keyword not in ("Ask LLM", "Grade Answer"):
            return

        text = message.get("message", "")
        if " >> " in text:
            response = text.split(" >> ", 1)[1]
            self._log("output", response)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _log(self, prompt_type: str, message: str) -> None:
        """Append a log entry."""
        timestamp = datetime.utcnow().isoformat() + "Z"
        self._entries.append((timestamp, self._model, prompt_type, message))

    def _save_chat_log(self, suite_name: str) -> None:
        """Write collected entries to ``chat.log``."""
        output_dir = os.getenv("ROBOT_OUTPUT_DIR", ".")
        output_file = os.path.join(output_dir, "chat.log")

        try:
            with open(output_file, "w") as f:
                f.write("# chat.log - Ollama interaction log\n")
                f.write(f"# Suite: {suite_name}\n")
                f.write(f"# Generated: {datetime.utcnow().isoformat()}Z\n")
                f.write("# Format: TIMESTAMP\\tMODEL\\tTYPE\\tMESSAGE\n")
                f.write("#\n")
                for ts, model, ptype, msg in self._entries:
                    clean = msg.replace("\n", " ").replace("\r", "").strip()
                    f.write(f"{ts}\t{model}\t{ptype}\t{clean}\n")
            logger.info(
                f"Chat log saved to: {output_file} ({len(self._entries)} entries)"
            )
        except Exception as e:
            logger.warn(f"Could not save chat log: {e}")
