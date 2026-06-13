"""Dataclasses for the Agentic Stack Tracker.

Pure dataclasses with no DB imports, so downstream modules can use the
types without pulling in sqlite3 / SQLAlchemy. CLAUDE.md forbids
Optional fields on database dataclasses; concrete defaults (empty
string for text, -1 sentinel for int IDs) are used instead.
"""

from dataclasses import dataclass


@dataclass
class AgenticHarness:
    """One row per Claude-Code / Codex / OpenCode session.

    session_id is the spine joining all agentic_* tables and (via a
    nullable column) test_runs. It is also the PRIMARY KEY of
    agentic_harnesses.
    """

    session_id: str
    tool_name: str
    started_at: str  # UTC ISO-8601
    tool_version: str = ""
    model_id: str = ""
    rfc_version: str = ""
    branch: str = ""
    ended_at: str = ""
    outcome: str = ""  # "" while running; 'success' | 'partial' | 'failed' when ended
    replay_of_recording_id: str = (
        ""  # nullable; points at dialog_recordings.id (Phase 2)
    )


@dataclass
class AgenticPlugin:
    """Plugin snapshot at session start. UNIQUE(session_id, plugin_name)."""

    session_id: str
    plugin_name: str
    recorded_at: str
    semver: str = ""
    source: str = ""  # 'pyproject' | 'pip' | 'manual'
    id: str = ""  # backend assigns uuid4().hex when blank


@dataclass
class AgenticSkill:
    """Skill (Robot .resource) snapshot. UNIQUE(session_id, skill_path)."""

    session_id: str
    skill_path: str
    recorded_at: str
    git_sha: str = ""
    skill_name: str = ""
    id: str = ""


@dataclass
class AgenticMetric:
    """EAV metric. test_run_id and test_result_id are -1 when session-level."""

    session_id: str
    metric_key: str
    recorded_at: str
    metric_value: float = 0.0
    test_run_id: int = -1  # -1 sentinel matches TestRun.id convention
    test_result_id: int = -1
    id: str = ""


@dataclass
class AgenticDecision:
    """One LLM-influenced decision with full provenance (Phase 3, #358/#359).

    ``applied`` is 0 for observe-only suggestions (``generative:observe``,
    or flow suggestions that could not be applied); 1 when the generative
    listener actually changed execution (``generative:flow``). Heal
    decisions (``heal:suggest``, #361) are ALWAYS ``applied=0``: the fix
    runs as a side experiment whose outcome lands in ``agentic_metrics``
    as ``heal_passed``, and the original failure stays the official test
    outcome.
    """

    session_id: str
    hook_event: str  # 'start_suite' | 'end_test' | 'on_failure' | ...
    prompt_model: str
    prompt_text: str
    recorded_at: str
    test_name: str = ""
    response_text: str = ""
    proposed_action: str = (
        ""  # 'skip'|'retry'|'fork'|'none'|'mutate'|'heal'|'observe'|'budget_exhausted'
    )
    applied: int = 0  # 0 = suggestion only, 1 = applied to run
    tokens_used: int = -1  # -1 sentinel = unknown (NULL in DB)
    id: str = ""  # backend assigns uuid4().hex when blank


@dataclass
class DialogRecording:
    """One recorded agent dialog (Phase 2). session_id "" = unattached."""

    id: str
    source_type: str  # 'live' | 'imported'
    started_at: str
    session_id: str = ""  # nullable in DB: imported recordings may pre-date a session
    tool_name: str = ""
    tool_version: str = ""
    model_id: str = ""
    ended_at: str = ""
    metadata_json: str = ""


@dataclass
class DialogTurn:
    """One turn of a recording. UNIQUE(recording_id, turn_number)."""

    recording_id: str
    turn_number: int
    role: str  # 'user' | 'assistant' | 'tool'
    timestamp: str
    content: str = ""
    tool_calls_json: str = ""
    tool_results_json: str = ""
    prompt_tokens: int = -1  # -1 sentinel = unknown (NULL in DB)
    completion_tokens: int = -1
    latency_ms: float = -1.0
    id: str = ""
