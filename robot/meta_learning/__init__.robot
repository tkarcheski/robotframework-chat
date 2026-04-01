*** Settings ***
Name              Meta-Learning Probe Tests
Documentation     In-context skill retention test suite.
...
...               Tests whether an LLM can retain a skill taught in one turn
...               and correctly apply it after a distractor turn.

Resource          meta_learning.resource
Resource          ../resources/llm_setup.resource

Suite Setup       Verify LLM Available
Suite Teardown    Log    Finished Meta-Learning Test Suite

Force Tags        meta_learning    tier:2    verify:llm
