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
from datetime import datetime, UTC
from typing import Any, ClassVar, Dict, List, Tuple

from robot.api import logger  # type: ignore
from robot.libraries.BuiltIn import BuiltIn  # type: ignore

from .base_listener import BaseListener


class ChatLogListener(BaseListener):
    """Listener that writes a plain-text ``chat.log`` of all Ollama interactions.

    Tracks the active model name and classifies each keyword call into a
    prompt type (input, output, config, grading, system).  LLM responses
    are captured via ``log_message`` by detecting the ``model >> text``
    pattern emitted by :class:`~rfc.ollama.OllamaClient.generate`.

    Usage:
        robot --listener rfc.chat_log_listener.ChatLogListener tests/
    """

    TRACKED_KEYWORDS: ClassVar[Dict[str, str]] = {
        "Ask LLM": "input",
        "Grade Answer": "grading",
        "Set LLM Endpoint": "config",
        "Set LLM Model": "config",
        "Set LLM Parameters": "config",
        "Wait For LLM": "system",
        "Get Running Models": "system",
        "LLM Is Busy": "system",
    }

    def __init__(self) -> None:
        super().__init__()
        self._model: str = os.getenv("DEFAULT_MODEL", "unknown")
        self._entries: List[Tuple[str, str, str, str]] = []

    # ------------------------------------------------------------------
    # BaseListener hooks
    # ------------------------------------------------------------------

    def on_suite_start(self, data: Any, result: Any) -> None:
        """Pick up ``--variable DEFAULT_MODEL:X`` once Robot context exists.

        ``__init__`` runs before Robot parses ``--variable``, so the env-var
        read there misses values set only via the CLI flag.
        """
        try:
            robot_model = BuiltIn().get_variable_value("${DEFAULT_MODEL}")
        except Exception:
            robot_model = None  # Not running inside Robot (e.g. unit tests)
        if robot_model:
            self._model = robot_model

    def on_suite_end(self, data: Any, result: Any) -> None:
        if not self._entries:
            return
        self._save_chat_log(data.name)

    def on_keyword_start(self, data: Any, result: Any, keyword_type: str) -> None:
        name = data.name
        args = list(data.args)

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

    def on_log_message(self, message: Any) -> None:
        """Capture LLM responses logged by OllamaClient.generate().

        The client logs ``"{model} >> {text}"`` on successful generation.
        We detect that pattern to record the output.
        """
        if self._in_tracked_keyword not in ("Ask LLM", "Grade Answer"):
            return

        text = message.message
        if " >> " in text:
            response = text.split(" >> ", 1)[1]
            self._log("output", response)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _log(self, prompt_type: str, message: str) -> None:
        """Append a log entry."""
        timestamp = datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z"
        self._entries.append((timestamp, self._model, prompt_type, message))

    def _save_chat_log(self, suite_name: str) -> None:
        """Write collected entries to ``chat.log``."""
        output_dir = os.getenv("ROBOT_OUTPUT_DIR", ".")
        output_file = os.path.join(output_dir, "chat.log")

        try:
            with open(output_file, "w") as f:
                f.write("# chat.log - Ollama interaction log\n")
                f.write(f"# Suite: {suite_name}\n")
                f.write(f"# Generated: {datetime.now(UTC).isoformat()}Z\n")
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
