# RFC-001 — Git Monorepo Structure: Public/Private Boundaries & Layout

- **Status:** Draft (for owner decision)
- **Tracking issue:** tkarcheski/robotframework-chat#545 (sanitized; this RFC kept internal — see §2 on why the detailed version must not be published to the public repo)
- **Author:** design role (rfc-design-agent)
- **Date:** 2026-06-14
- **Supersedes/affects:** `ai/GIT.md` (submodule ownership), `.gitmodules`, the
  dual GitHub/GitLab remote setup, `Makefile` `superset-export`/`update` targets
- **Decision owner:** repo owner (human)

---

## 1. Context — why this RFC exists

What presents as "the rfc repo" is actually a **constellation of eight Git
repositories** stitched together by submodules and out-of-band conventions. The
current shape grew organically and now has a structural contradiction (a public
repo depending on private submodules) plus real day-to-day friction (submodule
bumps, cross-repo atomicity, attribution complexity). This RFC proposes a
**monorepo** consolidation and — the part the owner specifically asked for — a
crisp, enforced **public/private boundary**.

### 1.1 The current constellation (verified 2026-06-14)

| Repo | Role | Visibility | Wired in as |
|---|---|:---:|---|
| `robotframework-chat` | Core test harness (Python + Robot) | **PUBLIC** | root |
| `robotframework-chat-results` | Archived run output (LFS) | **PRIVATE** | submodule `results/` |
| `rfc-monitor-logs` | Agent monitoring/listener logs | **PRIVATE** | submodule `monitoring/logs/` |
| `knowledge` | Personal knowledge base ("brain") | **PRIVATE** | submodule `knowledge/` |
| `elons-algorithm` | A single Claude skill | **PUBLIC** | submodule `.claude/skills/elons-algorithm/` |
| `mattpocock-skills` | Vendored 3rd-party skill pack | **PUBLIC** | submodule `vendor/skill-packs/mattpocock/` |
| `claude-sessions` | Transcript-mining pipeline (cc-ingest → Postgres → Superset) | **PRIVATE** | *not* a submodule (standalone) |
| `backups` (Superset export target) | Dashboard ZIPs + DB dumps | **PRIVATE** | *not* a submodule (`make superset-export` pushes here) |

Additionally the core repo is **dual-pushed** to GitHub (dev) *and* GitLab
(live) — `.gitlab-ci.yml` + `.github/` both exist — and runs as **two
checkouts**: `/home/tyler/AI/github/rfc` (dev) and
`/home/tyler/AI/robotframework-chat` (live, cron-driven).

### 1.2 Problems with the status quo

1. **Public repo, private submodules = broken clone + information leak.**
   `robotframework-chat` is PUBLIC but its tracked `.gitmodules` names PRIVATE
   repos (`results`, `monitoring/logs`, `knowledge`). A public cloner:
   - cannot `git submodule update` those paths (auth fails → broken setup), and
   - can read the **existence and URLs** of the private repos from `.gitmodules`
     and the private SHAs from history.
   This is the central defect. *(This same session hit the downstream symptom: a
   public-checkout `submodule update` only succeeds because the operator has
   private access.)*
2. **Submodule friction.** Every results/log/knowledge change is a two-step
   commit (commit inside submodule → bump pointer in parent), routinely
   producing "dirty submodule / new commits" noise and the ownership-guard
   violations seen in the test-loop ledger (engineering bumping the
   test-design-owned `results` pointer).
3. **No cross-cutting atomicity.** A change that touches harness code *and* its
   archived results *and* a listener log cannot be one reviewable commit/PR.
4. **Dual-remote drift.** GitHub and GitLab can diverge; CI is duplicated
   (`.github/workflows` + `.gitlab-ci.yml`); the live cron checkout silently
   commits audits (observed: `a79bddf`/`1bf8e9f`).
5. **LFS inside a submodule** (`results`) compounds clone cost and auth.
6. **Attribution machinery is heavy** because ownership is *per-repo*; it must
   be reconstructed from commit identities + a CI guard (`ai/GIT.md`).

### 1.3 Goals & non-goals

**Goals**
- One **source-of-truth repo** with atomic cross-cutting commits and one CI.
- A **mechanically enforced** public/private boundary — private data can never
  leak into anything world-readable, by construction not by vigilance.
- Preserve a genuine **public open-source face** for the harness (the Apache
  `LICENSE` stays meaningful).
- Keep the **worktree + per-role identity** model (it works); replace only the
  *submodule-ownership* half of the contract.

**Non-goals**
- Re-architecting the Python/Robot code itself.
- Choosing a build system (Bazel/Nx) — this is about repo topology, not build.
- Forcing GitLab away if the live deployment still needs it (addressed in §6).

