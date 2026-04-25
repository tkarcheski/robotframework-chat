# robotframework-chat

A Robot Framework-based test harness for systematically testing Large Language Models (LLMs) using LLMs as both the system under test and as automated graders. Test results are archived to SQL and visualized in Apache Superset dashboards.

---

## Quick Start

### Prerequisites

- **Python 3.11+** and **astral-uv** for dependency management
- **Docker** for containerized code execution, LLM testing, and the Superset stack
- **Ollama** (optional) for local LLM testing

### Installation (Linux / macOS)

```bash
make install                # Install all dependencies
pre-commit install          # Install pre-commit hooks
ollama pull phi4:14b         # Pull default LLM model (optional)
```

### Installation (Windows)

The `tasks.py` script provides a cross-platform alternative to the Makefile.
It requires only Python and `uv` — no `make`, `bash`, or Unix tools needed.

```powershell
uv run python tasks.py install      # Install all dependencies
uv run pre-commit install           # Install pre-commit hooks
ollama pull qwen3.5:27b             # Pull default LLM model (optional)
uv run python tasks.py help         # List all available targets
```

> **Note:** Docker-based tests require [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/) with the WSL 2 backend enabled.

### Running Tests

```bash
# Linux / macOS
make robot                  # Run all Robot Framework test suites
make robot-math             # Run math tests
make robot-docker           # Run Docker tests
make robot-safety           # Run safety tests

# All platforms (including Windows)
uv run python tasks.py robot        # Run all suites
uv run python tasks.py robot-math   # Run math tests
uv run python tasks.py robot-dryrun # Validate tests (dry run)
uv run python tasks.py check        # Lint + typecheck + coverage
```

### Superset Dashboard

```bash
# Linux / macOS
cp .env.example .env        # Configure environment
make docker-up              # Start PostgreSQL + Redis + Superset
make bootstrap              # First-time Superset initialization

# Windows — tasks.py copies .env automatically if missing
uv run python tasks.py docker-up
```

Open <http://localhost:8088> to view the dashboard.

---

## Ollama Configuration

### Pulling Models

The default model is `phi4:14b` (set via `DEFAULT_MODEL` in `.env`).
Pull additional models depending on how many you want to test against:

**Starter (3 models):**

```bash
ollama pull phi4:14b
ollama pull llama3.2:latest
ollama pull gemma2:latest
```

**Standard (4–5 models):**

```bash
ollama pull phi4:14b
ollama pull llama3.2:latest
ollama pull gemma2:latest
ollama pull mistral:latest
ollama pull qwen3.5:27b
```

**Full fleet** — pull all models from `config/test_suites.yaml`:

```bash
make cron-sync-models        # Pulls any master models missing locally
```

### Loading Multiple Models Simultaneously

By default Ollama keeps up to 3 models loaded in memory (3 × number of GPUs,
or 3 for CPU inference). To load more models concurrently, configure these
Ollama server environment variables:

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_MAX_LOADED_MODELS` | 3 × GPUs (or 3) | Max models resident in memory at once |
| `OLLAMA_NUM_PARALLEL` | `1` | Parallel requests per loaded model |
| `OLLAMA_MAX_QUEUE` | `512` | Max queued requests before rejecting |

> **Memory note:** each loaded model consumes VRAM/RAM proportional to its
> size. A 7B Q4 model uses ~4 GB; a 27B model uses ~16 GB. Setting
> `OLLAMA_NUM_PARALLEL` > 1 multiplies context memory per model.

**Linux (systemd):**

```bash
sudo systemctl edit ollama.service
```

Add under `[Service]`:

```ini
[Service]
Environment="OLLAMA_MAX_LOADED_MODELS=5"
Environment="OLLAMA_NUM_PARALLEL=2"
```

Then restart:

```bash
sudo systemctl restart ollama
```

**macOS:**

```bash
launchctl setenv OLLAMA_MAX_LOADED_MODELS 5
launchctl setenv OLLAMA_NUM_PARALLEL 2
```

Restart the Ollama application after setting these.

**Windows:**

Set `OLLAMA_MAX_LOADED_MODELS` and `OLLAMA_NUM_PARALLEL` as system environment
variables, then restart Ollama.

### VRAM Sizing Guide

| Models Loaded | Recommended VRAM | Example Hardware |
|---|---|---|
| 3 (default) | 24 GB | RTX 4090, M2 Pro |
| 4 | 32 GB | 2× RTX 4080, M2 Max |
| 5+ | 48+ GB | 2× RTX 4090, M3 Ultra |

Actual requirements depend on model sizes and quantization levels.

### Auto-Discovery and Multi-Model Testing

The test harness auto-discovers available models at startup and skips tests
for models that are not installed — you will never get failures from missing
models.

```bash
make discover-local-models   # List models available on all configured nodes
make run-local-models        # Run all test suites against every discovered model

