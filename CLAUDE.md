# CLAUDE.md

<!-- Project memory for Claude Code. Every agent reads this first.
     Fill in the placeholders — the role agents depend on the commands section. -->

## Project

- **Name:** <project name>
- **What it does:** <one paragraph>
- **Stack:** <languages, frameworks, infra>
- **Default branch:** main

## Commands (agents run these — keep them accurate)

```bash
# install:   <e.g. npm ci>
# build:     <e.g. npm run build>
# test:      <e.g. npm test>
# lint:      <e.g. npm run lint>
# typecheck: <e.g. npm run typecheck>
# run dev:   <e.g. npm run dev>
```

## Conventions

- Code style: <link to style guide or 3–5 bullet rules>
- Commit messages: <e.g. conventional commits>
- Branch naming: `<type>/<issue-number>-<slug>` (see ai/AGENTS.md)
- Tests live in: <path>; test plans live in: `ai/test-plans/`; RFCs in: `ai/rfcs/`

## Monitoring & dashboards (project-management reads these)

- CI: GitHub Actions (`gh run list`)
- <other dashboards / alert sources, with URLs or commands>

## Role system

This repo runs a four-role agent system defined in **`ai/AGENTS.md`** — read it
before acting. Roles live in `.claude/agents/`:

- `engineering` — loop: `status:ready` issues → pull requests
- `test-design` — loop: PRs → test plans → runs → verdicts + issues
- `project-management` — loop: triage → prioritize → quality review → monitoring
- `design` — open-ended: full-system awareness, RFCs, system-wide improvements

Start a role session with: `claude --agent <role>` (or `@<role>` in-session).

## Hard project rules

- <anything Claude must never do in this repo: e.g. never touch migrations,
  never commit secrets, never push to main directly>