---

## 2. The public/private classification (the core of the design)

Public/private is the **primary partition axis**. Every path lands in exactly
one tier. The litmus test: *"if a stranger read this, is anything leaked —
secrets, internal infrastructure, personal notes, raw transcripts, host names,
or model-performance data we don't want public?"*

| Tier | Contains | Examples (current paths) | Rule |
|---|---|---|---|
| **PUBLIC** | The harness as an OSS project | `src/rfc/`, `robot/`, `config/*.example`, `Makefile`, `Dockerfile*`, `docs/`, `ai/*.md` (contracts/RFCs), `.claude/skills/*` (first-party generic skills), `vendor/skill-packs/*` (already-public 3rd-party), `LICENSE`, `readme.md` | World-readable. Zero secrets, zero host identities, zero personal data. |
| **PRIVATE** | Operational data, identity, and personal artifacts | `results/` (run output + LFS), `monitoring/logs/`, `knowledge/`, transcripts (`claude-sessions`), `backups/`, `.env`, `host-config.toml`, `ci_metadata.json`, `*.audit-run-*.log`, real `local_models.yaml` host lists | Never world-readable. Lives only in the private remote. |
| **SECRET** (sub-tier of private) | Credentials | API keys, DB passwords, Superset secret key, SSH-bearing remotes | Never committed *anywhere*, even private. `.env`-only + secret manager; CI secret-scan gate. |

Notable reclassifications this forces:
- `elons-algorithm` is currently a PUBLIC submodule but is just a skill — it
  belongs in PUBLIC `.claude/skills/` as plain directories (no submodule).
- `host-config.toml` (real host list) is PRIVATE; only `host-config.toml.example`
  is PUBLIC. Same for `.env`/`.env.example` (already correct).
- `results/` model-vs-suite pass rates are **PRIVATE by default** — publishing
  model performance is a deliberate choice, not a leak; keep it private until
  the owner opts specific aggregates in.

---

## 3. Recommended approach — **Private monorepo + automated public mirror**

> One private monorepo is the source of truth. A CI job continuously publishes a
> curated, allowlisted subset to the existing PUBLIC `robotframework-chat` repo.

This is the recommendation because it is the only option that gets **both**
monorepo developer experience (atomic commits, one CI, no submodules) **and** a
clean public face **and** a leak-proof boundary (the public repo only ever
*receives* an allowlisted projection — private content has no path to it).

### 3.1 Target repository layout (the private monorepo)

```
rfc/                                   # single private monorepo (source of truth)
├── LICENSE  readme.md  Makefile
├── pyproject.toml  uv.lock(gitignored)
├── public/                            # ── EVERYTHING here is mirrored public ──
│   ├── src/rfc/                       # harness code
│   ├── robot/                         # Robot suites
│   ├── config/                        # *.example only (no real host lists)
│   ├── docs/                          # user-facing docs
│   ├── ai/                            # agents.md, ROLES.md, GIT.md, rfcs/, testing.md …
│   ├── skills/                        # first-party + vendored public skills
│   │   ├── elons-algorithm/           # de-submoduled
│   │   └── vendor/mattpocock/         # de-submoduled (3rd-party, public)
│   ├── Dockerfile  Dockerfile.ci  docker-compose.yml
│   └── .github/workflows/             # public CI (mirrored)
├── private/                           # ── NEVER mirrored ──
│   ├── results/                       # LFS run output (was a submodule)
│   ├── monitoring/logs/               # listener/monitor logs
│   ├── knowledge/                     # personal brain
│   ├── sessions/                      # claude-sessions pipeline + data
│   ├── backups/                       # Superset dashboard ZIPs + DB dumps
│   ├── hosts/host-config.toml         # real fleet config
│   └── ops/                           # cron scripts, live-deploy, .env.real (gitignored)
└── .mirror/
    ├── allowlist.txt                  # exact paths/globs that may go public
    └── publish.sh                     # subtree/filter-repo projection job
```

The single hard rule that makes the boundary mechanical:

> **`public/` is the *only* thing the mirror job copies. The publisher operates
> on an allowlist (`public/**`), never a denylist.** Adding a private file is the
> default-safe action; a file is public only by being placed under `public/` *and*
> matching `.mirror/allowlist.txt`. Two independent gates (location + allowlist)
> must both pass.

### 3.2 How the public mirror is produced & kept clean

- **Projection, not history rewrite.** On merge to the private default branch, CI
  runs `.mirror/publish.sh`, which uses `git subtree split --prefix=public` (or
  `git filter-repo --path public/`) to produce a tree containing only `public/`,
  then force-pushes that to `robotframework-chat` (the existing PUBLIC repo).
  The public repo's root becomes the contents of `public/` (the `public/` prefix
  is stripped so the OSS layout looks normal).
