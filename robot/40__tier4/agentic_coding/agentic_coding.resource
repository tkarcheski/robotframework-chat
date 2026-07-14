*** Settings ***
Documentation     Shared keywords and variables for the agentic-coding suite.

Library           rfc.agentic_coding_keywords.AgenticCodingKeywords

*** Variables ***
${AGENT_ID}                 claude-code
# Live-harness opt-in for the tier:4 sandbox suite (#174). Empty keeps the
# scripted stand-ins as the deterministic default; set e.g.
# `--variable SANDBOX_HARNESS:opencode` to drive a real coding-agent CLI
# host-side, optionally with `--variable SANDBOX_HARNESS_MODEL:ollama/<model>`.
${SANDBOX_HARNESS}          ${EMPTY}
${SANDBOX_HARNESS_MODEL}    ${EMPTY}
