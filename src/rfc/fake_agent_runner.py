"""Fake (replay) agent runner for the agentic-coding suite.

In PR #1 every test in the agentic-coding suite consumes a prerecorded
:class:`AgentRun` loaded from a fixture directory. A live adapter that actually
shells out to ``claude -p`` is a follow-up; isolating that here lets the
harness and verifiers be reviewed before any real API cost is incurred.

A fixture directory layout::

    fixtures/
      <scenario_id>/
        run.yaml          # prerecorded AgentRun payload
        ...               # (optional) seed workspace tarball, transcripts, etc.
"""

from __future__ import annotations

from pathlib import Path

from rfc.agent_run import AgentRun, load_agent_run

DEFAULT_FIXTURES_ROOT = (
    Path(__file__).resolve().parent.parent.parent
    / "robot"
    / "agentic_coding"
    / "fixtures"
)


class FakeAgentRunner:
    """Load prerecorded :class:`AgentRun` artifacts by scenario id."""

    def __init__(
        self,
        *,
        fixtures_root: Path | None = None,
        agent_id: str | None = None,
    ) -> None:
        self.fixtures_root = fixtures_root or DEFAULT_FIXTURES_ROOT
        self.agent_id = agent_id

    def list_scenarios(self) -> list[str]:
        """Return every scenario id that has a ``run.yaml`` under the fixtures root.

        When the runner is filtered by ``agent_id``, only scenarios whose run
        matches that agent are included.
        """
        if not self.fixtures_root.exists():
            return []
        out: list[str] = []
        for child in sorted(self.fixtures_root.iterdir()):
            run_yaml = child / "run.yaml"
            if not (child.is_dir() and run_yaml.is_file()):
                continue
            if self.agent_id is not None:
                try:
                    run = load_agent_run(run_yaml)
                except ValueError:
                    continue
                if run.agent_id != self.agent_id:
                    continue
            out.append(child.name)
        return out

    def run(self, scenario_id: str) -> AgentRun:
        """Load and return the :class:`AgentRun` for ``scenario_id``."""
        scenario_dir = self.fixtures_root / scenario_id
        run_yaml = scenario_dir / "run.yaml"
        if not run_yaml.is_file():
            raise KeyError(
                f"Unknown scenario {scenario_id!r} under {self.fixtures_root}"
            )
        run = load_agent_run(run_yaml)
        if self.agent_id is not None and run.agent_id != self.agent_id:
            raise KeyError(
                f"Scenario {scenario_id!r} not available for agent {self.agent_id!r}"
            )
        return run


def run_scenario(scenario_id: str, *, fixtures_root: Path | None = None) -> AgentRun:
    """Shorthand: load one scenario's :class:`AgentRun`."""
    return FakeAgentRunner(fixtures_root=fixtures_root).run(scenario_id)
