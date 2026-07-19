# Answer cache — verification re-run runbook

A Redis-backed memoization of `client.generate()` (issue #522). Re-running an
unchanged suite against an unchanged model serves the stored answer at ~0
compute instead of re-hitting the LLM — turning a multi-minute verification
loop into seconds.

> **Opt-in and skip-safe.** Nothing here runs by default. When enabled, only
> reproducible requests are cached, and an unreachable Redis is logged once and
> bypassed — it never fails a run (same contract as the Graylog sender).

## Four invariants

1. **Opt-in.** Wired in only when the run asks for it — `ANSWER_CACHE_ENABLED=1`
   or `RFC_RUN_MODE=verify`. Plain runs never touch Redis.
2. **Deterministic-only by default.** Even when enabled, a request is cached
   only if it is reproducible: `temperature == 0` **or** a `seed` is set.
   Non-deterministic requests legitimately differ per call and are skipped
   (override with `ANSWER_CACHE_NONDETERMINISTIC=1`).
3. **Provenance-recorded.** A cache hit stamps `cache_hit=True` on the served
   answer's `last_metrics`, with all token counts / durations zeroed — result
   rows stay honest about being replayed, and never fabricate usage.
4. **Never fails a run.** If Redis is unreachable the cache logs once, disables
   itself for the rest of the process, and degrades to a passthrough.

## Enabling it

```bash
# 1. Bring up Redis (publishes 127.0.0.1:6379 — loopback only; db 1 is ours).
docker compose up -d redis

# 2a. Enable directly…
export ANSWER_CACHE_ENABLED=1
# 2b. …or express run intent, which is clearer and safer (see the mode table):
export RFC_RUN_MODE=verify
```

Without a host-published Redis port the documented `REDIS_URL=redis://localhost:6379/1`
is unreachable from host-side `robot` runs and the cache silently latches to
passthrough — the compose service now binds `127.0.0.1:6379:6379` so this works
out of the box. Redis has no auth, so the bind is loopback-only by design.

## Run modes (`RFC_RUN_MODE`)

`RFC_RUN_MODE` gates the cache **above** `ANSWER_CACHE_ENABLED`, so a run's
intent — not a leftover shell export — decides whether answers are replayed.

| `RFC_RUN_MODE` | Effect | Use when |
|----------------|--------|----------|
| unset (default) | Honor `ANSWER_CACHE_ENABLED` | Normal runs |
| `verify` | Cache **forced ON** (deterministic-only gate still applies) | Re-running unchanged suites for a fast pass |
| `measure` | Cache **forced OFF** even if `ANSWER_CACHE_ENABLED=1` | Grading / measurement — protects against a stale replay |
| anything else | Warn once, fall back to unset behavior | — |

`measure` is the safety knob: a measurement run can never accidentally replay a
past answer just because the switch was left on in the shell.

## Invalidation

- **`rfc cache invalidate`.** The operator / CI affordance — bust by scope
  without hand-editing Redis (RFC-010 S4, #262). It reuses the version namespace
  as the bust lever:

  ```bash
  rfc cache invalidate                     # bust the current schema namespace
  rfc cache invalidate --version v2        # bust one specific namespace
  rfc cache invalidate --all               # flush every rfc:answer_cache:* key
  rfc cache invalidate --all --dry-run     # report the match count, delete nothing
  ```

  It honors `REDIS_URL` / `ANSWER_CACHE_*` like every other cache path. Unlike a
  run's cache reads/writes, an explicit invalidation is **loud on an outage**: an
  unreachable Redis exits non-zero rather than silently reporting "0 keys".
- **Version bump.** `ANSWER_CACHE_VERSION` (default `v2`) namespaces every key.
  Bump it to bust the entire cache on a schema or keying change: the new
  namespace starts empty and the old entries are orphaned (and TTL-expire on
  their own). To reclaim the orphaned old-namespace keys immediately, run
  `rfc cache invalidate --all` (or `--version <old>`, or a `FLUSHDB`) — the plain
  `rfc cache invalidate` busts only the *current* namespace (now the new, empty
  one), so it will not touch the orphans left under the previous version.
- **TTL.** `ANSWER_CACHE_TTL_SECONDS` (default `604800` = 7 days) expires
  entries automatically.
- **Flush.** `docker compose exec redis redis-cli -n 1 FLUSHDB` clears db 1.

## Key semantics

The key is the SHA-256 of a canonical JSON document over every output-affecting
attribute — provider type, prompt, model, `base_url`, `temperature`,
`max_tokens`, `seed`, `top_p`, `top_k`, `num_ctx`, `response_format` — plus the
version namespace. Omitting any output-affecting attribute would let two
genuinely different requests collide, so the key builder enumerates them
explicitly. A sibling change refines the model component from a mutable tag to
the immutable image digest so a re-pull of the *same* tag with different weights
does not serve a stale answer.

### Repo / prompt context (context-sensitive suites)

Most suites' prompts are self-contained, so their key needs no repo state. A
suite whose prompt **embeds repo state** — a pasted code snapshot, the current
commit, a versioned prompt template — is different: a code change must invalidate
that suite's own cached answers, or the cache replays an answer about the old
code. Such a suite opts in by setting `client.cache_context` to a fingerprint of
that state (for example the repo commit plus the prompt version) before calling
`generate()`; the fingerprint is folded into the key (RFC-010 S4, #262), so a
changed fingerprint is a miss, not a stale hit. The dimension is opt-in and
duck-typed like the model digest: a provider that never sets `cache_context`
keys exactly as before, so self-contained suites are unaffected.

### Why grader answers are cached too (one knob, not two)

The grader prompt **embeds the subject answer verbatim**. So a grader-call cache
hit is only possible when the subject answer was byte-identical — which for a
deterministic subject means the subject itself was a hit. The subject and its
grader therefore hit or miss together, which is why there is a single
`ANSWER_CACHE_ENABLED` knob rather than a separate grader switch: a
subject-only cache would be self-defeating (the expensive grader call would
re-run every time), and a grader-only cache is impossible (the embedded answer
keys it).

## Two-run speedup demo (live host)

```bash
export OLLAMA_ENDPOINT=http://<live-host>:11434
export DEFAULT_MODEL=qwen3:8b
docker compose up -d redis

# Run 1 — cold: each deterministic generate() hits the model and is stored.
time RFC_RUN_MODE=verify uv run robot -d results/verify-1 robot/10__tier1/math/tests/

# Run 2 — warm: identical requests replay from Redis at ~0 compute.
time RFC_RUN_MODE=verify uv run robot -d results/verify-2 robot/10__tier1/math/tests/
```

Run 2 should complete in a fraction of Run 1's wall-clock, and its result rows
carry `cache_hit=True`. In the monorepo, `run_local_models.py --verify` injects
`RFC_RUN_MODE=verify` into every launched `robot` subprocess; add `--dry-run` to
preview the mode without executing.
