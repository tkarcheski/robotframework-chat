"""Robot Framework test runner with auto-recovery support."""

import subprocess
import threading
import time
from pathlib import Path

from dashboard.core.session_manager import (
    RobotSession,
    SessionStatus,
    session_manager,
)


class RobotRunner(threading.Thread):
    """Runs Robot Framework tests in a separate thread with auto-recovery."""

    def __init__(
        self,
        session: RobotSession,
        output_dir: str = "results/dashboard",
    ):
        super().__init__(daemon=True)
        self.session = session
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session_dir = self.output_dir / session.session_id
        self.session_dir.mkdir(exist_ok=True)
        self._stop_event = threading.Event()
        self._recovery_delay = 5  # seconds

    def run(self) -> None:
        """Execute Robot with auto-recovery support."""
        while True:
            try:
                self._execute_robot()

                # Check if we should auto-recover
                if (
                    self.session.status == SessionStatus.FAILED
                    and self.session.config.auto_recover
                    and self.session.recovery_attempts
                    < self.session.max_recovery_attempts
                ):
                    self.session.recovery_attempts += 1
                    session_manager.update_session_status(
                        self.session.session_id, SessionStatus.RECOVERING
                    )
                    session_manager.add_output_line(
                        self.session.session_id,
                        f"\n🔄 Auto-recovery attempt {self.session.recovery_attempts}/"
                        f"{self.session.max_recovery_attempts} in {self._recovery_delay}s...\n",
                    )
                    time.sleep(self._recovery_delay)
                else:
                    break

            except Exception as e:
                session_manager.add_output_line(
                    self.session.session_id, f"\n❌ Fatal error: {e}\n"
                )
                session_manager.update_session_status(
                    self.session.session_id, SessionStatus.FAILED
                )
                break

            if self._stop_event.is_set():
                break

    def stop(self) -> None:
        """Signal the runner to stop."""
        self._stop_event.set()
        if self.session.process:
            try:
                self.session.process.terminate()
                self.session.process.wait(timeout=5)
            except Exception:
                if self.session.process:
                    self.session.process.kill()

    def _execute_robot(self) -> None:
        """Execute Robot Framework with the session configuration."""
        config = self.session.config

        # Build command
        cmd = ["uv", "run", "robot"]

        # Output directory
        cmd.extend(["-d", str(self.session_dir)])

        # Include IQ levels as tags
        if config.iq_levels:
            for iq in config.iq_levels:
                cmd.extend(["-i", f"IQ:{iq}"])

        # Dry run
        if config.dry_run:
            cmd.append("--dryrun")

        # Randomize
        if config.randomize:
            cmd.extend(["--randomize", "all"])

        # Log level
        if config.log_level != "INFO":
            cmd.extend(["-L", config.log_level])

        # Variables
        cmd.extend(["-v", f"MODEL:{config.model}"])
        cmd.extend(["-v", f"CONTAINER_PROFILE:{config.profile}"])

        # Timestamp outputs
        cmd.append("-T")

        # Test suite path
        cmd.append(config.suite)

        # Update status
        session_manager.update_session_status(
            self.session.session_id, SessionStatus.RUNNING
        )

        session_manager.add_output_line(
            self.session.session_id,
            f"🚀 Starting Robot Framework...\n{'=' * 60}\n",
        )
        session_manager.add_output_line(
            self.session.session_id, f"$ {' '.join(cmd)}\n\n"
        )

        # Execute process
        try:
            self.session.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )

            # Stream output
            if self.session.process.stdout:
                for line in self.session.process.stdout:
                    if self._stop_event.is_set():
                        break
                    session_manager.add_output_line(
                        self.session.session_id, line.rstrip()
                    )
                    self._parse_progress(line)

            # Wait for completion
            return_code = self.session.process.wait()

            if self._stop_event.is_set():
                session_manager.update_session_status(
                    self.session.session_id, SessionStatus.FAILED
                )
                session_manager.add_output_line(
                    self.session.session_id, "\n⏹️ Execution stopped by user\n"
                )
            elif return_code == 0:
                session_manager.update_session_status(
                    self.session.session_id, SessionStatus.COMPLETED
                )
                session_manager.add_output_line(
                    self.session.session_id, "\n✅ All tests passed!\n"
                )
            else:
                session_manager.update_session_status(
                    self.session.session_id, SessionStatus.FAILED
                )
                session_manager.add_output_line(
                    self.session.session_id,
                    f"\n❌ Tests failed (exit code: {return_code})\n",
                )

        except Exception:
            session_manager.update_session_status(
                self.session.session_id, SessionStatus.FAILED
            )
            raise

    def _parse_progress(self, line: str) -> None:
        """Parse Robot output to extract progress."""
        # Look for patterns like "Test Name | PASS" or "Test Name | FAIL"
        if "| PASS" in line or "| FAIL" in line:
            # Update progress counter
            current = self.session.progress.get("current", 0) + 1
            total = self.session.progress.get("total", current)
            session_manager.update_progress(
                self.session.session_id,
                current=current,
                total=total,
                current_test=line.split("|")[0].strip(),
            )


class RobotRunnerFactory:
    """Factory for creating and managing robot runners."""

    _runners: dict[str, RobotRunner] = {}
    _lock = threading.Lock()

    @classmethod
    def create_runner(
        cls,
        session: RobotSession,
    ) -> RobotRunner:
        """Create a new runner for a session."""
        with cls._lock:
            runner = RobotRunner(session)
            cls._runners[session.session_id] = runner
            return runner

    @classmethod
    def get_runner(cls, session_id: str) -> RobotRunner | None:
        """Get runner by session ID."""
        with cls._lock:
            return cls._runners.get(session_id)

    @classmethod
    def stop_runner(cls, session_id: str) -> bool:
        """Stop a runner."""
        with cls._lock:
            runner = cls._runners.get(session_id)
            if runner:
                runner.stop()
                cls._runners.pop(session_id, None)
                return True
            return False
