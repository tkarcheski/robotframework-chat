*** Settings ***
Name              Agentic Coding
Documentation     Coding-agent workflow evaluation suite.
...
...               Verifies AI coding agents (Claude Code today; Codex CLI
...               and Gemini CLI in later PRs) against the machine-readable
...               contract in config/agent_contract.yaml.
...
...               PR #1 is Tier 1 only: deterministic checks over prerecorded
...               AgentRun fixtures. A live adapter that shells out to the real
...               CLI is a follow-up.

Force Tags        agentic_coding