- **Three CI gates before any publish** (defense in depth):
  1. **Allowlist gate** — abort if the projected tree contains any path not
     matching `.mirror/allowlist.txt`.
  2. **Secret scan** — `gitleaks`/`trufflehog` on the projected tree; any hit
     aborts.
  3. **No-private-ref gate** — assert the projected tree references no `private/`
     path, no real host name, no internal email except the `@agents.rfc` role
     identities that are already public by design.
- **History hygiene.** The public repo is a *projection*; its history is the
  filtered history of `public/`. Private commits never appear. (If full public
  commit history isn't required, the simplest leak-proof variant is a
  **squashed snapshot per release** — even less surface area.)

### 3.3 Why not the alternatives

| Option | Verdict | Why |
|---|---|---|
| **Public monorepo + private overlay** (private repos cloned into gitignored paths at runtime) | Rejected | Keeps submodule-like coordination pain; one fat-fingered `git add` leaks private data into the public root. Boundary is a denylist — unsafe by default. |
| **Two repos by trust boundary** (`rfc-public` + `rfc-private`) | Viable fallback | Consolidates 8→2 and is dead simple, but loses cross-boundary atomicity (a harness+results change is still two PRs). Good "phase 0" if mirror tooling is deemed too much. |
| **Keep submodules, just fix visibility** (make core private) | Rejected | Abandons the public OSS face entirely and keeps every submodule pain point. |
| **Single public monorepo, delete all private data from git** | Rejected | Loses the archived results/knowledge/sessions that the analytics stack depends on. |

---

## 4. Impact on `ai/GIT.md` (the role git contract)

The monorepo **keeps** the parts that work and **removes** the submodule
machinery:

- **Keep:** worktree-per-branch, the lease protocol, per-role `--worktree`
  identities, the `Signed-off-by` + `Model` trailers, and
  `check_agent_signoffs.py`.
- **Replace submodule ownership → `CODEOWNERS`.** Today "who may bump `results`"
  is a per-repo rule enforced by `check_submodule_ownership.py`. In a monorepo it
  becomes a path rule:
  ```
  /private/results/        @rfc-test-design
  /private/monitoring/     @rfc-project-management
  /public/skills/elons-algorithm/  @rfc-design
  /public/src/rfc/         @rfc-engineering
  ```
  CODEOWNERS + a "changed-paths vs committer-role" CI check replaces the
  submodule guard with a stronger, finer-grained equivalent. `check_submodule_*`
  is retired.
- **New gate:** the §3.2 allowlist/secret/no-private-ref publish gates become
  part of CI and are documented in `ai/GIT.md` as the boundary contract.
- **Submodule session ritual deleted** (`submodule update --init` etc. — no
  longer applicable).

---

## 5. Migration plan (phased, reversible)

**Phase 0 — Decide & freeze (owner).** Approve target shape; pick "full filtered
history" vs "squashed snapshot" for the public mirror; decide GitLab's fate (§6).

**Phase 1 — Build the private monorepo skeleton.** Create the private repo;
`git subtree add`/`filter-repo` each existing repo into its target path
(`public/…` or `private/…`) **preserving history**. Verify LFS migrates for
`results`. Move `elons-algorithm`/`mattpocock` to `public/skills/` as plain dirs.

**Phase 2 — Stand up the mirror.** Write `.mirror/allowlist.txt` + `publish.sh`;
dry-run the projection; manually diff the projected tree against today's public
`robotframework-chat` to prove parity. Wire the three CI gates **before** the
first real push.

**Phase 3 — Cut over.** Point the live/dev checkouts and crons at the monorepo;
flip `robotframework-chat` to mirror-only (branch protection: pushes allowed only
from the mirror bot). Archive the now-absorbed private repos (don't delete —
keep read-only for 1 release as rollback).

**Phase 4 — Retire scaffolding.** Update `ai/GIT.md`, delete `.gitmodules` +
submodule guards, fold dual CI into one, update the `rfc-worktree` skill.

**Rollback:** until Phase 4, the absorbed repos still exist; revert by un-pointing
the crons and re-enabling the old submodule wiring.

---

## 6. GitLab / live deployment

The dual GitHub+GitLab setup is orthogonal to public/private but should be
resolved in the same pass:

- **Recommended:** make the **private monorepo** the source of truth on GitHub;
  if GitLab is still needed for the live runner/registry, treat it as a **second
  mirror target** (push `private/`-inclusive to a private GitLab mirror), not a
  second source of truth. One source, N mirrors (public GitHub OSS, optional
  private GitLab live).
