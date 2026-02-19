# TODO — Human Action Items

Items identified during project specification review (2026-02-19).
These require human decisions, manual setup, or external work.

---

## Infrastructure & Hardware

- [ ] **Map nodes to GitLab runner tags.** The `config/test_suites.yaml` `nodes:` section uses hostnames (`mini1`, `ai1`, `dev1`, etc.). These need to become GitLab CI runner tags so the pipeline scheduler can route jobs to the correct hardware. Decide on tag naming convention (e.g., `gpu-4090`, `tpu-tenstorrent`, `apple-m4-16gb`, `apple-m4-64gb`).
- [ ] **Document hardware specs per node.** Create a hardware inventory (GPU/TPU model, VRAM, system RAM, CPU) so test results can be correlated with hardware capability. Proposed location: `config/test_suites.yaml` under each node entry.
  - `ai1`: Linux, TenstorrentTPU, 256GB RAM, AMD CPU
  - `mini1`: Mac Mini M4, 16GB
  - `mini2`: Mac Mini M4, 64GB
  - `dev1`: NVIDIA RTX 4090
  - `dev2`: Laptop, NVIDIA RTX 5070 Mobile
- [ ] **Tenstorrent TPU support.** `ai1` has a Tenstorrent TPU that isn't currently used. Research Tenstorrent's inference stack (tt-metal / tt-buda) and whether Ollama or another serving layer can target it. This is future work but should be tracked.
- [ ] **Remove the custom Dash dashboard.** Owner confirmed Grafana will replace it. Plan the deprecation: remove `dashboard/` directory, remove `make test-dashboard*` targets, remove dashboard Docker service from `docker-compose.yml`, remove `[dashboard]` optional dependency from `pyproject.toml`.

---

## Database & Schema Changes

- [ ] **Add model metadata fields to database.** Call Ollama `/api/show` per model and store: quantization level (e.g., Q4_K_M, Q8_0), parameter count, architecture (llama, mistral, etc.), context length, family, license. Requires new columns on `models` table or a new `model_metadata` table.
- [ ] **Add tokens/sec performance tracking.** Ollama's `/api/generate` response includes `eval_count`, `eval_duration`, `prompt_eval_count`, `prompt_eval_duration`, `load_duration`. Capture these in `keyword_results` or a new `llm_performance` table. This is critical for the "fastest model" comparison.
- [ ] **Add hardware context to test runs.** Each test run should record which node (and therefore which hardware) executed it. Currently `runner_id` and `runner_tags` capture CI runner info, but for local runs there's no hardware fingerprint.
- [ ] **Track quantization in the database.** Parse the model tag (e.g., `llama3:8b-q4_K_M`) or use `/api/show` to get quantization details. Store in model metadata so you can compare Q4 vs Q8 vs FP16 performance.
- [ ] **Add model size in GB.** Model size should be stored in gigabytes (disk size of the GGUF/safetensors), not just parameter count. This can be researched from web sources or pulled from `/api/show`. Enables "best model that fits in X GB VRAM" queries.
- [ ] **Add model size categories.** Define size buckets (8B, 16B, 64B, 128B, 256B+) so Superset/Grafana can group comparisons by weight class. Models should only be compared within their size category.
- [ ] **Add cost tracking placeholder.** For local models, cost = wall-clock time (seconds). Schema: `cost_seconds REAL`, `cost_dollars REAL NULL`. Local runs populate seconds only. Future OpenRouter runs populate dollars. Enables "best model per dollar" and "best model per second" leaderboards.

---

## Grading System — Tier Model (Owner-Confirmed)

All tests are verified by Robot Framework. Every test must have Robot or Python checks.

| Tier | Name | Description |
|------|------|-------------|
| **Tier 0** | Pure Robot | Deterministic Robot Framework asserts only (`Should Be Equal`, regex, etc.) |
| **Tier 1** | Robot + Python | Robot keywords backed by Python logic (custom libraries, data parsing) |
| **Tier 2** | Robot + LLM | Single LLM grader evaluates the response |
| **Tier 3** | Robot + LLMs (consensus) | 3+ LLM models grade the response; Robot warns on disagreement |
| **Tier 4** | Robot + LLMs + Docker | LLM output executed in sandboxed Docker container (code gen, scripts) |
| **Tier 5** | Other | External grading services, human-in-the-loop, hybrid approaches |
| **Tier 6** | None | Ungraded — data collection only, no pass/fail |

