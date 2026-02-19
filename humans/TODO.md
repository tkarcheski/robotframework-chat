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
- [ ] **Add model size categories.** Define size buckets (8B, 16B, 64B, 128B, 256B+) so Superset/Grafana can group comparisons by weight class. Models should only be compared within their size category.

---

## Grading System Evolution

- [ ] **Design the grading keyword ecosystem.** Three grading modes, all tagged:
  - `Pass/Fail` (current) — binary, for deterministic answers (math, safety)
  - `Letter Grade` (A/B/C/D/F) — rubric-based, for subjective quality
  - `A/B Comparison` — model-vs-model, relative ranking
  - IQ scoring should be a Robot Framework **tag** on tests, not a grading mode
- [ ] **Decide: deterministic grading first, LLM grading only when needed.** For math: use Robot asserts (`Should Be Equal`). For code: execute and check exit code. For safety: regex + heuristics. Only use LLM grader for fuzzy evaluation (explanation quality, writing quality). This reduces dependency on grader accuracy.
- [ ] **External grader endpoint support.** Make the grading LLM configurable to run on a different Ollama instance or via OpenRouter API. Short-term: add `GRADER_ENDPOINT` and `GRADER_MODEL` env vars. Long-term: OpenRouter integration for cloud-hosted grading.
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

- [ ] **Design sci-fi Grafana dashboards.** Ideas:
  - Dark theme with cyan/magenta/electric-blue neon accents
  - "Mission control" layout: model status gauges, real-time tokens/sec streaming, node health matrix
  - Hexagonal grid for model comparison (like a radar/spider chart per model)
  - Animated time-series with glow effects (Grafana supports CSS overrides)
  - Terminal/HUD-style stat panels with monospace fonts
  - "Model duel" view: side-by-side A/B comparison with live scoring
  - Heatmap: model x test-suite matrix showing pass rates by color intensity
  - Consider Grafana plugins: Flowcharting, Treemap, Candlestick (for score distributions)
- [ ] **Deprecate Superset or define its role.** With Grafana taking over visualization, decide: keep Superset for SQL exploration / ad-hoc queries only? Or remove it entirely? Running both is maintenance overhead.

---

## CI/CD & Pipeline

- [ ] **Fix "Not Complete" Makefile targets.** 24 of 37 targets are marked "Not Complete" in FEATURES.md. Triage: which are actually broken vs. which just need environment setup?
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

*Last updated: 2026-02-19 — from spec review session*
