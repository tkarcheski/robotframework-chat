*** Settings ***
Documentation     Canary session-degradation LOGIC tests (deterministic).
...
...               The canary idea: pin one standing instruction on a session —
...               "include the token <name> in every reply" — then drive many
...               turns and detect the FIRST turn that drops the token. That turn
...               is the session's degradation point. This suite verifies the
...               detection contract itself (whole-word hit detection, first-miss
...               stop, and the full hit/miss curve) with SCRIPTED responses, so
...               it needs no model and is always green in CI.
...
...               The live, model-driven counterpart is the tier:4 suite
...               ``robot/40__tier4/canary`` (axis:model), which plugs a real LLM
...               session into the same engine. Deterministic twin in Python:
...               ``tests/test_canary.py``.

Resource          canary.resource

Test Tags         canary    tier:1    verify:python    axis:none

*** Variables ***
${TOKEN}          Tyler

*** Test Cases ***
Session Holds The Canary For Every Turn
    [Documentation]    Every reply echoes the token, so the session never
    ...                degrades: degraded is False and there is no degradation
    ...                turn.
    ${responses}=    Create List
    ...    Sure thing, ${TOKEN}!
    ...    Happy to help, ${TOKEN}.
    ...    Of course, ${TOKEN} — here you go.
    ${result}=    Run Scripted Canary Session    ${responses}    ${TOKEN}
    Session Should Not Degrade    ${result}
    Should Be Equal As Integers    ${result.total_turns}    3
    Should Be Equal As Integers    ${result.degradation_turn}    0

Session Degrades At The First Dropped Token
    [Documentation]    The token holds for two turns, then drops on turn 3.
    ...                First-miss policy: degradation is declared at turn 3 and
    ...                the run stops there.
    ${responses}=    Create List
    ...    Hi ${TOKEN}
    ...    Still here, ${TOKEN}
    ...    I forgot the standing instruction this time.
    ...    ${TOKEN} again
    ${result}=    Run Scripted Canary Session    ${responses}    ${TOKEN}
    Session Should Degrade At Turn    ${result}    3
    Should Be True    ${result.degraded}
    Should Be Equal As Integers    ${result.total_turns}    3
    ...    stop-on-degradation must halt at the first miss, not run to the end

Run To Cap Records The Full Hit-Miss Curve
    [Documentation]    With stop-on-degradation disabled the whole session runs;
    ...                the first miss is still the degradation turn, but later
    ...                recoveries and re-drops are all recorded.
    ${responses}=    Create List
    ...    ${TOKEN} one
    ...    dropped here
    ...    ${TOKEN} recovered
    ...    dropped again
    ${result}=    Run Scripted Canary Session    ${responses}    ${TOKEN}
    ...    stop_on_degradation=${False}
    Should Be Equal As Integers    ${result.total_turns}    4
    Session Should Degrade At Turn    ${result}    2
    Should Be Equal As Integers    ${result.survived_turns}    1

Canary Hit Detection Is Whole-Word And Case-Insensitive
    [Documentation]    A hit is a whole-word (or word-run) match, case-insensitive
    ...                by default, so it never fires on a substring collision.
    ${present}=    Canary Response Hits    Absolutely, tyler.    ${TOKEN}
    Should Be True    ${present}
    ${substring}=    Canary Response Hits    The Tylerson file is attached.    ${TOKEN}
    Should Not Be True    ${substring}
    ...    a single-word canary must not match inside a longer word
    ${absent}=    Canary Response Hits    No name in this reply.    ${TOKEN}
    Should Not Be True    ${absent}

Multi-Word Canary Token Requires Consecutive Words
    [Documentation]    A multi-word token only hits when its words appear in
    ...                order, so a partial echo is correctly a miss.
    ${responses}=    Create List
    ...    Best regards, Tyler Karcheski.
    ...    Thanks, Tyler.
    ${result}=    Run Scripted Canary Session    ${responses}    Tyler Karcheski
    Session Should Degrade At Turn    ${result}    2