- [ ] **Implement Tier 0–1 first.** These are the foundation — pure Robot asserts and Python-backed keywords. All existing tests should map to these tiers.
- [ ] **Implement Tier 2.** Single LLM grader with configurable endpoint (`GRADER_ENDPOINT`, `GRADER_MODEL` env vars).
- [ ] **Implement Tier 3 — LLM consensus grading.** Run 3+ grader models on the same response. Robot keyword emits a **WARNING** (Robot Framework `Log  message  WARN`) when graders disagree. Majority vote determines grade. Log all individual grades for analysis. The LLM "console" (grading panel) should surface disagreements prominently in Grafana.
- [ ] **Implement Tier 4 — Docker sandbox.** For code generation tests: execute LLM output in a disposable Docker container, check exit code and stdout. Robot keyword wraps Docker execution.
- [ ] **Tag all tests with their tier.** Use Robot tags: `tier:0`, `tier:1`, etc. This enables filtering by tier in CI and Grafana.
- [ ] **Grader validation strategy.** Build a "grader test suite" — known question/answer/expected-grade triples. Run this suite to validate that the grading model itself is accurate before trusting its grades on real tests.

---

## Ollama API & Model Metadata Feature

- [ ] **Implement `/api/show` integration.** Add `OllamaClient.show_model(name)` method that calls Ollama's `/api/show` endpoint. Returns: architecture, parameter count, quantization, context length, license, template, system prompt, and more. Add unit tests.
- [ ] **Create Robot keyword `Collect Model Metadata`.** Calls `show_model()` for each model on a node and stores results in the database. Should run as a CI pipeline step before test execution.
- [ ] **Create `robot/ci/model_metadata.robot` test suite.** Runs in pipeline, collects metadata for all available models, archives to database via listener.
- [ ] **Ollama API limitations to be aware of:**
  - `/api/generate` is synchronous — one request at a time per model (queued)
  - No native batch API — concurrent testing requires multiple Ollama instances or sequential execution
  - `/api/show` doesn't return actual benchmarks — only static metadata
  - Token counts (`eval_count`) are in the response but not currently captured
  - Ollama has no authentication — any network access = full access
  - Model pull/delete operations are available but dangerous in CI

---

## Visualization

