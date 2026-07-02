# Graylog GELF integration (operator runbook)

Streams Robot Framework lifecycle events **and every LLM `generate()` call** to
Graylog over GELF-TCP, on two independent inputs with independent severity
thresholds. The code lives in the private submodule `modules/graylog`
(`rfc-graylog`); this page covers wiring it into the `core/` harness.

**Opt-in by design.** Nothing here runs by default: the submodule is absent from
the public/default install, and the LLM wrapper is gated behind
`GRAYLOG_LLM_ENABLED=1`. A missing package or an unreachable sink is logged and
skipped — it never fails a measurement run (same contract as the answer cache).

## Install

```bash
git submodule update --init modules/graylog
pip install -r core/requirements-graylog.txt   # -e ../modules/graylog
```

## Two channels

| Channel | Source | Default input | GELF facility |
|---------|--------|---------------|---------------|
| Robot lifecycle | `--listener robot_graylog_builtin.robot_graylog_builtin` | port 12201 | `robot-framework` |
| LLM calls | `--listener robot_graylog_llm.robot_graylog_llm` + provider wrapper | port 12202 | `rfc-llm` |

Each LLM event carries `model`, `provider`, `latency_ms`, `prompt_preview`,
`response_preview`, normalized token metrics (`prompt_tokens` / `completion_tokens`
/ `total_tokens`, from either Ollama or OpenAI keys), `suite` / `test` / `tags`
correlation, and `event_type=llm_call` (escalated to `ERROR` on failure).

## Environment

Shared fallbacks: `GRAYLOG_HOST` (`localhost`), `GRAYLOG_SOURCE` (hostname),
`GRAYLOG_TIMEOUT` (`5`).

Per-stream: `GRAYLOG_BUILTIN_{HOST,PORT,FACILITY,LEVEL}` (port `12201`,
`robot-framework`, `INFO`) and `GRAYLOG_LLM_{HOST,PORT,FACILITY,LEVEL}`
(port `12202`, `rfc-llm`, `INFO`).

`GRAYLOG_LLM_ENABLED=1` turns on the provider wrapper in
`rfc.llm_client.create_provider` so every harness `generate()` emits an event —
independent of the listeners (the wrapper no-ops if no listener/transport is
registered).

Level precedence per listener (highest first): listener arg
(`--listener robot_graylog_llm:level=DEBUG`) > Robot CLI var
(`--variable GRAYLOG_LLM_LEVEL:DEBUG`) > env var (`GRAYLOG_LLM_LEVEL`) >
default (`INFO`).

## Run

```bash
export GRAYLOG_HOST=graylog.example.com
make robot-graylog            # or: uv run python tasks.py robot-graylog
```

`make robot-graylog` registers both listeners alongside the default `LISTENER`
set, sets `GRAYLOG_LLM_ENABLED=1`, and writes output under `results/.../graylog/`.

## Implementation notes

- The provider wrapper is applied **outermost** in `create_provider`
  (`_maybe_wrap_with_graylog(_maybe_wrap_with_cache(client))`). `unwrap_provider`
  peels a single `__wrapped__` layer, so keeping graylog outside the cache lets
  `as_ollama` keep resolving the concrete client in every cache/graylog
  on/off combination.
- `GraylogProvider` forwards attributes via `__wrapped__` (so `unwrap_provider`
  and `as_ollama` work) but does **not** delegate `__class__`. With graylog
  enabled, a *direct* `isinstance(create_provider(...), OllamaClient)` is False —
  use `as_ollama()` / `unwrap_provider()` (as the harness already does)
  instead of bare isinstance.

## Multiple nodes

The stack is multi-node ready: host ports publish on `0.0.0.0`, the GELF inputs
bind `0.0.0.0` and are `global`, and the transport honors `GRAYLOG_HOST` (or the
per-stream `GRAYLOG_{BUILTIN,LLM}_HOST`). A remote runner just exports
`GRAYLOG_HOST=<server-ip>` (firewall open on `12201`/`12202`); set the server's
`GRAYLOG_HTTP_EXTERNAL_URI` to its reachable host so UI links resolve. Full setup
and a zero-dependency cross-node probe live in
[`modules/ops/graylog/README.md`](../../modules/ops/graylog/README.md).

## Smoke test (no Graylog server needed)

```bash
nc -lk 12201 >builtin.gelf &   nc -lk 12202 >llm.gelf &
GRAYLOG_HOST=localhost GRAYLOG_LLM_ENABLED=1 make robot-graylog
# inspect builtin.gelf / llm.gelf for NUL-framed JSON events
```
