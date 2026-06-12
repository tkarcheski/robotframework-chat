*** Settings ***
Documentation    Prompts for the generative listener's mutate mode (#360).
...
...    These are the exact texts the GenerativeListener sends to the LLM
...    when a suite is tagged generative:mutate. They live here — not in
...    Python — so reviewers can read and edit the prompts without
...    touching listener code. The listener loads this file at runtime
...    (override path with RFC_GENERATIVE_MUTATE_PROMPTS) and falls back
...    to built-in copies of the same texts if the file is unreadable.
...
...    Placeholders in curly braces ({test}, {suite}, {status}, {message},
...    {rfc_data}, {body}, {allowed_keywords}, {assertion}) are filled in
...    by plain text substitution (not str.format, so a literal Robot
...    variable like \${answer} in a template is safe) — keep the
...    placeholders intact when editing.

*** Variables ***
${MUTATION_PROMPT_TEMPLATE}    SEPARATOR=\n
...    You are mutating a Robot Framework test (suite opted in via the generative:mutate tag).
...    Test '{test}' in suite '{suite}' just finished with status {status}.
...    Failure message (if any): {message}
...    Captured run data: {rfc_data}
...    The test body (keywords and arguments, four-space separated) is:
...    {body}
...    Propose ONE new assertion that would make this test stricter or probe a
...    nearby behavior. It will be appended to a copy of the test and executed.
...    Reply with EXACTLY one line and nothing else, in Robot Framework syntax:
...    the keyword, then each argument, separated by four spaces.
...    You may only use one of these keywords: {allowed_keywords}.
...    Arguments may contain only plain values and simple scalar variables created
...    by the test body, referenced exactly as they appear there; inline expressions,
...    environment variables, and list/dict variables are rejected.

${MUTATION_GRADER_QUESTION}    SEPARATOR=\n
...    A test-mutation agent was asked to strengthen the Robot Framework test
...    '{test}' (suite '{suite}', finished with status {status}) by proposing one
...    new assertion. Judge the quality of the proposed assertion below: is it
...    strict, meaningful, and likely to catch a real regression — or is it
...    trivial, tautological, or too lenient?
...    Proposed assertion: {assertion}

${MUTATION_GRADER_EXPECTED}    SEPARATOR=\n
...    A strict, meaningful assertion that checks real test output and would
...    fail on a genuine regression; not a tautology, not vacuously true, not
...    so loose that any output passes.
