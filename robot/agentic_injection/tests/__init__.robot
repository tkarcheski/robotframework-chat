*** Settings ***
Name              Agentic Injection Tests

# Force tags applied to every test in this suite (tier and verify mandatory).
# These are duplicated from parent __init__.robot to ensure they're preserved
# when retry workflows run robot/agentic_injection/tests directly.
Force Tags        agentic_injection    regression    tier:2    verify:llm
