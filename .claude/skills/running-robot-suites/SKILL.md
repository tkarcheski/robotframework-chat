---
name: running-robot-suites
description: >-
  How to run real Robot Framework suites in robotframework-chat and where output
  lands: the 5-tuple watermark (rfc_version, model/harness, suite, hostname,
  session_id), when you are the agent harness vs when the LLM under test is the
  model, the MODEL_HARNESS vs DEFAULT_MODEL distinction, terminal vs web session
  constraints, and committing output.xml.
when_to_use: >-
  Trigger when the user asks to run a robot suite (robot-math, robot-safety,
  robot-agentic-coding, etc.), to produce "real results", or when a change
  touches agent behaviour and a suite run is warranted (Issue #350).
---

# Running Robot suites yourself (Issue #350)

Every Robot run is keyed by a **5-tuple watermark** stamped into both
`output.xml` (`--metadata`) and the `test_runs` table:

| Slot           | Source                                              | Path component |
|----------------|-----------------------------------------------------|----------------|
| `rfc_version`  | `from rfc import __version__`                       | 1              |
| `default_model` (LLM suites) **or** `model_harness` (agent suites) | `.env` `DEFAULT_MODEL` / shell `MODEL_HARNESS` | 2 |
| `test_suite`   | Make target                                         | 3              |
| `hostname`     | `$(shell hostname)`                                 | 4              |
| `session_id`   | Fresh UUID per `make` invocation                    | 5              |

Output goes to
`results/<rfc_version>/<model_or_harness>/<test_suite>/<hostname>/<session_id>/`.

## When to run real tests

**You are running from a terminal (Claude Code CLI):** you have shell access, so
for agent suites (`robot-agentic-coding`, `robot-agentic-injection`) **you are
the harness**. After making changes that touch agent behaviour:

1. Identify your own model id (it appears in the session system prompt — e.g.
   `claude-opus-4-7[1m]`).
2. Run the agent suite with `MODEL_HARNESS` set, so the path and DB row record
   that you drove the test:

   ```bash
   MODEL_HARNESS='claude-opus-4-7[1m]' make robot-agentic-coding
   ```

3. Verify the output landed under
   `results/$(VERSION)/<sanitized-harness>/agentic_coding/<host>/<session>/` and
   commit the `output.xml` (HTML stays gitignored).

For LLM suites (`robot-math`, `robot-safety`, etc.) the model under test is the
LLM at `OLLAMA_ENDPOINT`, not you. Run with `DEFAULT_MODEL` already in `.env`:

```bash
make robot-math
```

**You are running from the web (claude.ai):** you have no shell access. Don't
attempt to run robot suites — just produce the code changes and ask the user to
run them locally. State this constraint in your PR description so the reviewer
knows the run is deferred.

## Wiring (already in place)

- `Makefile` exports `SESSION_ID`, `MODEL_HARNESS`, `HOSTNAME` and passes
  `--metadata` + `--variable` flags to every robot run.
- `rfc.db_listener.DbListener` reads `${SESSION_ID}` and `${MODEL_HARNESS}`
  Robot variables and writes them to `test_runs.session_id` /
  `test_runs.model_harness`.
- `tests/test_test_database_migration.py` covers fresh + pre-migration upgrades
  for both columns.
