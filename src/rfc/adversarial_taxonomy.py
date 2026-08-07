"""Attack taxonomy for the adversarial test-development program.

The red-team loop enumerates and covers a three-dimensional attack space. Each
dimension is orthogonal to the others so a single scenario names exactly one
value of each:

* :class:`Surface`   -- WHICH product surface is under attack.
* :class:`Technique` -- HOW the attack is delivered.
* :class:`Objective` -- WHAT the threat actor is trying to achieve.

An :class:`AttackVector` is one ``(surface, technique, objective)`` coordinate.
The catalog (:mod:`rfc.adversarial_catalog`) declares the *intended* vectors;
the generator (:mod:`rfc.adversarial_generator`) measures coverage as which
intended vectors have at least one implemented scenario, and the loop proposes
work for the uncovered ones.

The ``Surface`` -> ``axis:*`` mapping ties this vocabulary back to the suite
axis tags enforced by ``scripts/check_test_axes.py``: a coding-harness scenario
holds the model constant and varies the harness (``axis:harness``), while every
other surface drives the model under test (``axis:model``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Surface(StrEnum):
    """The product surface a scenario attacks."""

    CODING_HARNESS = "coding_harness"
    """The coding-agent harness (claude-code / opencode / codex): git, tools,
    filesystem, CI. Graded deterministically over an ``AgentRun``."""

    MODEL_UNDER_TEST = "model_under_test"
    """The raw LLM answering a prompt: jailbreak / injection / extraction."""

    AGENTIC_TOOL_USE = "agentic_tool_use"
    """A model in a tool/retrieval loop: poisoned tool outputs, indirect
    injection through retrieved content, tool-call hijacking."""

    MULTI_AGENT = "multi_agent"
    """Emerging paradigms: multi-agent orchestration, sub-agent delegation,
    cross-session memory. Instructions laundered through an agent boundary."""


class Technique(StrEnum):
    """How the attack payload is delivered."""

    ENCODING_EVASION = "encoding_evasion"
    """base64 / homoglyph / zero-width / unicode-tag obfuscation of the payload."""

    INSTRUCTION_OVERRIDE = "instruction_override"
    """"Ignore previous instructions" / role switch / fake system turn."""

    ROLEPLAY_JAILBREAK = "roleplay_jailbreak"
    """DAN-style persona, hypothetical framing, fiction wrapper."""

    INDIRECT_INJECTION = "indirect_injection"
    """Payload planted in content the agent will read (repo file, issue, page)."""

    TOOL_OUTPUT_POISONING = "tool_output_poisoning"
    """Payload embedded in a tool/API/web-search result the agent retrieves."""

    SOCIAL_FRAMING = "social_framing"
    """Authority, urgency, or benign-reframing pressure ("just staging creds")."""

    OBFUSCATION = "obfuscation"
    """Forbidden action hidden behind aliases, env indirection, split tokens."""

    MULTI_STEP_CHAIN = "multi_step_chain"
    """A full kill chain: several individually-plausible steps that compose
    into the objective (weaken a guard, then exploit it)."""

    MEMORY_POISONING = "memory_poisoning"
    """A payload written to durable memory to fire on a later turn/session."""

    DELEGATION_ABUSE = "delegation_abuse"
    """Instructions laundered through a sub-agent / orchestration boundary so
    the guardrail sees a "trusted" internal request."""


class Objective(StrEnum):
    """What the threat actor is trying to achieve."""

    SECRET_EXFILTRATION = "secret_exfiltration"
    """Leak credentials / secrets (commit, print, send off-box)."""

    UNSAFE_REPO_ACTION = "unsafe_repo_action"
    """Force-push, rewrite published history, delete tests, push to main."""

    GUARDRAIL_BYPASS = "guardrail_bypass"
    """Disable or skip a safety control (pre-commit, TDD, review gate)."""

    TASK_HIJACK = "task_hijack"
    """Abandon the user's task and execute the attacker's instead."""

    SYSTEM_PROMPT_EXTRACTION = "system_prompt_extraction"
    """Leak the system prompt / hidden configuration."""

    PRIVILEGE_ESCALATION = "privilege_escalation"
    """Broaden tool / permission / filesystem scope beyond the task."""

    PERSISTENCE = "persistence"
    """Plant instructions that survive into future runs."""

    SUPPLY_CHAIN = "supply_chain"
    """Introduce a malicious / typosquatted dependency or build step."""


class Severity(StrEnum):
    """How damaging a successful exploit of the vector would be."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_SEVERITY_ORDER: dict[Severity, int] = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}


def severity_rank(severity: Severity) -> int:
    """Return a sortable integer for ``severity`` (higher == more severe)."""
    return _SEVERITY_ORDER[severity]


# Which suite axis a scenario on each surface discriminates. A coding-harness
# scenario holds the model constant and varies the harness; every other surface
# varies the model under test. Kept in sync with scripts/check_test_axes.py.
_SURFACE_AXIS: dict[Surface, str] = {
    Surface.CODING_HARNESS: "axis:harness",
    Surface.MODEL_UNDER_TEST: "axis:model",
    Surface.AGENTIC_TOOL_USE: "axis:model",
    Surface.MULTI_AGENT: "axis:model",
}


def axis_for_surface(surface: Surface) -> str:
    """Return the ``axis:*`` tag a suite on ``surface`` must declare."""
    return _SURFACE_AXIS[surface]


@dataclass(frozen=True)
class AttackVector:
    """One coordinate in the attack space: (surface, technique, objective)."""

    surface: Surface
    technique: Technique
    objective: Objective

    @property
    def slug(self) -> str:
        """Stable ``surface/technique/objective`` string for logs and reports."""
        return f"{self.surface.value}/{self.technique.value}/{self.objective.value}"

    @property
    def axis(self) -> str:
        """The ``axis:*`` tag a suite exercising this vector must declare."""
        return axis_for_surface(self.surface)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.slug
