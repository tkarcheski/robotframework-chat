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
