"""Session manager for handling multiple Robot test sessions."""

import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

from rfc.suite_config import (
    default_iq_levels,
    default_model,
    default_profile,
    test_suites,
)


def _first_suite_path() -> str:
    """Return the path of the first configured test suite."""
    suites = test_suites()
    if suites:
        return next(iter(suites.values()))["path"]
    return "robot/math/tests"


class SessionStatus(Enum):
    """Session status states."""

    IDLE = "idle"
    RUNNING = "running"
    FAILED = "failed"
    COMPLETED = "completed"
    RECOVERING = "recovering"


@dataclass
class SessionConfig:
    """Configuration for a test session.

    Defaults are loaded from ``config/test_suites.yaml``.
    """

    suite: str = field(default_factory=_first_suite_path)
    iq_levels: list = field(default_factory=default_iq_levels)
    model: str = field(default_factory=default_model)
    profile: str = field(default_factory=default_profile)
    auto_recover: bool = False
    dry_run: bool = False
    randomize: bool = False
    log_level: str = "INFO"


@dataclass
class RobotSession:
    """Represents a single Robot test session."""

    session_id: str
    config: SessionConfig
    status: SessionStatus = SessionStatus.IDLE
    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime | None = None
    output_buffer: deque = field(default_factory=lambda: deque(maxlen=1000))
    results: list = field(default_factory=list)
    current_test: str = ""
    progress: dict = field(default_factory=dict)
    recovery_attempts: int = 0
    max_recovery_attempts: int = 3
    process: Any = None  # subprocess.Popen

    @property
    def runtime(self) -> str:
        """Calculate runtime as formatted string."""
        end = self.end_time or datetime.now()
        duration = (end - self.start_time).total_seconds()
        minutes = int(duration // 60)
        seconds = int(duration % 60)
        return f"{minutes}m {seconds}s"

    @property
    def tab_color(self) -> str:
        """Get tab color based on status."""
        if (
            self.status == SessionStatus.RUNNING
            or self.status == SessionStatus.RECOVERING
        ):
            return "#6c757d"  # Gray for busy
        elif self.status == SessionStatus.FAILED:
            return "#dc3545"  # Red for failed
        elif self.status == SessionStatus.COMPLETED:
            return "#28a745"  # Green for complete
        else:
            return "#adb5bd"  # Light gray for idle

    @property
    def tab_label(self) -> str:
        """Generate tab label with runtime."""
        status_emoji = {
            SessionStatus.IDLE: "⚪",
            SessionStatus.RUNNING: "⏳",
            SessionStatus.FAILED: "❌",
            SessionStatus.COMPLETED: "✅",
            SessionStatus.RECOVERING: "🔄",
        }
        emoji = status_emoji.get(self.status, "⚪")
        runtime = self.runtime if self.status != SessionStatus.IDLE else "0m 0s"
        return f"{emoji} Session {self.session_id[-4:]} ({runtime})"


class SessionManager:
    """Manages multiple Robot test sessions (max 5)."""

    MAX_SESSIONS = 5

    def __init__(self):
        self._sessions: dict[str, RobotSession] = {}
        self._lock = threading.Lock()
        self._observers: list = []

    def create_session(self, config: SessionConfig | None = None) -> RobotSession:
        """Create a new session if under limit."""
        with self._lock:
            if len(self._sessions) >= self.MAX_SESSIONS:
                raise SessionLimitError(f"Maximum {self.MAX_SESSIONS} sessions allowed")

            session_id = str(uuid.uuid4())[:8]
            config = config or SessionConfig()
            session = RobotSession(session_id=session_id, config=config)
            self._sessions[session_id] = session
            return session

    def get_session(self, session_id: str) -> RobotSession | None:
        """Get session by ID."""
        with self._lock:
            return self._sessions.get(session_id)

    def list_sessions(self) -> list[RobotSession]:
        """List all sessions."""
        with self._lock:
            return list(self._sessions.values())

    def close_session(self, session_id: str) -> bool:
        """Close and cleanup a session."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session and session.process:
                try:
                    session.process.terminate()
                    session.process.wait(timeout=5)
                except Exception:
                    session.process.kill()
            return self._sessions.pop(session_id, None) is not None

    def update_session_status(self, session_id: str, status: SessionStatus) -> None:
        """Update session status."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.status = status
                if status in [SessionStatus.COMPLETED, SessionStatus.FAILED]:
                    session.end_time = datetime.now()
                self._notify_observers(session_id)

    def add_output_line(self, session_id: str, line: str) -> None:
        """Add line to session output buffer."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.output_buffer.append(line)

    def update_progress(
        self,
        session_id: str,
        current: int,
        total: int,
        current_test: str = "",
    ) -> None:
        """Update session progress."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.progress = {"current": current, "total": total}
                if current_test:
                    session.current_test = current_test

    def register_observer(self, callback: Callable[[str], None]) -> None:
        """Register status change observer."""
        self._observers.append(callback)

    def _notify_observers(self, session_id: str) -> None:
        """Notify all observers of status change."""
        for callback in self._observers:
            try:
                callback(session_id)
            except Exception:
                pass


class SessionLimitError(Exception):
    """Raised when session limit is exceeded."""

    pass


# Global session manager instance
session_manager = SessionManager()
