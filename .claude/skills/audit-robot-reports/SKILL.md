---
name: audit-robot-reports
description: >-
  Use when auditing Robot Framework coverage from `make run-local-models` in the
  rfc repo (robotframework-chat) — i.e. answering "which models have been tested
  against which suites?". Builds a model × test-suite coverage matrix for the
  latest rfc version, writes a markdown report to `.claude/audits/`, and commits
  the latest results (the `results/` submodule is LFS-tracked). Also the entry
  point for launching the multi-hour `make run-local-models` run detached and
  doing status check-ins. Trigger whenever the user says "audit the robot
  reports", "check model/suite coverage", "run the local models and audit",
  "what models have we tested", "regenerate the coverage report", or points at
  run-local-models output — even if they don't say the word "audit".
---

# audit-robot-reports

## What this is

`make run-local-models` runs every suite in `config/local_models.yaml` against
every model discovered on the local Ollama fleet, writing one `output.xml` per
(model, suite, host, session) under the `results/` submodule. After enough runs
pile up the useful question is **coverage**: which models have actually been
measured against which suites for the current rfc version, and where are the
gaps?

This skill answers that. The real parsing/matrix/markdown logic lives in
`scripts/audit_robot_reports.py` (tested, type-hinted) so the Makefile pipeline
and this skill call the same code. Your job here is orchestration: figure out
where the (multi-hour) run stands, drive it, and produce + commit the report.

The audit is **also wired into the pipeline**: `make run-local-models` runs the
audit and commits automatically after its first iteration. `make
run-local-models AUDIT=0` disables that. So this skill is mostly for *manual*
audits and for babysitting a detached run.

## Step 1 — Confirm context

```bash
git -C "$PWD" rev-parse --show-toplevel   # should end in /rfc
python -c "import sys; sys.path.insert(0,'src'); from rfc import __version__; print(__version__)"
```

The version is the audit target (the latest version with watermarked results is
used if you don't pass `--version`). If you're not in the rfc repo, stop.

## Step 2 — Ask where the run stands

`make run-local-models` can take **hours** and needs the live Ollama fleet, so
never just launch it blind. Ask the user (multiple choice, per CLAUDE.md):

> Where does the run-local-models run stand?
> a) Not started — launch it detached and give me a status command
> b) Already running — show me current progress
> c) Done (or recent enough) — audit + commit now
> d) Audit whatever's on disk right now, regardless

Branch on the answer:

### (a) Launch detached

The run must outlive this session, so detach it and tee to a logfile. Audit +
commit happen automatically after the first iteration (built into the pipeline):

```bash
TS=$(date +%Y%m%d-%H%M%S)
LOG="results/.audit-run-${TS}.log"   # ignored: results/ is a submodule
nohup make run-local-models > "$LOG" 2>&1 &
echo "Launched. PID $!  •  log: $LOG"
echo "Status:  tail -f $LOG   |   re-invoke this skill and pick (b)"
```

Then **stop** — do not block waiting for hours. Tell the user the log path and
that re-invoking the skill with option (b) will summarise progress.

### (b) Status check-in

Summarise progress from the newest logfile and the results on disk. Do NOT
re-run the audit yet (the run is still writing):

```bash
LOG=$(ls -t results/.audit-run-*.log 2>/dev/null | head -1)
pgrep -af run_local_models.py || echo "run-local-models process not found (finished or not started)"
tail -n 20 "$LOG"
# how many (model,suite) cells have landed for the latest version so far:
uv run python scripts/audit_robot_reports.py --audit-dir /tmp/audit-peek
```

Report: is the process alive, what iteration/model it's on (from the log), and
the partial coverage count. The `/tmp/audit-peek` write is a throwaway preview —
don't commit it.

### (c) / (d) Audit + commit

```bash
uv run python scripts/audit_robot_reports.py --commit
```

This writes `.claude/audits/<date>-v<version>-coverage.md` and commits the
latest results + report. See § Committing below for what `--commit` does with
the submodule. For (d) without committing, drop `--commit`.

## Step 3 — Read and relay the report

The script prints a one-line summary (models × suites, cells covered, fleet
models with no data). Open the written report and relay the headline to the
user: how many cells are covered, which suites no model has run, and which fleet
models are missing entirely. The report itself has the full matrix.

Cell legend: ✅ ran & ≥50% pass · ⚠️ ran & <50% pass · 🛑 ran but 0 tests ·
⬜ not run. A model is "complete" when it has ≥1 run for every configured suite.

## Committing (submodule-aware)

`results/` is a **submodule** (`github.com/tkarcheski/robotframework-chat-results`)
and its `output.xml` files are **LFS-tracked**. `--commit` therefore does a
two-repo commit, in this order (so the parent never points at a SHA the remote
lacks):

1. In `results/`: `git add <version>` → commit → **push** the submodule.
2. In the superproject: stage the submodule pointer bump + the new report, then
   commit `chore: audit robot coverage for v<version>`.

`scripts/audit_robot_reports.py::commit_audit` handles this and falls back to a
plain `git add results` commit if `results/` ever stops being a submodule.

## Common pitfalls

- **LFS pointers, not content.** A fresh `git clone --recurse-submodules` (or a
  bare `git submodule update --init`) leaves `results/**/output.xml` as LFS
  *pointer* files until you run `git -C results lfs pull`. The audit parser
  detects pointers and skips them, so an un-pulled tree looks like "no results".
  If coverage is mysteriously empty, run `git -C results lfs pull` first.
- **Don't block on the run.** It's hours long. Launch detached (option a) and
  return; never hold the session open polling.
- **`make run-local-models` auto-commits** (after iteration 1) to whatever
  branch is checked out, pushing the submodule. That's intended for unattended
  runs — but tell the user if they're on a branch they didn't expect to commit
  to. Use `AUDIT=0` to suppress it.
- **Latest version may have no data.** The audit targets the highest PEP 440
  version *with watermarked results*. dryrun outputs carry no watermark and are
  correctly ignored — so right after a version bump the matrix can be empty
  until run-local-models has run for it.
- **Don't hand-edit the report.** Regenerate it from the script so it stays in
  sync with the results on disk.
