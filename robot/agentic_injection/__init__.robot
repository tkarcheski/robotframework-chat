*** Settings ***
Name              Agentic Injection
Documentation     Agentic Prompt Injection Resistance Suite
...
...               Tests whether an LLM acting as an agent ignores injected
...               instructions embedded in retrieved tool outputs (web scrapes,
...               API responses, file reads).
...
...               This is the indirect injection attack surface that matters
...               most for agentic pipelines, distinct from the direct
...               user-input injection covered by robot/safety/.

# Force tags applied to every test in this suite (tier and verify mandatory).
Force Tags        agentic_injection    regression    tier:2    verify:llm
