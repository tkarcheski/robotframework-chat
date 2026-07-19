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
    # #277: which paired repeat within a (harness, scenario) battery leg this run
    # is, so S4 pairs on the STORED (scenario_id, repeat_idx) key instead of
    # fragile row order, and a skipped repeat is a visible index hole rather than a
    # silently shifted run. -1 sentinel -> NULL (an int-id convention, not the ""
    # string one) so non-battery writers keep NULL and repeat 0 persists as 0.
    repeat_idx: int = -1
    # RFC-008 A3 (#242) runtime-provenance columns (nullable; "" -> NULL in DB).
    # Every runtime-bound axis a result sits at, so its coordinate is
    # reconstructable (the CLAUDE.md provenance rule). Rows written before #242
    # keep NULL; existing writers that never set them are unchanged.
    # resolved model content digest (distinguishes a re-pulled tag):
    model_digest: str = ""
    # prompt-registry id of the prompt that ran (e.g. grader.default_judge):
    prompt_id: str = ""
    # sha256 of the *resolved* prompt text — what ACTUALLY ran, after any env
    # override (RFC_GRADER_PROMPT), NOT PromptRegistry.provenance(id)'s registered
    # coordinate (RFC-008 §5; design's bound A3 criterion from the PR #272 review).
    prompt_hash: str = ""
    # identity/version of the grader that produced grader_score:
    grader_version: str = ""
    # Sampling regime (temperature/top_p/seed/...) as a JSON blob. RFC-008 §10
    # settled on a blob for the MVP: one migration, reversible — promote a hot
    # param to its own column later if the scoreboard needs to GROUP BY it.
    params_json: str = ""
    # #350: the durable local-resolution verdict — "did this run actually resolve
    # to a declared-local provider?" — persisted at WRITE TIME from the presence of
    # the gate-minted VerifiedLocalModel token (ComparisonRow.verified_local). The
    # token IS the tier: 1 == token minted (fixed-local, Tier A), 0 == no token
    # (Tier B / native / unverified). The int-id sentinel convention (NOT the ""
    # text one): -1 -> NULL for legacy rows and every non-comparison writer, which
    # the harness_scoreboard view reads FAIL-CLOSED to Tier B. This carries the
    # write-time comparability invariant to read time so the view's tier matches the
    # gate's tier by construction, not by a tool_name name-coincidence (#273/#350).
    verified_local: int = -1
    # RFC-012 MS5 (#328): the backend that actually served this run's generate()
    # calls — a fleet host name/endpoint (e.g. "ollama@http://ai1:11434") or a
    # BYOK "provider/model" (e.g. "openai/gpt-4o"), taken from the open-tolkein
    # gateway's route trace. Fills the RFC-008 section 5 host gap: model_digest
    # records WHAT ran but not WHERE, so two fleet hosts on one digest are
    # otherwise indistinguishable. Nullable ("" -> NULL): rows written before the
    # gateway seam populates it keep NULL, and it NEVER carries key material
    # (RFC-012 section 5.2 — provider/model only, never an api_key). Q3 (RFC-012
    # section 9): a discrete column, not a params_json field or a new route_trace
    # table, so the scoreboard can GROUP BY the serving host without a JSON probe.
    served_by: str = ""


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

# Efficiency-scoreboard keys (RFC-010 section 5, slice S1 — #258). Written once
# per top-level suite/run by AgenticHarnessListener and pivoted into
# agentic_sessions_full so the efficiency loop reads a *measured* number. Both
# aggregate signals that already exist: the answer cache stamps per-answer
# cache_hit=True (see answer_cache.py), and Robot already measures suite wall
# time. They fold in here beside the RFC-007 set rather than in a separate
# vocabulary.
METRIC_CACHE_HIT_RATE = "cache_hit_rate"  # fraction of generate() calls cached
METRIC_SUITE_RUNTIME_MS = "suite_runtime_ms"  # wall time per suite/run (ms)

# Sandbox exec-broker key (RFC-007 S1 spine, #235). The host-side
# ContainerExecBroker routes a live agent's code-exec tool calls into the
# network-isolated container and records, per call, the broker-dispatch wall
# time minus the in-container command's own runtime. One EAV row per code-exec
# call; the scoreboard aggregates per (harness, scenario, run) via the same AVG
# path the other reserved keys use. Budget: p50 <= 120 ms, p95 <= 300 ms. This
# is a *reserved name*, not a schema change -- the agentic_metrics table is EAV,
# so it needs no migration.
METRIC_SANDBOX_EXEC_OVERHEAD_MS = "sandbox_exec_overhead_ms"

# open-tolkein route-efficiency keys (RFC-012 section 7.3, slice MS5 — #328).
# The standalone gateway (tkarcheski/open-tolkein) emits a per-request route
# trace; the seam records these numeric route metrics beside the RFC-010 S1
# efficiency pair, and the host/provider that actually served the call in the
# nullable agentic_harnesses.served_by provenance column (the RFC-008 section 5
# host gap: model_digest alone cannot tell two fleet hosts apart). They fold in
# here rather than in a separate vocabulary, same reserved-name discipline.
#   * route_taken           — the routing-chain tier that served the call
#     (RFC-012 section 3.2 order: 1 cache .. 6 openrouter). AVG'd == mean route
#     depth, an efficiency signal (a lower mean == more cache/local service).
#   * tokens_saved_by_route — tokens a cache/local hit kept off a billed BYOK
#     provider (the headline "LOTR-books" number). SUM'd per session like
#     tokens_in/tokens_out.
#   * route_local_fraction  — fraction of a run's calls a local/cache tier served
#     (0..1). AVG'd like cache_hit_rate.
METRIC_ROUTE_TAKEN = "route_taken"
METRIC_TOKENS_SAVED_BY_ROUTE = "tokens_saved_by_route"
METRIC_ROUTE_LOCAL_FRACTION = "route_local_fraction"

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
    METRIC_CACHE_HIT_RATE,
    METRIC_SUITE_RUNTIME_MS,
    METRIC_SANDBOX_EXEC_OVERHEAD_MS,
    METRIC_ROUTE_TAKEN,
    METRIC_TOKENS_SAVED_BY_ROUTE,
    METRIC_ROUTE_LOCAL_FRACTION,
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
