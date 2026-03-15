# Plan: Fix Superset Upload — Where Is The Data?

## Root Cause Analysis

**The data is going NOWHERE.** It's collected in memory during the test run, then silently discarded.

Here's the chain of failure:

1. **No `.env` file exists** on this machine (confirmed: `cat .env` → file not found)
2. **`DATABASE_URL` is empty** in the current environment (confirmed: `echo $DATABASE_URL` → blank)
3. When `DbListener.end_suite()` runs, it calls `TestDatabase()` with no URL
4. `TestDatabase.__init__` raises `RuntimeError("DATABASE_URL is not set...")`
5. **The exception is silently swallowed** at `db_listener.py:409-412`:
   ```python
   except Exception as e:
       error_msg = f"DbListener: FAILED to archive results: {e}"
       logger.warn(error_msg)
       logger.console(error_msg)
   ```
   The test run completes successfully. The data just... vanishes.

### Why previous fixes didn't help

The git history shows 8+ commits addressing symptoms, but never this root cause:

| Commit | What it did | Why it didn't help |
|--------|------------|-------------------|
| `8bd6fff` | Aligned POSTGRES_PASSWORD defaults | Password doesn't matter if DATABASE_URL is never set |
| `0ff5483` | Fixed host parsing in diagnostic tool | Diagnostics don't fix missing config |
| `c0f29b5` | Added post-run DB verification | Verification warns, but still says "skipping" when DATABASE_URL is unset |
| `5f4aecb` | Added `make robot-superset` connection tests | Tests can't pass if DB isn't configured |

### The cron script is also broken

`scripts/cron_run_local_models.sh` **never sources `.env`**. Even if `.env` existed, the hourly cron job wouldn't see `DATABASE_URL`. The Makefile does `-include .env` + `export`, so `make run-local-models` would work — but the cron script bypasses Make and calls `run_local_models.py` directly.

---

## The Fix (3 changes)

### 1. Fail loudly, not silently (`db_listener.py`)

The `DbListener` must **fail the suite** (or at minimum produce a highly visible
error) when it can't connect to the database. The current behavior of swallowing
the exception means test runs appear successful while silently losing all data.

**Change:** In `end_suite()`, when database write fails due to missing config,
raise a clear `RuntimeError` or log at `ERROR` level + set a suite message so
the Robot output shows the failure. Don't let a missing DATABASE_URL silently
drop data.

Also: In `start_suite()`, **eagerly validate** the database connection instead of
waiting until `end_suite()`. If DATABASE_URL is unset, fail immediately with a
clear message rather than running all tests and then losing the results.

### 2. Source `.env` in the cron script (`scripts/cron_run_local_models.sh`)

Add `.env` loading at the top of the cron script:

```bash
ENV_FILE="${REPO_DIR}/.env"
if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
fi
```

This ensures `DATABASE_URL` is available when the cron job runs
`run_local_models.py` outside of Make.

### 3. Early validation in `run_local_models.py`

The script already has post-run verification that warns when `DATABASE_URL` is
unset. But this warning comes AFTER tests run and data is lost. Move the check
to BEFORE the test loop begins, and make it a hard error (or at least a very
prominent warning with a y/N confirmation) so the user knows data won't be
archived.

---

## Summary

| # | File | Change | Why |
|---|------|--------|-----|
| 1 | `src/rfc/db_listener.py` | Eagerly validate DB in `start_suite()`; fail visibly on write error | Stop silently losing data |
| 2 | `scripts/cron_run_local_models.sh` | Source `.env` before running | Cron jobs need DATABASE_URL too |
| 3 | `scripts/run_local_models.py` | Pre-flight DATABASE_URL check before test loop | Don't run tests if data can't be saved |
