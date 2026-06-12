# External skill packs

Forked external skill repos, submoduled here and wired into Claude Code's
skill discovery by `scripts/sync_skill_packs.py`.

## The rules

- **Fork-first policy:** never submodule an upstream you don't control. Fork
  it under `tkarcheski/*`, submodule the fork. Upstream changes arrive only
  when we deliberately sync the fork and bump the pointer here — supply-chain
  changes are always a reviewed diff, never a surprise.
- **Ownership:** skill-pack submodules are owned by the **design** role
  (`ai/GIT.md` ownership table) — only `rfc-design-agent` commits pointer
  bumps; CI enforces this via `scripts/check_submodule_ownership.py`.
- **Discovery:** Claude Code only finds flat `.claude/skills/<name>/SKILL.md`
  dirs. The sync script materializes prefixed symlinks (e.g. `mp-tdd`) per
  `config/skill_packs.yaml`, honoring gitignore-style excludes in
  `.skillignore` (patterns match `<pack>/<category>/<name>`).
- **Collisions:** pack prefixes (`mp-`) prevent name clashes; if a real local
  skill dir somehow collides anyway, the local skill wins — the script never
  replaces a non-symlink.

## Adding a pack

1. Fork the upstream into `tkarcheski/<owner>-<repo>`.
2. `git submodule add git@github.com:tkarcheski/<fork>.git vendor/skill-packs/<pack>`
3. Add the pack to `config/skill_packs.yaml` (name, path, prefix, glob).
4. `uv run python scripts/sync_skill_packs.py` and commit the symlinks.

## Updating a pack

```bash
# sync the fork with upstream first (deliberate, reviewable):
gh repo sync tkarcheski/<fork> --source <owner>/<repo>
git submodule update --remote vendor/skill-packs/<pack>
uv run python scripts/sync_skill_packs.py   # re-links added/removed skills
# review the diff, then commit the pointer bump (design role only)
```

## Packs

| Pack | Fork | Upstream | Prefix |
|---|---|---|---|
| `mattpocock` | tkarcheski/mattpocock-skills | mattpocock/skills | `mp-` |
