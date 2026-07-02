---
name: skill-packs
description: >-
  rfc skill-pack sync mechanics: .skillignore fnmatch patterns match
  pack-relative identities (<pack>/<category>/<name>); bare names don't
  match nested paths; patterns like */personal/* are correct form.
domain: software/skills
sources:
  - "tkarcheski/robotframework-chat PR #448"
  - "scripts/sync_skill_packs.py (vendor/skill-packs worktree, 2026-06-12)"
last-verified: 2026-06-12
links: []
---

# rfc skill-pack sync

## .skillignore pattern matching

The rfc skill-pack sync script (`scripts/sync_skill_packs.py`) filters skills
using Python's `fnmatch` against a **pack-relative identity** of the form
`<pack>/<category>/<name>`.

- **Correct pattern form:** `*/personal/*` — matches any pack's `personal`
  category. Glob wildcards must span the full identity structure.
- **Incorrect pattern form:** `personal` — a bare name will NOT match nested
  identities like `mattpocock/personal/foo` because `fnmatch("mattpocock/personal/foo", "personal")` is `False`.
- The ignore file lives at `.skillignore` in the repo root (gitignore-style,
  `#` comments, blank lines ignored).

## How identities are built

```python
# From scripts/sync_skill_packs.py:
parts = rel.parts[-2:] if len(rel.parts) >= 2 else rel.parts
ident = "/".join((pack.name, *parts))  # e.g. "mattpocock/engineering/tdd"
```

Identity is always three segments: `<pack>/<category>/<name>`.

## Example .skillignore entries

```gitignore
# Exclude all personal skills from any pack
*/personal/*

# Exclude in-progress and deprecated from mattpocock pack
mattpocock/in-progress/*
mattpocock/deprecated/*
```

## Sync behaviour

- **Idempotent:** re-creates missing symlinks, prunes stale pack-owned ones.
- **Local skills win:** a real directory (non-symlink) at `.claude/skills/<name>` is never touched even if a pack would supply the same name.
- **Duplicate detection:** if two packs map to the same link name, the first wins and a `WARN:` is printed to stderr.
