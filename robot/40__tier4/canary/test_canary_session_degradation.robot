*** Settings ***
Documentation     LIVE canary session-degradation measurement (axis:model).
...
...               Pins one standing instruction on a real model session —
...               "include the token '${CANARY_TOKEN}' in every reply" — then
...               drives a long multi-turn conversation and measures how many
...               turns the session survives before the model first drops the
...               token. That first drop is the degradation point; turns, response
...               tokens, and wall-clock to that point are recorded on the spine
...               via RFC_DATA for the scoreboard.
...
...               LONG-RUNNING and opt-in: gated behind ``CANARY_LIVE=1`` so it
...               never spends model time by accident. Holding the harness (our
...               conversation driver) and model constant, this suite varies only
...               the turn index — the single axis it discriminates is the model,
...               so the per-model sweep (``make run-local-models``) is the
...               follow-up that fans this across every discovered model.
...
...               axis:harness FOLLOW-UP: the same engine
...               (``rfc.canary.run_canary_session``) is responder-agnostic. Plug a
...               coding-agent harness session in as the responder and the identical
...               measurement becomes a per-HARNESS durability test — a separate
...               ``axis:harness`` suite behind the harness keyword surface, not a
...               change here. Deterministic twins: ``tests/test_canary.py`` and
...               ``tests/test_canary_keywords.py``; logic suite:
...               ``robot/10__tier1/canary``.

Resource          canary_session.resource

Suite Setup       Require Canary Live Mode

Test Tags         canary    tier:4    verify:python    axis:model    category:live

# The per-test wall-clock budget for a whole multi-call session. Kept well above
# the single-call OLLAMA_TIMEOUT (90 min) per the CLAUDE.md invariant, since one
# session makes many generate() calls.
Test Timeout      600 minutes

*** Variables ***
${CANARY_TOKEN}         %{CANARY_TOKEN=Tyler}
# Hard cap on turns for the long run; the session stops earlier the moment it
# degrades. Override with CANARY_MAX_TURNS for a longer or shorter sweep.
${CANARY_MAX_TURNS}     %{CANARY_MAX_TURNS=50}
# A short cap for the floor case so it stays cheap.
${CANARY_FLOOR_TURNS}   3

*** Test Cases ***
Canary Floor — Model Echoes The Token On Turn One
    [Documentation]    Floor assertion: a model that cannot echo the canary even
    ...                on the very first turn is fundamentally unable to follow the
    ...                standing instruction, and no degradation measurement is
    ...                meaningful. This is the golden path; if it fails, something
    ...                is wrong before durability is even in question.
    [Tags]    floor
    ${result}=    Run Canary Session    token=${CANARY_TOKEN}    max_turns=${CANARY_FLOOR_TURNS}
    Should Be True    ${result.total_turns} >= 1    the session must run at least one turn
    Should Be True    ${result.turns}[0].hit
    ...    the model failed to include the canary token '${CANARY_TOKEN}' on turn 1

Measure Turns To Session Degradation
    [Documentation]    The measurement: drive up to ${CANARY_MAX_TURNS} turns,
    ...                stopping at the first dropped token, and record turns /
    ...                tokens / wall-clock to degradation. Degradation is the
    ...                signal being measured, not a failure — so this emits metrics
    ...                and only floor-asserts that the canary survived at least the
    ...                first turn (the turn-1 contract from the floor case).
    [Tags]    measurement    degradation    stress
    ${result}=    Run Canary Session    token=${CANARY_TOKEN}    max_turns=${CANARY_MAX_TURNS}
    Log    Canary '${CANARY_TOKEN}' survived ${result.survived_turns} of ${result.total_turns} turns; degraded=${result.degraded} at turn ${result.degradation_turn}
    Should Be True    ${result.survived_turns} >= 1
    ...    the session degraded before completing a single turn — see the floor case
