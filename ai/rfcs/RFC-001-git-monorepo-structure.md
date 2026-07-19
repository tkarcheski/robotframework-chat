# RFC-001 — Monorepo Structure: Public Core + Private-by-Default Modules

- **Status:** Draft (for owner decision)
- **Tracking issue:** #545
- **Author:** design role
- **Date:** 2026-06-14

> **Note:** This is the public, sanitized summary of the design. Implementation
> specifics (exact repository inventory, host/deployment details, migration
> runbooks) are maintained in an internal document and intentionally omitted here.

---

## 1. Context

The project is currently spread across a primary repository plus several
satellite repositories wired in as Git submodules, with some auxiliary
repositories coordinated out of band. That topology creates day-to-day friction
(multi-step submodule pointer bumps, no atomic cross-cutting commits, duplicated
CI) and makes the boundary between the open-source harness and private
operational material harder to keep clean than it should be.

This RFC proposes consolidating into a **single monorepo** organized around one
clear idea: a **small, always-public core** plus **modules whose visibility is
declared per-module and defaults to private**.

### Goals

- One source-of-truth repository with atomic cross-cutting commits and one CI.
- A **minimal public core** — the open-source harness essentials, nothing more.
- **Private by default** — complexity, tooling, data, and personal artifacts live
  in modules that are private unless explicitly opted public.
- A boundary enforced **mechanically** (an allowlist + scanning), not by
  vigilance, so private material cannot leak into public artifacts by accident.

### Non-goals

- Re-architecting the Python/Robot test code itself.
- Selecting a build system (this is about repository topology).

---

## 2. Model — public core + modules (default private)

**Default visibility is private.** Something is public only if it is needed to
understand and run the core harness.

- **Core — always public.** The Robot Framework test suites and the Python that
  supports them, plus the minimum to run them (example configs, container build,
  license, a slim readme). This is the open-source project. The core must never
  depend on a module to run.
- **Modules — per-module visibility, default private.** Every other part is a
  self-contained module (e.g. test-result archives, monitoring logs, a knowledge
  base, session data, skills, agent/role tooling, operational scripts). Each
  module declares its own visibility; a new module is private until explicitly
  flagged public. A module may be published when it is genuinely reusable and
  contains nothing sensitive — but it never has to be.
- **Secrets** are never committed anywhere — environment files + a secret manager
  + a CI secret-scan gate — regardless of module visibility.

Why this shape:

- **Humans:** a small public core is easy to read, fork, and trust.
- **Tooling portability:** the public core must work for any consumer that can't
  load editor/agent-specific extensions; modules are additive, never required.
- **Focus:** a lean core keeps attention (and context) on the harness that
  matters rather than on operational scaffolding.

| Tier | What | Visibility |
|---|---|---|
| **Core** | Robot suites + supporting Python + run essentials | always public |
| **Modules** | data archives, monitoring, knowledge, sessions, skills, agent/role tooling, ops | per-module; **default private** |
| **Secrets** | credentials of any kind | never committed anywhere |

---

## 3. Recommended approach — private monorepo + automated public mirror

One private monorepo is the source of truth. CI publishes a curated subset — the
**core plus any module explicitly marked public** — to the public package.

### 3.1 Layout

```
repo/                     # private monorepo (source of truth; private by default)
├── core/                 # ALWAYS PUBLIC: robot suites + supporting python + run essentials
│   ├── robot/            #   the test suites
│   ├── src/…             #   the library that supports them
│   ├── config/*.example  #   example configs only
│   ├── Dockerfile        #   container build
│   ├── readme.md  LICENSE
│   └── .github/workflows/#   public CI for the core
├── modules/              # each module sets its OWN visibility; default private
│   └── <name>/module.toml#   visibility = "private" (default) | "public"; owner = <role>
└── .mirror/
    └── publish.sh        # publishes core/ + every module whose module.toml = public
```

Each module carries a small manifest:

```toml
# modules/<name>/module.toml
visibility = "private"   # default; set "public" to opt a clean, reusable module in
owner      = "<role>"    # owning role (drives CODEOWNERS)
```

**Submodule-backed modules use one convention.** When a module vendors an
external repository as a git submodule, mount the submodule at
`modules/<name>/upstream/` and keep the authoritative `modules/<name>/module.toml`
as a superproject-tracked file one level up. The manifest is then present in every
checkout — including a default clone with no submodules — so the generated
registry (`README.md` modules table + `CODEOWNERS`) is deterministic regardless of
submodule state. Never mount a submodule *as* the module directory, which would
bury `module.toml` inside the submodule where a no-submodule checkout cannot see
it. The registry generator ignores any `module.toml` found inside a submodule for
the same reason.

### 3.2 Boundary mechanics (safe by default)

- **Allowlist, not denylist.** The mirror publishes `core/` plus only modules
  whose manifest says `visibility = "public"`. A module with no manifest, or set
  to private, is never published. Adding a module is therefore default-safe;
  going public is an explicit, reviewable, per-module change.
- **Defense in depth before any publish:** (1) the publish set is derived only
  from the core + public manifests — abort on any stray path; (2) secret scan on
  the projected tree; (3) a check that the projected tree contains no private
  paths or internal references.
- **Projection, not history rewrite.** The public package is a filtered
  projection of the publish set, so private history never appears in it.

---

## 4. Contract impact

- **Keep:** the worktree-per-branch workflow, per-role commit identities, and the
  signed-off/model-attributed commit trailers.
- **Replace** the submodule-ownership check with `CODEOWNERS` generated from each
  module's manifest `owner`, plus the publish gates above.
- **Retire** the submodule session ritual and the second CI remote (the project
  is GitHub-only).

---

## 5. Migration (phased, reversible)

0. **Decide & freeze** the target shape and publication granularity.
1. **Build the monorepo skeleton** — move existing content into `core/` or
   `modules/<name>/` preserving history; add a default-private manifest per module.
2. **Stand up the mirror** — write the publish job; dry-run and diff the projection
   against today's public package to prove parity; wire the gates first.
3. **Cut over** — point checkouts/CI at the monorepo; make the public package
   mirror-only (pushes only from the publish job).
4. **Retire scaffolding** — submodule guard, second CI remote; add `CODEOWNERS`.

Until the final phase, the absorbed repositories remain as rollback.

---

## 6. Risks & mitigations (summary)

- *Mirror publishes something it shouldn't* → allowlist + secret scan +
  no-private-path gate, all before push.
- *Large clones* → data modules are partial-clone/sparse-checkout friendly; public
  contributors clone only the small mirrored core.
- *Ownership check weaker than expected* → pair CODEOWNERS with the existing
  commit-identity/trailer guard at the merge gate.

---

## 7. Open questions for the owner

1. How minimal is the public core (e.g. all suites public, or a curated subset)?
2. Public publication granularity: filtered history vs per-release snapshot.
3. Which modules (if any) start public.
4. One repo vs a simpler two-repo (public/private) split as a first step.