# Windows
uv run python scripts/run_local_models.py --discover-models
uv run python scripts/run_local_models.py
```

Use `ITERATIONS` for continuous testing:

```bash
make run-local-models ITERATIONS=-1   # Run forever
make run-local-models ITERATIONS=0    # Stop on first error
```

### Multi-Node Setup (Optional)

To distribute tests across multiple machines running Ollama, set
`OLLAMA_NODES_LIST` in `.env`:

```bash
OLLAMA_NODES_LIST=localhost,gpu-server-1,gpu-server-2
```

Or edit the `nodes` list in `config/test_suites.yaml` directly. Check node
status with:

```bash
make discover-local-nodes
```

### Project Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | Provider backend (`ollama` or `openai`) |
| `OLLAMA_ENDPOINT` | `http://localhost:11434` | Ollama API endpoint |
| `DEFAULT_MODEL` | `phi4:14b` | Model used for standard test runs |
| `OLLAMA_TIMEOUT` | `5400` | Request timeout in seconds (90 min) |
| `OLLAMA_NODES_LIST` | `localhost` | Comma-separated Ollama hostnames |

---

## Generating Model Cards

Model cards are objective SWOT analysis summaries of LLM test performance. They combine empirical metrics (pass rates, latency, throughput) with LLM-generated qualitative analysis.

### Setup

Install the Superset extra (required for database querying):

```bash
uv sync --extra superset
```

### Generate Cards for All Models

```bash
# Using Make
make model-cards

# Or directly
uv run python -m rfc.make_model_cards
```

Cards are written to `model_cards/<model_slug>.md` and ready to commit and publish.

### Generate Card for a Single Model

```bash
uv run python -m rfc.make_model_cards --model qwen2.5:72b
```

### Customize Output Directory

```bash
uv run python -m rfc.make_model_cards --output docs/models/
```

### Configuration

Environment variables (or CLI flags):

| Variable | CLI Flag | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | `--database-url` | `sqlite:///data/test_history.db` | Test results database |
| `OLLAMA_ENDPOINT` | `--ollama-endpoint` | `http://localhost:11434` | Ollama API endpoint |
| `MODEL_CARD_LLM` | `--llm-model` | `qwen2.5:72b` | LLM for SWOT analysis |

Example with custom settings:

```bash
uv run python -m rfc.make_model_cards \
  --output model_cards/ \
  --ollama-endpoint http://gpu-server:11434 \
  --llm-model llama3.2:latest
```

### Card Format

Each card includes:

- **Metadata:** Provider, parameters, quantization, context window
- **Benchmarks:** Pass rate, latency (p50/p95/p99), throughput per suite
- **Overall Results:** Aggregated metrics + 7d vs 30d prior trend
- **SWOT Analysis:** LLM-generated Strengths, Weaknesses, Opportunities, Threats

Example card: [model_cards/qwen2.5_72b.md](model_cards/qwen2.5_72b.md) (if available)

---

## Example Test

```robot
*** Test Cases ***
LLM Can Do Basic Math
    ${answer}=    Ask LLM    What is 2 + 2?
    ${score}    ${reason}=    Grade Answer    What is 2 + 2?    4    ${answer}
    Should Be Equal As Integers    ${score}    1
```

---

## Core Philosophy

- **LLMs are software** — test them like software
- **Determinism before intelligence** — structured, machine-verifiable evaluation first
- **Constrained grading** — scores, categories, pass/fail; no prose from the evaluation layer
- **Modular by design** — composable pieces; new providers and graders plug in without rewriting core
- **Robot Framework as the orchestration layer** — readable, keyword-driven tests
- **Every test run is archived** — listeners always active, results flow to SQL
- **CI-native, regression-focused** — if it can't run unattended, it's not done

See [ai/agents.md](ai/agents.md#core-philosophy) for the full philosophy.

---

## Documentation

| Document | Description |
|----------|-------------|
| [docs/TEST_DATABASE.md](docs/TEST_DATABASE.md) | Database schema and usage |
| [docs/GITLAB_CI_SETUP.md](docs/GITLAB_CI_SETUP.md) | CI/CD setup guide |
| [docs/GRAFANA_SUPERSET_SETUP.md](docs/GRAFANA_SUPERSET_SETUP.md) | Superset visualization stack setup (Grafana deferred to v2+) |
| [docs/SUPERSET_EXPORT_GUIDE.md](docs/SUPERSET_EXPORT_GUIDE.md) | Superset dashboard export, import, and backup |
| [Ollama Configuration](#ollama-configuration) | Multi-model loading, VRAM sizing, and multi-node setup |

---

## Contributing

1. Read [ai/dev.md](ai/dev.md) for the development workflow and TDD discipline
2. Follow the code style guidelines in [ai/agents.md](ai/agents.md)
3. Add tests for new features (see [ai/testing.md](ai/testing.md) for grading tiers)
4. Run `pre-commit run --all-files` before committing
