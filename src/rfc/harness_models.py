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
    # RFC-007 section 6.2 spine grouping columns (nullable; "" -> NULL in DB).
    # Rows written before #217 keep NULL; the scoreboard groups runs on them.
    scenario_id: str = ""  # battery task this run solved
    battery_run_id: str = ""  # groups the legs of one battery invocation


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


# Reserved agentic_metrics.metric_key vocabulary (RFC-007 section 6.1).
#
# The harness comparison scoreboard (RFC-007 slice S5) pivots exactly these
# EAV keys, one agentic_metrics row per (session[, test_run]). A metric key
# outside this set is not a comparison signal and the scoreboard ignores it.
# These are *reserved names*, not a schema change: any per-run metric is still
# just a new metric_key string, but the keys below have a named consumer (the
# scoreboard) and a fixed meaning, so writers and the view must agree on the
# spelling. tokens_in / tokens_out / latency_ms / grader_score predate #217 and
# are named here so the whole reserved set lives in one place.
METRIC_TASK_SUCCESS = "task_success"  # 0/1: tests pass AND negative case not hit
METRIC_CHURN_RATIO = "churn_ratio"  # changed lines / reference-diff lines
METRIC_PROCESS_VIOLATIONS = "process_violations"  # count of agent_verifiers fails
METRIC_TOKENS_IN = "tokens_in"  # prompt tokens (pre-existing key)
METRIC_TOKENS_OUT = "tokens_out"  # completion tokens (pre-existing key)
METRIC_LATENCY_MS = "latency_ms"  # wall time per run (pre-existing key)
METRIC_GRADER_SCORE = "grader_score"  # llm_judge score (pre-existing key)

# Canonical order == scoreboard column order. An immutable, iterable manifest
# the scoreboard view (S5) and its drift-guard can enumerate without re-listing
# the strings.
RESERVED_METRIC_KEYS: tuple[str, ...] = (
    METRIC_TASK_SUCCESS,
    METRIC_CHURN_RATIO,
    METRIC_PROCESS_VIOLATIONS,
    METRIC_TOKENS_IN,
    METRIC_TOKENS_OUT,
    METRIC_LATENCY_MS,
    METRIC_GRADER_SCORE,
)


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


# Human-in-the-Loop interaction vocabulary (#384, MVP). Settled with
# @rpelevin on the issue: the kinds share one table/inbox, but only
# ``approval`` rows ever carry execution authority (see rfc.hitl_gate).
HITL_KINDS: tuple[str, ...] = ("goal", "clarification", "approval", "input")
HITL_STATUSES: tuple[str, ...] = ("pending", "approved", "denied", "expired")


@dataclass
class HitlInteraction:
    """One human-in-the-loop interaction (#384).

    ``target_action_id`` and ``args_digest`` are required only for
    approvals; on other kinds they are recorded as context and never
    grant authority (the gate keys on ``kind == 'approval'``).
    ``expires_at`` "" means the row never times out — but an approval
    without an expiry fails closed at the gate.
    """

    session_id: str
    kind: str  # 'goal' | 'clarification' | 'approval' | 'input'
    prompt: str
    created_at: str  # UTC ISO-8601
    response: str = ""
    target_action_id: str = ""  # approvals: the exact pending action bound
    args_digest: str = ""  # approvals: sha256 over canonical action args
    status: str = "pending"  # 'pending' | 'approved' | 'denied' | 'expired'
    resolved_at: str = ""
    expires_at: str = ""
    id: str = ""  # backend assigns uuid4().hex when blank