- [ ] **Design TRON-themed Grafana dashboards.** Owner confirmed: TRON aesthetic, 10000%.
  - **Color palette:** Black background, cyan (#00FFFF) primary, electric blue (#0080FF), white (#FFFFFF) text, orange (#FF6600) for warnings, red for failures
  - **Grid lines:** Glowing cyan grid on dark background (the iconic TRON grid)
  - **Panels:** Beveled edges, subtle glow effects, circuit-board styling
  - **Fonts:** Monospace, geometric sans-serif (like TRON: Legacy titles)
  - **Animations:** Data flowing like light cycles along grid lines
  - Specific views:
    - "The Grid" — node health matrix, glowing when active
    - "Light Cycle Arena" — model-vs-model A/B comparison
    - "Identity Disc" — radar/spider chart per model (accuracy, speed, safety, cost)
    - "MCP Dashboard" (fitting name!) — Master Control Program overview of all test runs
    - Heatmap: model x test-suite matrix, cyan-to-orange intensity
  - Consider Grafana plugins: Flowcharting, Treemap, Candlestick (for score distributions)
- [ ] **Deprecate Superset or define its role.** With Grafana taking over visualization, decide: keep Superset for SQL exploration / ad-hoc queries only? Or remove it entirely? Running both is maintenance overhead.

---

## CI/CD & Pipeline

- [ ] **Fix "Not Complete" Makefile targets.** 24 of 37 targets are marked "Not Complete" in FEATURES.md. Triage: which are actually broken vs. which just need environment setup?
- [ ] **Add `make test-make` target.** A meta-target that runs a dry-run or smoke test of every other make target to verify they at least parse and start correctly. Could use `make -n` (dry-run) for dangerous targets and actual execution for safe ones.
- [ ] **Pipeline node auto-discovery.** Pipelines should discover which nodes are online before scheduling jobs. Proposed flow: (1) ping each node's Ollama `/api/tags` endpoint, (2) build a live inventory of online nodes + available models, (3) schedule jobs only to reachable nodes. This replaces hardcoded node lists.
- [ ] **Model-to-node assignment config.** Owner wants to control which models are loaded on which hosts. Short-term: a `config/model_assignments.yaml` file. Long-term: web UI to manage assignments. The pipeline reads this config and calls `ollama pull` / `ollama rm` to enforce the desired state.
- [ ] **Node-to-GitLab-tag mapping.** Update `config/test_suites.yaml` nodes to include a `gitlab_tag` field. Update `scripts/generate_pipeline.py` to use these tags when generating child pipeline jobs. Example:
  ```yaml
  nodes:
    - hostname: dev1
      port: 11434
      gitlab_tag: gpu-4090
      hardware:
        gpu: "NVIDIA RTX 4090"
        vram_gb: 24
        ram_gb: 64
  ```
- [ ] **Verify GitHub Actions pipeline.** Is the GitHub Actions workflow current, or has it drifted from the GitLab pipeline? If GitLab is the source of truth, consider auto-generating the GitHub workflow from the same config.

---

## Architecture Decisions Needed

- [ ] **LLM client abstraction.** `OllamaClient` is Ollama-specific. If OpenRouter support is coming, decide: refactor now into a generic `LLMClient` interface with `OllamaProvider` and `OpenRouterProvider` backends? Or bolt on OpenRouter support later?
- [ ] **A/B testing data model.** Multi-model comparison needs a way to link test runs that used the same prompt. Current schema doesn't support "test session" or "comparison group" concepts. Design this before building the A/B feature.
- [ ] **Dashboard deprecation plan.** The Dash dashboard in `dashboard/` is feature-rich but owner wants to replace with Grafana. Create a migration plan: what Grafana dashboards need to exist before `dashboard/` can be deleted?

---

## Quick Wins

- [ ] **Capture Ollama response metadata now.** In `ollama.py:generate()`, the response JSON already contains `eval_count`, `eval_duration`, `prompt_eval_count`, etc. Start returning or logging these alongside the text response. Low effort, high value.
- [ ] **Add quantization to model name parsing.** Parse tags like `llama3:8b-q4_K_M` to extract base model, size, and quantization. Use this in database records immediately.
- [ ] **Add `RETURN` keyword audit.** CLAUDE.md says "Use `RETURN` (not `[Return]`)" — verify all `.robot` files comply.

---

## Packaging & Distribution

- [ ] **Decide distribution method.** Options researched:
  - **PyPI** — `pip install rfc`. Widest reach, standard Python ecosystem. Requires unique package name (rfc is likely taken — may need `robotframework-chat` or `rf-chat`).
  - **GitLab/GitHub Package Registry** — `pip install` from private registry. Good for internal use, no name conflicts. Free for public repos.
  - **`pip install git+https://...`** — Zero infrastructure. Just point at the repo. Works today with no changes.
  - **Conda / conda-forge** — If targeting data science users who prefer conda environments. More packaging effort.
  - **Docker image** — `docker run rfc ...`. Bundles everything (Python, Robot, Ollama client). Best for CI and reproducibility.
  - **GitHub Releases / `.whl` artifacts** — Attach wheel files to GitHub releases. Manual but simple.
  - **Just a forkable template** — No packaging at all. Users fork and customize. Simplest, but no upstream updates.
- [ ] **Template documentation.** Write a "How to use RFC as a template" guide — what to fork, what to customize, how to add your own test suites while keeping the CI/listener/database infrastructure.

---

## AI-Powered Code Review in CI

- [ ] **AI agent PR review pipeline.** The `ci/review.sh` stage should use an AI agent to:
  1. Review code changes (diff)
  2. Review pipeline results (pass/fail, regressions)
  3. Approve or deny the pull request (pass/fail)
  4. Grade the code quality (letter grade)
  5. Generate a full report (posted as PR comment)
- [ ] **Makefile parity with pipeline.** Every CI stage must have a corresponding `make` target so the full pipeline can run locally. Audit and fix the 24 "Not Complete" targets.
- [ ] **Robot Framework tasks for AI review (investigate).** Owner thinks this might be too complex for CI, but worth exploring. A `robot/ci/review.robot` task file that drives the AI review workflow could be a powerful showcase of Robot tasks.

---

## Agentic Workflows & Playwright

- [ ] **Playwright-based agentic workflows.** Use Robot Framework + Browser library (Playwright) for agentic web automation. Examples:
  - Navigate to Ollama web UI and collect model info visually
  - Interact with Grafana dashboards programmatically
  - Scrape model leaderboards from external sites
  - Automated Superset/Grafana dashboard validation
- [ ] **Robot Framework Tasks (not tests).** Explore RF's `*** Tasks ***` syntax for non-test automation (RPA-style). Could be used for: model metadata collection, dashboard provisioning, node health checks, report generation.

---

## Branching & Workflow

- [ ] **Document the branching strategy.** Current workflow:
  - `main` — human-reviewed, tested, stable
  - `claude-code-staging` — AI agent working branch
  - `claude/*` — per-session feature branches (merged via PR)
  - GitLab CI runs on both `main` and staging to catch regressions
  - GitHub mirrors for code checks only
  - Owner syncs staging → main after review and testing

---

## Dash Dashboard Deprecation

- [ ] **Dashboard is confirmed as prototype.** Migration path:
  1. Identify what Grafana needs to replicate (node monitoring, test triggering)
  2. Test triggering will move to CLI (`make`) and CI (GitLab pipelines) only
  3. Once Grafana dashboards cover visualization needs, remove `dashboard/` entirely
  4. Remove: `dashboard/` dir, Docker service, `[dashboard]` extra, `make test-dashboard*` targets

---

*Last updated: 2026-02-19 — from spec review session (round 3)*
