# Agent Workflows Test Suite

OpenClaw-style multi-turn agent workflow testing for Robot Framework.

## Overview

This suite captures agent execution as a structured `AgentWorkflow` —
a sequence of `AgentInteraction` turns, each containing messages, tool
calls, tool results, and state snapshots — and validates them with
Python-backed assertions. The captured workflow is emitted as
`RFC_DATA: agent_workflow` at end-of-test and persisted to a database
by `AgentWorkflowListener`.

## Architecture

```
robot/agent_workflows/
├── README.md                       # This file
├── agent_workflows.resource        # Library import
└── tests/
    ├── test_basic_workflow.robot   # Three-turn happy path (issue → PR mock)
    ├── test_tool_validation.robot  # Tool schema + ordering assertions
    ├── test_error_recovery.robot   # Tool failure and retry semantics
    ├── test_state_snapshots.robot  # Per-turn state_before / state_after
    └── test_live_agent.robot       # Two-turn conversation against real LLM (tier:3)
```

Python implementation lives in `src/rfc/`:

- `agent_tool.py`, `agent_interaction.py`, `agent_memory.py`,
  `agent_state.py`, `agent_workflow.py` — frozen dataclasses for the
  captured workflow shape.
- `agent_interaction_tracker.py` — mutable builder that produces a
  finalised `AgentWorkflow`.
- `agent_memory_manager.py` — sliding-window short-term, vector
  long-term, and schema-checked persistent memory.
- `tool_call_validator.py` — schema, ordering, and result validation.
- `agent_workflow_keywords.py` — Robot keyword library.
- `agent_workflow_db.py` — SQLite + PostgreSQL persistence.
- `agent_workflow_listener.py` — listener that persists captured
  workflows at end-of-test.

## Running Tests

```bash
# Whole suite (synthetic only — fast, no LLM)
uv run robot --include tier:1 robot/agent_workflows/

# Including the live-LLM test (requires DEFAULT_MODEL + reachable Ollama)
uv run robot robot/agent_workflows/

# With persistence (workflows saved to SQLite)
AGENT_WORKFLOW_DATABASE_URL=sqlite:///data/agent_workflows.db \
    uv run robot --listener rfc.agent_workflow_listener.AgentWorkflowListener \
    robot/agent_workflows/
```

## Tier and verify tags

| Test                       | Tier | Verify | Notes                                  |
| -------------------------- | ---- | ------ | -------------------------------------- |
| `test_basic_workflow`      | 1    | python | Deterministic mock                     |
| `test_tool_validation`     | 1    | python | Deterministic                          |
| `test_error_recovery`      | 1    | python | Deterministic                          |
| `test_state_snapshots`     | 1    | python | Deterministic                          |
| `test_live_agent`          | 3    | python | Two-turn live LLM, Python-graded shape |

## Writing a new agent workflow test

```robot
*** Settings ***
Resource          ../agent_workflows.resource
Default Tags      agent-workflow    tier:1    verify:python

*** Test Cases ***
My Workflow Test
    Agent.Start Agent Workflow    wf-1    claude    Describe task
    Agent.Start Interaction       1
    Agent.Agent Message           user        ...
    ${cid}=    Agent.Agent Calls Tool    git    {"cmd": "status"}
    Agent.Agent Receives Tool Result    ${cid}    ${True}    output=clean
    Agent.End Interaction         ${True}
    Agent.Assert Tool Was Called    git    1
    Agent.End Agent Workflow      ${True}
```

## Persisted schema

`AgentWorkflowDatabase` writes four tables:

- `agent_workflows` — one row per workflow (id, status, started_at,
  ended_at, error, metadata).
- `agent_interactions` — one row per turn (messages and state stored as
  JSON columns).
- `agent_tool_calls` — one row per call.
- `agent_tool_results` — one row per result (FK to call).

Database URL precedence: `AGENT_WORKFLOW_DATABASE_URL` > `DATABASE_URL`.
SQLite (default) and PostgreSQL (via SQLAlchemy) are both supported.