- This kills the dual-remote drift and the silent cron-commit problem (the live
  checkout becomes mirror-only / read-mostly, fed by CI rather than committing
  audits back into a shared branch).

---

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Mirror job leaks a private file | Allowlist (not denylist) + secret scan + no-private-ref gate, all *before* push; squashed-snapshot option shrinks surface further. |
| History rewrite breaks public forks/stars | Public repo keeps its name/URL; only internal layout shifts. Communicate once; or use squashed snapshots so external history was never guaranteed. |
| LFS migration corrupts results | Phase 1 migrates LFS in isolation with checksums before cutover; old `…-results` repo retained as rollback. |
| Monorepo clone gets heavy (LFS + knowledge + sessions) | `private/` is LFS/partial-clone friendly; contributors to PUBLIC work clone only the mirrored public repo (small). Sparse-checkout for operators. |
| CODEOWNERS check weaker than people think | Pair it with the existing identity/trailer guard; both must pass at the merge gate. |

---

## 8. Open questions for the owner

1. **Public mirror history:** full filtered history of `public/`, or squashed
   snapshot per release? (Squashed = smallest leak surface, loses public commit
   granularity.)
2. **Results visibility:** keep all model-performance data PRIVATE, or publish
   opt-in aggregates (e.g. a sanitized coverage matrix) to the public repo?
3. **GitLab:** still required for the live deployment, or can the live runner move
   to GitHub Actions and retire GitLab entirely?
4. **Sessions & knowledge in the monorepo:** absorb `claude-sessions` and
   `knowledge` into `private/`, or keep them as separate private repos? (They're
   the most sensitive; some owners prefer them physically separate.)
5. **One repo or two:** commit to the full mirror tooling (§3), or start with the
   simpler `rfc-public` + `rfc-private` two-repo split (§3.3 fallback) and add
   mirroring later?

---

## 9. Owner decisions (locked 2026-06-14)

The owner reviewed §8 and resolved all five questions. This section is the
decision of record for issue #545.

| §8 | Question | Decision |
|---|---|---|
| 1 | Public mirror history | **Full filtered history of `public/`** (not squashed). |
| 2 | Results visibility | **Keep all model-performance data PRIVATE**; opt-in sanitized aggregates may be published later as a deliberate choice. |
| 3 | GitLab | **Retire.** Move the live runner matrix to GitHub Actions and drop GitLab + the sync workflows entirely. |
| 4 | Sessions & knowledge | **Keep as separate private repos.** Do not absorb `claude-sessions`/`knowledge` into the monorepo (most sensitive; physical separation preferred). |
| 5 | One repo or two | **Two-repo split first** (§3.3 fallback): build the private monorepo + sanitize the public repo now; defer the automated per-merge mirror tooling (§3.2) until the manual projection is proven. |

### 9.1 Operational facts that shape the migration

- **GitHub Actions CI is already self-hosted on `ai1`.** The self-hosted-runner
  capability the GitLab matrix (`ai1/mini1/mini2/dev1/dev2`) relies on already
  exists on the GitHub side, so retiring GitLab (§5 Phase 4) is *extending* the
  existing GitHub self-hosted setup to the remaining nodes, not standing one up
  from scratch. Monitoring corollary: if a pushed pipeline does not appear to
  run, suspect the `ai1` runner first, not a missing trigger.
- **De-submoduling and the ownership guard are coupled.**
  `scripts/check_submodule_ownership.py` runs on every PR (`robot-tests.yml`),
  diffing submodule-pointer bumps. Removing the `results`/`monitoring/logs`/
  `knowledge` submodules must happen in the **same** change that retires that
  guard — they cannot be cleanly separated across phases. The actual public
  `.gitmodules` sanitization is therefore sequenced into the phase where
  `rfc-private` already holds the data *and* the guard comes out together
  (Phase 1/3 boundary), not as an isolated early step.

---

## Appendix A — One-screen summary

- **Problem:** public core repo declares private submodules → broken clones +
  leak; 8-repo sprawl; submodule friction; dual-remote drift.
- **Proposal:** one **private monorepo** (`public/` + `private/`), with CI that
  **mirrors only `public/`** to the existing public `robotframework-chat`.
- **Boundary:** allowlist-based (safe by default) + secret scan + no-private-ref
  gate. Private is the default; public is opt-in by location *and* allowlist.
- **Contract change:** submodule-ownership guard → `CODEOWNERS`; keep worktrees,
  identities, sign-off/Model trailers.
- **Decision needed:** mirror history style, results visibility, GitLab's fate,
  whether sessions/knowledge get absorbed, and one-repo-vs-two.
