# Changelog

All notable changes to **robotframework-chat** are documented here. The format
is inspired by [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the
project follows [Semantic Versioning](https://semver.org/).

Provenance notes:

- The last **tagged** release is `v1.4.3` (2026-03-22). Versions 1.5.0 through
  1.17.5 landed continuously on the `claude-code-staging` branch without
  release tags; dates below are when each minor line first appeared in
  `pyproject.toml`. Tagging resumes once the current stabilization board
  clears.
- Entries are thematic summaries per minor line, not exhaustive commit lists.
  Pre-monorepo history (v1.4.3 → 1.17.x) lives in this repository's git log;
  later work is developed in a private monorepo whose public surface is
  published here via a PR-mode mirror publisher (see the readme's
  Contributing section).

## [1.29.0] — Unreleased

### Added

- **Canary session-degradation suite (`axis:model`, tier:4) + engine.** A
  "canary" pins one standing instruction on a session — *include the token
  `<name>` in every reply* — then drives a long multi-turn conversation and
  records how many turns / response tokens / wall-clock the session survives
  before the model first drops the token (the degradation point; first-miss
  policy). The engine (`rfc.canary`) is responder-agnostic: the live LLM-session
  responder lives in `rfc.canary_keywords.SessionCanaryKeywords`, and the same
  engine is meant to back a future `axis:harness` leg (a coding-agent harness
  session as the responder) with no engine change. New Robot keywords: `Run
  Canary Session`, `Default Canary Prompts`, `Run Scripted Canary Session`,
  `Canary Response Hits`, `Session Should Not Degrade`, `Session Should Degrade
  At Turn`. Two suites: the deterministic `robot/10__tier1/canary` logic suite
  (`axis:none`, scripted responses, no model — always green in CI) and the live
  `robot/40__tier4/canary` measurement suite (opt-in via `CANARY_LIVE=1`,
  registered in `config/local_models.yaml` for the per-model sweep). Per-turn
  and summary metrics are emitted as `RFC_DATA` for the spine. Deterministic
  twins: `tests/test_canary.py`, `tests/test_canary_keywords.py`.

## [1.28.0] — Unreleased

### Added

- **Pinned gold-suite judge (`GOLD_JUDGE_MODEL`).** The gold suites built their
  `Grader` from the arm's own client, so a model under test graded its own
  answers. `create_judge_provider` pins one frozen judge (temperature 0, JSON
  mode) for every arm when `GOLD_JUDGE_MODEL` is set, refuses a judge equal to
  `DEFAULT_MODEL` (`SelfGradingConfigError`, skip-not-fail), and otherwise keeps
  the legacy per-arm client so non-gate suites are unaffected. Documented in
  `.env.example`.
- **`gold` / `platinum` / `stress` suite tags.** The ten evaluation suites are
  tagged `gold`; the deterministic temporal-reasoning suite is additionally
  `platinum` (the cheap screening set); latency-bound needle/batch tests are
  tagged `stress` so `--include gold --exclude stress` selects the quality
  signal only. This reinstates context_window and legal quality tests that were
  previously skipped wholesale.

### Fixed

- **Judge failure skips instead of failing.** A judge that emitted unparseable
  JSON raised `ValueError`, recording a test FAIL and blaming the model under
  test for a broken instrument. `Grader.grade` now retries once and then raises
  `GraderUnavailableError` (skip-not-fail); an empty *answer* still scores 0.

- **#200 — codex parser: a string / non-int `exit_code` no longer records a
  failed command green.** `parse_codex_events` coerced `exit_code` with
  `int(exit_code) if isinstance(exit_code, int) else 0`, so a failed codex
  command whose `exit_code` arrived as `"1"` was recorded `returncode == 0`
  (green) — the exact green-when-red direction `assert_no_commit_while_tests_red`
  exists to protect. Coercion is now centralized in `_codex_exit_code` across
  both the current `item.completed` / `command_execution` path and the legacy
  `exec_command_end` path: a real int (not bool) is honored, a numeric string is
  parsed, and any other shape (bool, non-numeric string, `null`/missing, float)
  biases toward failure (non-zero) — fail loud, never silently green.
  - **Live-conformed against codex-cli 0.144.5.** A real `codex exec --json`
    run of a failing command emitted the `item.completed` / `command_execution`
    shape with `exit_code` as an int (`3`, `status = "failed"`); the non-terminal
    `item.started` carried `exit_code = null`. This closes the parser's
    `PENDING LIVE CONFORMANCE` marker for the `exit_code` shape and inverts the
    former `test_string_exit_code_is_treated_as_zero_KNOWN_RISK` characterization.

## [1.27.1] — Unreleased

### Added

- **#261 (RFC-010 S3) — recorded-transcript replay as a first-class harness run
  mode.** `harness_matrix.robot` gains a REPLAY mode
  (`HARNESS_MATRIX_REPLAY=1`, or the S2 `RFC_RUN_MODE=replay` intent): the
  cross-harness conformance legs read a recorded transcript from the on-disk
  corpus (`robot/40__tier4/harness_matrix/recordings/`) instead of spawning a
  live agent, so the matrix runs in CI at ~0 tokens on every push with no
  harness CLI installed. A replayed leg stamps its provenance on the
  `agentic_harnesses` spine (`replay_of_recording_id`, via a new
  `rfc harness start --replay-of`), so a green conformance cell is never
  mistaken for a fresh live pass — the same discipline as `cache_hit=True`. New
  module `rfc.harness_replay`; new keywords `Replay Mode Requested`,
  `Recording Available`, `Get Session Provenance`. The comparison-battery legs
  stay live-only and skip cleanly under replay.
- **#394 — a live-enforcement leg must never silently skip forever.** Two
  real-proof live legs certify opencode's routed permission enforcement against
  the REAL CLI + local model on top of the deterministic fixture/resolver proofs:
  the host-leak A/B (`TestOpenCodeHostLeakABDirtyEnv`) and the #390 returncode
  live leg (`TestLiveOpenCodeReturncode390`). Each skips cleanly per run under
  model/compute contention — acceptable once, but a config regression could then
  leave a leg perpetually skipped with no live proof on record.
  - **`rfc.live_leg_ledger`** — a JSON skip-streak ledger (under `~/.rfc/`,
    override `RFC_LIVE_LEG_LEDGER`) that records each leg's per-run outcome
    (executed vs skipped) only from a box already found CAPABLE of running it, so
    a box that merely lacks opencode never pollutes the streak. Both legs are
    folded into one gate per the owner ruling — the requirement is visibility,
    not blocking: individual skips are tolerated; a consecutive-skip streak that
    reaches the threshold (default 10, override `RFC_LIVE_LEG_MAX_SKIP_STREAK`) is
    surfaced.
  - **`python -m rfc.live_leg_ledger check`** (`make live-leg-gate`) — exits
    non-zero when any leg has skipped for N consecutive runs, naming the leg and
    directing it back to an uncontended/serialized gate.
  - **`RFC_HOSTLEAK_AB_TIMEOUT`** — makes the host-leak A/B's wall-clock cap
    env-tunable (default 180s), so a serialized/uncontended gate can grant the
    larger budget needed to conclude the A/B non-skipped (mirrors the returncode
    leg's existing `RFC_LIVE_OPENCODE_TIMEOUT`). Verified: the A/B executes green
    (not skipped) at a 420s budget on an uncontended box.

## [1.27.0] — Unreleased

### Added

- **#350 — persist the tier / local-resolution verdict to the spine.** The
  harness comparison scoreboard's tier separation now derives from a durable
  column instead of a tool_name allowlist, closing the seam where a misconfigured
  remote `opencode`/`codex` run could be promoted to a green Tier-A cell by its
  NAME (the #273 lie). This is the capstone gate over the #347 scoreboard view
  and the #348 McNemar gate.
  - **`agentic_harnesses.verified_local`** (INTEGER, nullable) — the durable
    local-resolution verdict, written AT WRITE TIME from the presence of the
    gate-minted `VerifiedLocalModel` token (`ComparisonRow.verified_local`, the
    exact-type token predicate). 1 = fixed-local (Tier A), 0 = no token (Tier B),
    NULL = legacy / non-comparison writer. Added by an additive migration
    (`_SQLITE_MIGRATIONS` / `_PG_MIGRATIONS`) per the RFC-008 A3 precedent — no
    data rewrite; existing rows keep NULL.
  - **`harness_scoreboard` view** now derives `tier` FAIL-CLOSED from
    `verified_local` (`CASE WHEN h.verified_local = 1 THEN 'A' ELSE 'B' END`)
    instead of `tool_name IN ('opencode','codex')`, so the view's tier matches the
    write-time comparability invariant by construction. The false-comfort docstring
    claiming the tool_name allowlist "mirrors the write-time invariant" is
    corrected. The #220 significance-overlay JOIN gate is thereby cleared (both
    `pass_rate` and `p_value` now range over the same token-verified population);
    landing the JOIN itself remains #220's slice.
  - **The verdict is part of the cell grain** (test-design's PR #374 finding):
    the tier CASE sits in the view's GROUP BY, so the cell is
    `(tool_name, model_id, scenario_id, tier)`. A bare non-grouped
    `verified_local` was a `GroupingError` on PostgreSQL (the production
    backend) and an arbitrary-row pick on SQLite — silent order-dependent
    Tier-A promotion of mixed cells. Under the grain fix a cell mixing token
    rows with untokened/legacy-NULL rows (the canonical post-migration state)
    splits into a pure Tier-A sub-cell and a Tier-B sub-cell: an untokened row
    can never enter a Tier-A aggregate, and Tier-A `pass_rate` is computed over
    token-verified rows only. A live-PostgreSQL validity guard (scratch schema
    on the compose database, dropped after) pins the view against the real
    backend so SQLite's permissiveness can't hide an invalid body again.
  - **Bootstrap upgrade path for pre-existing lean tables** (Codex finding on
    mirror PR #660, fixed at source): on an existing database the bootstrap's
    `CREATE TABLE IF NOT EXISTS agentic_harnesses` is a no-op, so the
    view-referenced columns added since (`scenario_id` #347, `verified_local`
    #350) stayed missing and the `CREATE VIEW` crashed. The DDL now applies
    additive `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for both before any
    view references them — no-op on fresh tables, in-place upgrade on old ones,
    no data rewrite.
  - **Comparative scoreboard charts** default-filter `tier='A'` (the raw grid is
    exempt), so a head-to-head bar/heatmap defaults to the honestly-comparable
    fixed-local population.
  - **`bootstrap_dashboards._run_ddl`** now executes the comment-stripped
    statement it already computes as its emptiness guard, instead of re-sending
    the raw statement.

## [1.26.2] — Unreleased

### Fixed

- **#385 — `Run Agent Task` no longer passes vacuously on a broken harness.**
  `LiveClaudeCodeRunner.run` now scores a nonzero harness process exit as a
  FAILED run (raising `HarnessRunError`) instead of returning an empty-but-
  well-formed `AgentRun` that every `harness_matrix.robot` conformance assertion
  passed trivially. A harness that dies before emitting tool events (auth /
  model-startup failure) is now a real failure, not a silent green. The
  legitimate `returncode == 0`-with-events path is unchanged.
- **#386 — harness sidecar resolves correctly under a git worktree.**
  `HarnessKeywords.start_harness_session` now reads the session sidecar via
  `git -C <workspace> rev-parse --absolute-git-dir` (matching the writer in
  `rfc harness start`) instead of assuming `<workspace>/.git` is a directory, so
  a git WORKTREE workspace — where `.git` is a gitdir-pointer file — resolves to
  the real `<main>/.git/worktrees/<name>/` sidecar.
- **#399 — `Harness Run Should Conform` no longer passes a do-nothing harness.**
  Follow-up to #385: that fix caught the nonzero-exit vacuous pass at the RUNNER
  layer, but a residual vacuous pass remained one layer up — a harness that
  exits 0 having done nothing (zero commits, zero changed paths) still satisfied
  the matrix conformance keyword, whose agent-id / branch / transcript-equality /
  no-commit-while-red assertions are all trivially true of an empty run. A new
  `assert_run_did_positive_work` verifier (surfaced as the **`Run Should Do
  Positive Work`** keyword) now requires ≥1 commit OR ≥1 changed path, and
  `Harness Run Should Conform` asserts it. The rc=0-with-zero-events case stays
  deliberately un-failed at the runner layer (a clarifying-question reply
  legitimately emits zero commands and exits 0); the check is scope-limited to
  work-producing scenarios at the conformance layer.

## [1.26.1] — Unreleased

### Fixed

- **#383 SECURITY — opencode routed deny was precedence-bypassable (a live
  sandbox escape landed via #381/#382).** #381 wrote opencode's native-tool deny
  only to `dest_dir/opencode.routed.json` and exported it via the `OPENCODE_CONFIG`
  env var — which is opencode's **lowest explicit** config tier. Live-verified on
  opencode 1.2.9 (`opencode debug config`), precedence is
  `cwd opencode.json > ancestor opencode.json (walk-up) > OPENCODE_CONFIG env >
  global > defaults`, merged **key-wise**. So any `opencode.json` in the run cwd
  or an ancestor (the monorepo itself ships `core/opencode.json` and
  `modules/skills/.../opencode.json`) outranked the deny, flipped `permission.bash`
  back to `allow`, and re-enabled **native host exec** — silently reviving the #377
  Tier-A corruption *and* opening a host escape. `OpenCodeAdapter.apply_routed_config`
  now also writes the merged deny **as `<workspace>/opencode.json`** — opencode's
  HIGHEST tier (cwd project config) — so no seed or ancestor config can shadow it;
  it scrubs-then-writes over any seed-shipped `opencode.json`/`.jsonc` (deny always
  wins) and carries **every** denied tool key explicitly (a key omitted at cwd
  falls through to a permissive ancestor — proven by a control test). The
  `OPENCODE_CONFIG` env-tier write is kept as defence in depth. New real-resolver
  regression tests (`test_opencode_config_precedence.py`) plant adversarial
  `opencode.json` (bash=allow) in the workspace **and** ancestors, drive
  `opencode debug config`, and assert effective `permission.bash == deny` in every
  case — the test class that would have caught the escape — plus a permanent
  host-leak A/B in the adversarial-planted-config environment.

### Added

- **#381 (F5) — opencode per-tool-call exec routes LIVE into the sandbox
  container.** Un-darkens the Tier-A comparison leg #377 correctly fenced off.
  `OpenCodeAdapter` now materializes a run-scoped merged config (base
  `opencode.json` + an exec overlay) that (a) registers the `rfc-exec` MCP server
  bound to the run's pre-warmed container and (b) DENIES opencode's native code
  tools via its own `permission` (fail-closed gate) + `tools` (registry-disable)
  config keys — so opencode's per-tool-call bash/write/edit dispatch through the
  broker into the container `/workspace`, not the host. Route-don't-copy holds:
  no `_sync_workspace`, the container tree is the single tree. `opencode` joins
  `_CONTAINER_ROUTED_HARNESSES` (claude-code + opencode) now that its live
  conformance passes; `codex` stays out (CLI absent, probe-gated). The Tier-A
  `ComparisonRow` now carries the broker's `sandbox_exec_overhead_ms` alongside
  the gate-minted `VerifiedLocalModel` token, so the cost tier is populated, not
  just task-success. Verified against the real opencode 1.2.9 CLI with a local
  Ollama model: the agent's real edits land in the container (churn manifest sees
  them), and — the F4 finding — opencode's `tools`-disable alone can be bypassed
  under adversarial prompting while the `permission: deny` layer holds, so the
  two-layer config denial IS opencode's PreToolUse-equivalent backstop (opencode
  has no PreToolUse hook; that is claude-code-specific).

### Fixed

- **#384 — tier-renumbering left dialog E2E + agentic fake-runner fixture path
  constants stale.** The migration (`robot/dialog/…` → `robot/10__tier1/dialog/…`,
  `robot/agentic_coding/…` → `robot/40__tier4/agentic_coding/…`) moved the fixture
  trees but left two runtime constants pointing at the deleted pre-migration
  locations. `dialog_e2e_keywords.FIXTURE_SUITE` spawned the child robot on a
  nonexistent suite (dialog E2E child run exited nonzero); and
  `fake_agent_runner.DEFAULT_FIXTURES_ROOT` resolved every prerecorded scenario
  under a deleted directory (agentic-coding scenarios failed as unknown). Both
  constants now point at the tier-numbered locations, verified present. Added
  regression guards that assert each constant resolves to a real path *and* that
  the dependent fixture actually loads — the dialog fixture suite parses to its
  expected test, and a default `FakeAgentRunner` lists (not merely `exists()`)
  its real scenarios — so a future move turns red immediately instead of at
  child-run time. A bare existence check is deliberately avoided: a stale
  `__pycache__`-only directory can linger at the old path and would satisfy it
  while yielding zero scenarios.

- **#377 — non-routed live harnesses no longer silently corrupt Tier-A
  comparison data.** The #235 rewrite deleted the host→container copy-back
  (`_sync_workspace`) on the premise that every live harness routes its
  code-exec into the container. Only `claude-code` does; `opencode`/`codex`
  stay host-native (the F5 / PENDING LIVE CONFORMANCE gap), so their edits
  landed in a throwaway host workspace while the churn manifest + tests ran
  against the *pristine* container — a red-seed fix the agent actually made
  read as "not fixed" (task-success 0, churn 0). Because `opencode` is the only
  Tier-A leg in `harness_comparison`, that silently poisoned the sacred
  comparison spine. `_run_live_scenario` now **fails closed** for any harness
  not in `_CONTAINER_ROUTED_HARNESSES`, raising
  `rfc.exceptions.LiveHarnessNotRoutedError` (a clean skip) before any container
  work; `HarnessComparison.run` records the leg as skipped rather than a wrong
  row. Reviving the Tier-A leg — a scoped copy-back bridge vs. F5 routing — is a
  design-owned follow-up (#378).

## [1.26.0]

### Added

- **#235 — per-tool-call code execution routed into the isolated container.** A
  live agent's code-exec tool calls (bash/write/edit) now run inside the
  pre-warmed, network-isolated sandbox container instead of on the host, through
  one host-side seam:
  - **`rfc.container_exec_broker.ContainerExecBroker`** — owns a `docker exec`
    channel into one container and speaks the harness-agnostic
    `SandboxToolCall -> SandboxToolResult` contract. `write`/`edit` materialize
    whole-file content via base64; large payloads stream to an out-of-tree temp
    file in bounded chunks so they never hit the inline-argv `MAX_ARG_STRLEN`
    ceiling. `write`/`edit` paths are confined to `/workspace` (host-side `..`
    rejection + an in-container `realpath` guard against symlink-parent escapes).
  - **`sandbox_exec_overhead_ms`** — a reserved RFC-007 S1 metric key (EAV, no
    migration). Each code-exec call is self-timed inside the container shell, so
    the recorded overhead is `broker_wall - command_own_runtime` = docker-exec
    transport + marshalling (the cost this path ADDS over a host exec). A budget
    gate (`check_overhead_budget`, p50 ≤ 120 ms / p95 ≤ 300 ms) can therefore see
    a create-per-call / transport regression. Measured live: p50 ≈ 64 ms.
  - **`rfc.exec_mcp`** — the `rfc-exec` MCP stdio server exposing `bash`/`write`/
    `edit`, backed by the broker. The claude-code adapter denies the native
    `Bash`/`Write`/`Edit`/`Read` tools via `--settings` and registers the server
    via `--mcp-config`; `parse_transcript` keys the routed `mcp__rfc-exec__bash`
    alongside native `Bash`. The opencode MCP overlay ships but is marked PENDING
    LIVE CONFORMANCE (CLI not installed to verify).
  - **`AgentSandbox._run_live_scenario`** rewritten to the coherence ruling: the
    container's `/workspace` is the single working tree, seeded at t0, mutated in
    place by the agent's broker'd tools, then manifested for churn + tested in
    place. `_sync_workspace` (host-side copy-back) is deleted.

## [1.25.0]

### Added

- **Pre-S4/S5 comparison hardening** (#277, #278): two design follow-ups from the
  merged #270 sign-off, tightening the harness-comparison spine before S4 (#220)
  and a second comparison runner land.
  - **#277 — `repeat_idx` persisted to the spine.** The paired-repeat index used
    to live only on the in-memory `ComparisonRow`; `agentic_harnesses` now carries
    a nullable `repeat_idx` (INTEGER) column, added through the established
    post-#217/#242 per-statement idempotent migrations on both backends and
    written by the comparison runner. So S4 pairs on the STORED
    `(scenario_id, repeat_idx)` key instead of fragile row order, and a skipped
    repeat is a visible index hole rather than a silently shifted run. The column
    uses the int-id sentinel convention (`-1 → NULL`), so a genuine repeat `0`
    persists as `0`. Sequenced at positional index 17, after #242's provenance set
    (12–16), so the two never collide.
  - **#278 — model-resolution gate pushed to the config/adapter layer + a
    stronger Tier-A type invariant.** The load-bearing "selected model resolves to
    a declared-local provider" check moved out of `rfc.harness_comparison` into a
    new leaf `rfc.opencode_config` module (the config loader), and
    `OpenCodeAdapter` — the layer that materializes `OPENCODE_CONFIG` for a run —
    grows `verify_local_model()` plus an opt-in `require_local_comparability` that
    gates `env_overrides()`, so any consumer of that config gets the check for
    free rather than only when a runner remembers to call it. The gate now mints a
    `VerifiedLocalModel` capability token, and a Tier-A `ComparisonRow` REQUIRES
    one — so a future runner constructing
    `ComparisonRow(tier="A", model_id="openai/gpt-4o")` directly is rejected:
    accidental omission of the gate fails closed, and type-checked code cannot
    skip it. Deliberate in-process forgery remains partially possible (as with
    any Python capability token) and is defended by review + dual sign-off; the
    #314 hardening below narrows it to two conspicuous paths. This matches the
    docstring's "gate-verified local model" contract instead of merely checking
    non-empty. `assert_opencode_comparable` still returns the model-id string
    and is re-exported from `rfc.harness_comparison`, so existing callers are
    unchanged. The #273 bypass regression suite still fails closed.
- **#326 — the open-tolkein seam fails closed under `local_only` (RFC-012 §3.4,
  MS3).** The MS1 consumption seam (#324) ships a down-gateway fallback: when
  `OPEN_TOLKEIN_BASE_URL` is set but the gateway is unreachable,
  `select_backend` skip-and-logs back to the direct provider path. That fallback
  is the one seam line that can egress a `local_only` prompt — a down gateway
  plus a remote direct provider plus a cache miss would build a remote client
  and leave the fleet boundary (the #273 lesson). `select_backend` now raises the
  new typed `LocalOnlyEgressError` on exactly that path: a `local_only` request
  whose down-gateway fallback provider is not localhost-class (`ollama`/`vllm`
  are; `openai` and unknowns are not) is refused rather than downgraded to a
  remote BYOK path. Deliberately a hard failure, not an `RFCSkipError` — a
  locality-safety breach must fail loudly, not skip. A reachable gateway (it owns
  the routing), the inert seam (no gateway boundary, RFC-012 §3.3), and every
  non-`local_only` request are unchanged. Paired with the gateway-side
  URL-derived locality guard in `tkarcheski/open-tolkein` (#2), the up-path half
  of the same invariant.

### Changed

- **#314 — Tier-A token forgery hardening (design-capped defense-in-depth).**
  Of the four deliberate in-process forge paths test-design demonstrated during
  the #313 sign-off, two are now closed:
  - the **mint key is closure-bound**, not an importable module global — the
    one-line, mypy-clean `rfc.opencode_config._GATE_MINT_KEY` grab is gone, and
    no module attribute can mint a token (the only callable holding the key is
    the gate itself, which verifies before it mints);
  - the Tier-A `ComparisonRow` check is **`type()`-exact** — a duck-typed fake
    (`SimpleNamespace(model_id=...)`) or a `VerifiedLocalModel` subclass that
    overrides `__post_init__` is rejected at runtime, mypy-independent.

  Two paths remain, per the #314 design ruling deliberately out of scope
  (inherent to Python capability tokens; an in-process absolute is impossible,
  so review + dual sign-off is the defense and each is a glaring one-liner in a
  diff): `object.__new__` + `object.__setattr__` fabrication of a real-typed
  token, and extracting the mint key by introspecting the gate's closure cells.
  Both closed paths are locked by fail-closed forge tests; the two remaining
  paths are documented by tests that pin the exact boundary of the guarantee.

## [1.24.0] — Unreleased

### Added

- **RFC-008 A3 — runtime-provenance columns on the harness spine** (#242): every
  runtime-bound axis of a result is now recorded on `agentic_harnesses`, so its
  coordinate is reconstructable (the CLAUDE.md provenance rule). Five nullable
  columns — `model_digest`, `prompt_id`, `prompt_hash`, `grader_version`, and a
  `params_json` sampling blob (the reversible choice RFC-008 §10 settled on for
  the MVP) — are added through the established post-#217 per-statement idempotent
  migrations on both the sqlite3 and SQLAlchemy backends; pre-existing rows keep
  `NULL`, existing writers are unchanged, and a half-migrated DB backfills only
  the missing columns. The dialog-replay writer — the one `agentic_harnesses`
  writer that runs the LLM judge — records the **resolved** grader prompt hash
  (after any `RFC_GRADER_PROMPT` override) rather than
  `PromptRegistry.provenance(id)`'s registered coordinate, so both arms of a
  prompt A/B log the text that actually ran (design's bound criterion from the
  PR #272 review); it also records the target model's digest and sampling
  regime. The comparison runner records `model_digest` via an injectable
  resolver. New `rfc.grader.resolved_grader_provenance()` seam and
  `GRADER_VERSION`; the over-promising "the live hash (what actually ran)"
  docstrings on `PromptRegistry.resolve()`/`provenance()` are corrected to
  describe the *registered* coordinate and point to the resolved-hash spine seam.
## [1.23.2] — Unreleased

### Added

- **Efficiency scoreboard — `cache_hit_rate` + `suite_runtime_ms`** (RFC-010
  slice S1, #258): two reserved `agentic_metrics` keys, written once per
  top-level suite/run by `AgenticHarnessListener` (cache-hit fraction from each
  `llm_metrics` payload's `cache_hit` flag; suite wall time from Robot's
  `result.elapsedtime`) and pivoted into the `agentic_sessions_full` scoreboard
  view. A new `rfc harness scoreboard` command reads a session's rollup. No
  schema change (EAV rows only); the Superset dashboard stays out of scope
  (#221/S5). This makes every later efficiency lever's win a *measured* one.

## [1.23.1] — Unreleased

### Fixed

- **One owned churn-manifest policy** (#248, #231, #274, #280): the tier:4
  sandbox grader (`rfc.agent_sandbox`) and the host-side battery-scenario guard
  (`check_battery_scenarios.py`) each carried their own churn-manifest
  implementation, and the two disagreed — so the guard could bless a solution the
  grader would reject (#231) and the grader was blind to an out-of-allowlist
  symlink the guard would have seen (`find -type f` omits symlinks, #248). Both
  now consume a single owned policy in the new stdlib-only `rfc.churn_manifest`
  module. Symlinks are **included**, keyed by `symlink:<sha256 of the link
  target>` — the target is hashed, never embedded raw, so an attacker-chosen
  target (newline, double-space) cannot inject a manifest delimiter (#274); the
  records are NUL-delimited with raw paths for the same reason. Exclusion keys on
  an **ancestor directory**, not a name-anywhere: the *contents* of a `.git` /
  `__pycache__` directory are pruned on both sides (VCS metadata / byproduct
  bytecode, not agent artifacts), but a *leaf* (file or symlink) named `.git` /
  `__pycache__`, and any `.pyc` **outside** a `__pycache__/` directory, is
  authored content and **counts** as churn (#280). A shell-vs-walk parity test
  pins the two renderings byte-identical — including on the excluded-name-leaf and
  hostile-name trees (#231, #274, #280) that previously drifted silently.

## [1.23.0] — Unreleased

### Added

- **Live harness adapters wired into `agent_sandbox` scenarios** (#174): a
  tier:4 sandbox scenario can now be solved by a *live* coding-agent CLI instead
  of only the scripted `agents/*.sh` stand-ins. `AgentSandbox.run_scenario` and
  the `Run Sandboxed Coding Scenario` keyword take `harness=<name>` (a
  `rfc.harness_cli.TOOLS` taxonomy name, e.g. `opencode`) plus an optional
  `harness_model=` override; the named `rfc.harness_adapters.HarnessAdapter`
  builds the agent command. Per the owner's ratified egress model (decision 2)
  the harness runs ON THE HOST against the seeded scenario repo, while the
  network-isolated container still verifies the churn diff (`allowed_paths`) and
  the scenario `test_command` exactly as before. An absent harness CLI skips the
  run cleanly (new `rfc.exceptions.HarnessNotAvailableError`); a live agent that
  overruns the wall-clock cap degrades to exit 124 with a still-verified result.
  The scripted stand-ins remain the deterministic CI default. The `agent_sandbox`
  and HITL approval gate contracts are unchanged and fire identically for both
  paths.

- **Explicit `timed_out` flag on `SandboxResult`** (#251): the sandbox no
  longer forces consumers to infer a wall-clock kill from `agent_exit_code
  == 124`. `SandboxResult` gains `timed_out` and `tests_timed_out` bools, set
  at the single point of truth in `agent_sandbox` — the live path's
  `except TimeoutExpired` branch (a happy-path CLI 124 is deliberately NOT
  flagged, resolving the conflation) and the scripted path's container
  `timeout -k` 124 detection, with the verification command's 124 reported
  separately as `tests_timed_out`. Additive and backward compatible (both
  default `False`; existing `== 124` readers keep working). Precursor to #218
  per design's PR #230 sign-off ruling.

- **Harness comparison mode over the tier:4 sandbox battery** (#218, RFC-007
  S2): new `rfc.harness_comparison` runs the discriminating sandbox battery
  under each *available* harness, N paired repeats each (default N=5), and
  RECORDS per-run reserved metrics to the spine — one `agentic_harnesses` row
  per (scenario × harness × repeat) carrying `scenario_id` + a shared
  `battery_run_id`, plus `agentic_metrics` rows for `task_success`,
  `churn_ratio`, `process_violations`, and `latency_ms` — instead of asserting
  cross-harness equality. The Tier-A comparability contract (RFC-007 §5) is
  hard-blocked on #191: `opencode` is pinned to the repo `opencode.json` local
  Ollama model (self-contained, no egress — a `ComparabilityError` fails
  loudly otherwise). `claude-code` cannot pin a local model, so it is recorded
  as its own Tier-B cost tier (native model, never cross-compared); `codex`
  skips when absent. The runner is shaped for N harnesses (a second
  fixed-local leg pairs automatically by `(scenario_id, repeat_idx)`); the
  McNemar significance gate is S4/#220. Exposed as a
  `python -m rfc.harness_comparison` entry point and a gated live-smoke case
  in `harness_matrix.robot` (`HarnessComparisonKeywords`); the conformance
  suite is unchanged. Honest-comparison note: with only `opencode` able to pin
  a fixed local model today, the sanctioned cross-harness head-to-head is not
  available yet — it unlocks when a second Tier-A harness arrives.

## [1.22.0] — Unreleased

### Added

- **Harness spine grouping columns + reserved metric keys** (#217, RFC-007
  S1): `agentic_harnesses` gains two nullable columns — `scenario_id` (the
  battery task a run solved) and `battery_run_id` (groups the legs of one
  battery invocation) — so the comparison scoreboard can
  `GROUP BY (tool_name, model_id, scenario_id)` and pair repeats by a shared
  battery run. Added to the SQLite schema and the SQLAlchemy `Table` for
  fresh DBs, and as idempotent `ADD COLUMN` backfills in `_SQLITE_MIGRATIONS`
  / `_PG_MIGRATIONS` for pre-existing DBs; old rows keep `NULL` and existing
  writers are unchanged. `AgenticHarness` gains matching `scenario_id` /
  `battery_run_id` fields (concrete `""` defaults, not `Optional`). New
  `RESERVED_METRIC_KEYS` tuple + `METRIC_*` constants name the scoreboard's
  reserved `agentic_metrics.metric_key` vocabulary (`task_success`,
  `churn_ratio`, `process_violations`, plus the pre-existing `tokens_in` /
  `tokens_out` / `latency_ms` / `grader_score`). No new table (RFC-007
  section 6.2 rejects a `harness_benchmark` table). Write path deferred to
  #218.

### Changed

- **IFEval constraint checkers hidden from the Robot keyword surface**
  (#205): the 11 pure-function `check_*` helpers in `IFEvalKeywords`
  (`Check Sentence Count`, `Check All Caps`, `Check Bullet Points`,
  `Check Word Count`, `Check Numbered List`, `Check Paragraph Count`,
  `Check Forbidden Letter`, `Check Sentence Start`, `Check Ends With Word`,
  `Check All Lowercase`, `Check No Digits`) were auto-exposed as Robot
  keywords by omission. They are internal building blocks dispatched only by
  `Check IFEval Constraint`, so each is now marked `@not_keyword` and no
  longer surfaces. No suite invoked them directly, so this is a
  surface-hygiene trim, not a breaking change; the public entry points
  `Check IFEval Constraint` and `Check IFEval Instruction` are unchanged.

## [1.21.0] — Unreleased

### Added

- **HarnessKeywords RF library + cross-harness conformance matrix** (#173):
  `rfc.harness_keywords.HarnessKeywords` is the public keyword surface that runs
  one coding-agent task inside an `rfc harness` session bracket and normalizes
  the CLI transcript into an `AgentRun`, so every run lands in the
  `agentic_harnesses` DB spine and every `rfc.agent_verifiers` assertion applies
  to it identically. New keywords: `Create Harness Workspace`,
  `Harness Is Available`, `Start Harness Session`, `Run Agent Task`,
  `Get Agent Transcript`, `End Harness Session`. Built on the #172 / #186
  `HarnessAdapter` seam (claude-code / opencode / codex), with only the agent
  invocation injectable so it is unit-testable without spending tokens. New
  `robot/40__tier4/harness_matrix/harness_matrix.robot` runs the same fixture
  task under each *available* harness and asserts identical contract outcomes;
  it is LIVE and probe-gated (`HARNESS_MATRIX_LIVE=1`; the claude-code leg
  additionally needs `HARNESS_MATRIX_CLAUDE=1`; codex skips cleanly until
  installed). The deterministic twin (all three harnesses, no models, no tokens)
  is `tests/test_harness_keywords.py`. Feeds public-repo issue rfc#596.

## [1.20.1] — Unreleased

### Fixed

- **Docker execution suites: str-valued `volumes` dict zeroed all container
  setup** (#189): `robot/resources/environments.resource` built its `volumes`
  as `{host: "/workspace:rw"}` (a *str* value). docker-py's `containers.run`
  calls `value.get("bind")` on each value, so the str raised
  `AttributeError: 'str' object has no attribute 'get'`, no container was
  created, and **every** test in every execution suite (`docker/python`, `c`,
  `rust`, `bash`) failed deterministically at Suite Setup — silently zeroing
  execution-eval signal for #176/#167/#162. The resource now builds the
  docker-py dict form `{host: {"bind": "/workspace", "mode": "rw"}}`, and a new
  `rfc.docker_config.normalize_volumes` seam defensively normalizes the str
  shape (and passes valid dict/list forms through) so any suite still emitting
  the old shape is repaired before it reaches docker-py. `Setup Container
  Environment` also asserts a non-empty container id so a zero-container start
  fails loudly. Regression tests pin the accepted shapes.

## [1.20.0] — Unreleased

### Added

- **Computer-use substrate v0** (#175): browser actions exposed as
  dispatchable agent tools. New `rfc.computer_use_keywords` wraps New Page /
  Click / Type Text / page-to-markdown / screenshot as `ToolSchema` entries
  with a Robot-independent `ComputerUseDispatcher`; new Robot keywords
  `Get Computer Use Tools`, `Get Computer Use Tools JSON`,
  `Get Computer Use Tool Names`, `Dispatch Computer Use Call`, and
  `Assert Tool Call Succeeded`. New `rfc.computer_use_mcp` exposes the same
  tools over an MCP (JSON-RPC 2.0) stdio server with zero extra
  dependencies. New hermetic `robot/20__tier2/computer_use` suite drives an
  open-page -> read-markdown -> click -> assert sequence entirely through
  `ToolSchema` dispatch against a local `file://` fixture, archiving a
  screenshot per step. `rfc.agent_tool` gains an additive `new_tool_call`
  factory (no signature changes to `ToolSchema`/`ToolCall`/`ToolResult`).

## [1.19.0] — Unreleased

### Added

- **RSI-model priority test lane** (#648): `rfc.rsi_priority` update-detection
  module (`extract_digest` / `needs_retest` over Ollama `/api/tags` digests)
  and `scripts/rsi_priority_watcher.py`, which polls the RSI tag and runs a
  curated fast suite set immediately when the model is re-published, reusing
  the run-local-models command builder so results archive through the same
  listeners.

## [1.18.0] — Unreleased

The clean-public-repo wave: everything that ships to the public mirror was
audited, scrubbed, and re-plumbed, plus new evaluation surface since 1.17.5.

### Added

- **OpenAI Evals scaffold** (#621): reusable `eval_datasets` Hugging Face
  loader extracted from the SWE-bench importer, pluggable grader dispatcher
  wrapping the existing LLM judge, eval provenance columns on `test_results`,
  and an `openai-evals` job group, make target, and stub Robot suite.
- **SWE-bench Verified tail** (#60): `--dataset` / `--slice` CLI args on
  `run_swebench.py` targeting the Verified dataset, per-instance `difficulty`
  plumbed through `SWEBenchInstance`, and suite config that describes the
  shipped Verified upgrade.
- **DeepWiki badge**: the readme now links the auto-generated project wiki on
  DeepWiki (#630).
- **Graylog onboarding surface**: a `make graylog-doctor` preflight that checks
  each hop a log event takes (submodule checked out, sender packages importable,
  GELF inputs reachable, LLM streaming enabled), a harness-side runbook at
  `core/docs/graylog.md` (install → run → verify → troubleshoot, with the event
  schema), and a documented `GRAYLOG_*` block in `.env.example`.
- **This changelog.**

### Changed

- **PR-mode mirror publisher**: the public mirror is now updated by
  `.mirror/publish.sh --pr` — the staged public tree is pushed as one normal
  commit on a mirror branch and opened as a reviewable PR against
  `claude-code-staging`, replacing force-push rewrites. SSH remote is the
  default and a publish (DROP) allowlist codifies owner rulings on exactly
  which paths ship publicly.
- **Human-in-the-loop merge rule**: red CI is an absolute blocker. Nothing —
  including generated mirror-publish PRs — is presented as mergeable until
  every check is green; failing publishes are fixed at source and
  regenerated.

### Removed

- **GitLab CI support removed at source** (#106/#107): the write path, config
  surface, sync workflows, and remaining doc references are gone; the public
  repo ships no GitLab surface and CI is GitHub Actions only.
- **Identifier scrub**: personal email addresses and real fleet/host
  inventory were genericized out of everything that reaches the public
  surface (configs, docs, `.env` examples, test fixtures). Runtime behavior
  is unchanged — real hosts come from `OLLAMA_NODES_LIST` or locally edited
  config.
- The vestigial public-submodule CI guard retired from the public surface
  (#554).

### Fixed

- Checkpoint workflow concurrency scoped by event type so heartbeat and
  webhook runs no longer cancel each other (#638).
- Graylog make targets are layout-agnostic and skip-and-log when run outside
  the monorepo.
- Dead Graylog install references in `modules/ops/graylog` docs (a
  non-existent `core/requirements-graylog.txt` and a self-link that didn't
  resolve) now point at real paths; the `core/docs/graylog.md` the docs
  referenced now exists.

## [1.17.x] — 2026-06-12 → 2026-06-17

Stabilization of the June feature wave, plus caching and provenance.

- **Redis-backed answer cache** for `client.generate()` with cache-hit
  provenance persisted to results (#522, #524); `CachingProvider` is
  isinstance-transparent to the wrapped provider type.
- **Timeout contract**: LLM-suite Robot `Test Timeout` raised above the HTTP
  budget (`OLLAMA_TIMEOUT`, default 90 min) so slow local models skip or pass
  instead of false-failing; documented Ollama/`.env` setup and sizing guidance.
- **Model-readiness gate**: suites skip when the model is not ready instead of
  false-failing.
- Repaired concurrent-merge damage on staging (provider-suite runner, budget
  wiring, duplicate test classes) from the parallel-agent wave; agentic
  workflow verifiers hardened over multiple review rounds (#503).
- Role taxonomy config `config/claude_code_roles.yaml` (#599); ARC pilot
  rerun under a frozen contract (#390).

## [1.16.x] — 2026-06-12 → 2026-06-14

Providers beyond Ollama, and the cost controls to use them safely.

- **Free-tier providers**: Groq, Cerebras, and Google AI Studio backends
  (#509) and OpenRouter via the existing OpenAI client (#507).
- **Privacy routing guard**: local-only suites can never be routed to
  external free-tier providers (#512).
- **Cost & usage telemetry** (#511): token/cost estimator, monthly budget
  alarm, per-run token usage and estimated cost recorded on `test_runs`.
- **Provider budgets**: run planner with leftover carry-over (#510) and a
  runtime per-provider daily request counter with hard-stop (#515).
- **HF benchmark static-import pattern** (#126): google/IFEval 50-item subset
  and a Devign defect-detection subset for code review, imported once and
  committed as YAML.

## [1.15.x] — 2026-06-12

Recording and replaying what agents actually did.

- **Dialog import**: `rfc dialog import` ingests external Claude Code
  transcripts into the dialog schema (#355).
- **Replay engine, prompt mode**: re-run recorded prompts against new models
  (#356).
- **heal:suggest**: suggestion-only self-healing on failure — proposes fixes
  without mutating tests (#361).
- **Feedback-first role loops**: PR feedback outranks new work for the agent
  roles (#499).

## [1.14.x] — 2026-06-12

The generative listener family and sandboxed agentic coding.

- **agentic_decisions schema + read-only generative listener** (#358),
  **generative:flow** LLM-suggested flow control (#359), and
  **generative:mutate** LLM-suggested test mutation (#360).
- **Tier:4 Docker-sandboxed agentic-coding scenarios** with sandbox resource
  caps in agent config (#290), plus complex workflow verifiers — rebase,
  regression, bisectability (#292).
- **Multi-host job scheduler** with loaded-model affinity: curated
  `host-config.toml` inventory, global `(model, suite)` queue,
  `make run-local-models` / `run-all-external` split (#306).
- **LiveClaudeCodeRunner** adapter for the agentic-coding suite; official
  google/IFEval instruction checkers wired into `IFEvalKeywords`.
- External **skill-pack system** (#447) and the knowledge submodule (#454);
  agent sign-offs enforced with model attribution (#422).

## [1.12.x – 1.13.x] — 2026-06-11

Session bracketing: know which harness produced which results.

- **`rfc harness start|end|status`** session-bracketing CLI with
  plugin/skill snapshot helpers (#351) and an **AgenticHarnessListener** that
  auto-captures LLM metrics per run and joins `test_runs` to the active
  session (#352).
- **Dialog Recorder**: bracket keywords + `DialogListener`, with
  `dialog_recordings` / `dialog_turns` schema and CRUD (#354).
- **Tier:3 prose graders** for agentic-coding quality (#289).

## [1.11.x] — 2026-05-24 → 2026-06-11

Self-healing tests and self-monitoring repos.

- **Self-healing framework**: `@self_healing` decorator + strategy engine,
  `SelfHealingListener` for healing-event capture, prose-prompt API, and a
  nightly `analyzer_agent` failure review.
- **Robot coverage audit**: model × suite coverage matrix tool plus the
  audit-robot-reports skill; audits run after `run-local-models` passes.
- **Issue/PR monitoring system**: heartbeat + checkpoint workflows + local
  webhook listener, llm-ignore failsafe, and a draft-PR babysitting policy.
- Superset dark mode by default (6.0 theming); Superset exports + DB dump
  backed up to a submodule; ai/ playbooks promoted to discoverable Claude
  Code skills.
- SWE-bench dataset override on `Load SWEBench Instances`; ARC pilot
  artifact package (#390).

## [1.10.x] — 2026-05-07 → 2026-05-24

Reasoning suites and run provenance.

- **New behavioral suites**: causal reasoning, temporal reasoning, epistemic
  calibration, and sycophancy / pressure-resistance.
- **Agentic harness storage**: harness dataclasses with SQLite then
  SQLAlchemy `HarnessDatabase` backends.
- **Run watermark**: `rfc_version` / model / host / session stamped on robot
  runs; `session_id` and `model_harness` columns on `test_runs` and the
  full-results view.
- rfc-worktree skill for isolated per-branch development.

## [1.9.x] — 2026-04-25 → 2026-05-07

The agent-workflow foundation and structured-output validation.

- **Agent workflow stack**: OpenClaw data models, `AgentInteractionTracker`,
  tool-call validation engine, `AgentWorkflowDatabase` / Keywords / Listener,
  `MemoryManager` (short/long-term/persistent), agent runner factory with
  `OllamaAgentRunner` and `local_agents.yaml` config.
- **Structured-output suites**: JSON-schema validation keywords with retry
  logic, `tool_call_schema` suite, and tool-call schema validation keywords.
- **Safety calibration**: `AgenticInjectionGrader` + agentic_injection suite
  for tool-output injection, `RefusalCalibrationGrader` + suite for
  over-refusal detection, adversarial safety scenarios for agentic-coding
  (#291).
- **Consistency & stress**: temperature-stability `ConsistencyKeywords`,
  context-window stress suite (needle-in-haystack), multilingual
  instruction-following suite.
- **Model cards**: `make-model-cards` CLI generating SWOT summary cards from
  archived results; distinct joke-judging panel via `MultiGrader`.

## [1.8.x] — 2026-04-18 → 2026-04-25

- **Browser-based tests**: Superset dashboard and GitHub repo checks driven
  through the Browser library with LLM evaluation (#304).
- Removed `phi4:14b` silent fallbacks across the codebase — the model under
  test is always explicit (`DEFAULT_MODEL`).

## [1.7.x] — 2026-04-09 → 2026-04-18

- **Autonomous-workflow docs**: CLAUDE.md rewritten for a self-reviewing
  workflow; PR template with review guidance, testing evidence, and a
  version-bump checklist.
- **Agentic-coding suite scaffolding** and `ARGS` passthrough for extra robot
  CLI args in the Makefile.

## [1.6.x] — 2026-03-30 → 2026-04-09

The behavioral-suite wave and a leaner results database.

- **Eleven new behavioral suites**: adversarial injection, persona
  consistency, quantization degradation, demographic-parity bias, format
  compliance, GAIA-style tool use, hallucination detection, IFEval
  instruction-following (deterministic grading), multi-turn conversation
  quality, ReAct loop / meta-learning probe / tool hallucination, and MCP
  validation.
- **Token-efficiency metrics** with Superset datasets, charts, and layout.
- **Database split**: lean + archive tables (4-table layout) with a rewritten
  schema reference.
- **Resilience**: `retry-failed` / `retry-skipped` targets, versioned output
  directories under `results/<version>/`, skip-not-fail on empty LLM
  responses and unavailable Docker daemons.

## [1.5.x] — 2026-03-23 → 2026-03-30

- **Interview-question suites**: 85 C, 20 Rust, and 100 Bash questions as
  Robot tests with gold answers.
- **SWE-bench evaluation pipeline** integrated (containerized per-instance
  runs, hardened setup, per-instance failure isolation).
- **LLM creativity & humor suite**; configurable `max_retries` on
  `Ask And Validate`; `hide_thinking` stripping of unclosed thinking tokens;
  `RFCSkipError` hierarchy with `ROBOT_SKIP` for infra failures.
- pytest coverage tracking in CI; `uv.lock` untracked policy (pyproject pins
  are the source of truth).

## [1.4.3] — 2026-03-22 (last tagged release)

See [`v1.4.3`](https://github.com/tkarcheski/robotframework-chat/releases/tag/v1.4.3)
and earlier tags for the pre-1.5 history: the BaseListener consolidation,
metrics/output_xml extraction, mypy adoption, and the original math /
accounting / docker / safety suites.
