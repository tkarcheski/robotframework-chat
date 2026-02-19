# Robot Framework Dashboard (Deprecated — Grafana Replacing)

> **DEPRECATION NOTICE (2026-02-19):** This Dash-based dashboard is a prototype.
> It will be replaced by TRON-themed Grafana dashboards. Do not invest further
> development effort here. See `humans/TODO.md` § Dash Dashboard Deprecation
> for the migration plan.

A web-based dashboard for running and managing multiple Robot Framework test sessions concurrently.

## Features

- **Multiple Sessions**: Run up to 5 concurrent test sessions
- **Live Monitoring**: Real-time console output and progress tracking
- **Colored Tabs**: Visual status indicators (green=complete, red=failed, gray=busy)
- **Auto-Recovery**: Optional automatic restart on test failures
- **LLM Model Selection**: Dropdown to choose from available Ollama models
- **Test History**: View and manage past test runs
- **Session Runtime**: Each tab shows elapsed time

## Usage

### Starting the Dashboard

```bash
# Install with dashboard dependencies
uv sync --extra dashboard

# Run the dashboard
rfc-dashboard

# Or with options
rfc-dashboard --host 0.0.0.0 --port 8050 --debug
```

### Creating Sessions

1. Click "➕ New Session" to create a new test session
2. Configure settings:
   - **Test Suite**: Select the test suite to run (math, docker/python, etc.)
   - **IQ Levels**: Filter tests by IQ tag (100-160)
   - **LLM Model**: Choose an available Ollama model
   - **Container Profile**: Resource allocation (MINIMAL, STANDARD, PERFORMANCE)
   - **Auto-recover**: Enable automatic restart on failure
3. Click "▶️ Run" to start the test

### Session Management

- **Colored Tabs**:
  - 🟢 Green = Complete/Success
  - 🔴 Red = Failed
  - ⚪ Gray = Running/Busy
- **Runtime Display**: Each tab shows elapsed time
- **Live Output**: Console output streams in real-time
- **Progress Bar**: Visual indicator of test completion

### Controls

- **▶️ Run**: Start a new test run
- **⏹️ Stop**: Stop the current test run
- **🔄 Replay**: Re-run the same configuration
- **💾 Save**: Save test results to history

## Architecture

```
dashboard/
├── app.py                    # Main Dash application
├── cli.py                    # CLI entry point
├── core/
│   ├── session_manager.py    # Process orchestration (max 5 sessions)
│   ├── robot_runner.py       # Subprocess wrapper with auto-recovery
│   └── llm_registry.py       # Ollama model discovery
├── callbacks/
│   └── execution_callbacks.py # Dash callbacks for interactivity
└── assets/
    └── style.css             # Custom styling
```

## Configuration

Default settings can be modified in the UI or through code:

```python
from dashboard.core.session_manager import SessionConfig

config = SessionConfig(
    suite="robot/math/tests",
    iq_levels=["100", "110", "120"],
    model="llama3",
    profile="STANDARD",
    auto_recover=True,
)
```

## Requirements

- Python 3.11+
- Ollama (for LLM model discovery)
- Docker (for container-based tests)

## Development

```bash
# Run with hot reload
rfc-dashboard --debug

# Run linting
uv run ruff check dashboard/
```
