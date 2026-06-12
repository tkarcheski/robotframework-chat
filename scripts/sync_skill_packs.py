#!/usr/bin/env python3
"""Sync external skill packs into .claude/skills/ as prefixed symlinks.

External skill repos are forked under tkarcheski/* (fork-first policy, see
ai/GIT.md) and submoduled at vendor/skill-packs/<pack>. Their layouts are
arbitrary (e.g. skills/<category>/<name>/SKILL.md), while Claude Code only
discovers flat .claude/skills/<name>/SKILL.md dirs — this script bridges the
two:

  config/skill_packs.yaml   which packs exist, their prefix and skill glob
  .skillignore              gitignore-style excludes, matched against the
                            pack-relative identity <pack>/<category>/<name>
  .claude/skills/<prefix><name>  relative symlink into the pack (committed)

Run after `git submodule update --remote vendor/skill-packs/<pack>` or after
editing the manifest/.skillignore. Idempotent: re-creates missing links,
prunes links it owns that are no longer planned, and never touches real
(non-symlink) skill directories.

Usage:
  uv run python scripts/sync_skill_packs.py            # sync
  uv run python scripts/sync_skill_packs.py --dry-run  # show the plan only
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

import yaml

MANIFEST = Path("config/skill_packs.yaml")
SKILLIGNORE = Path(".skillignore")
SKILLS_DIR = Path(".claude/skills")


@dataclass(frozen=True)
class SkillPack:
    name: str
    path: str
    prefix: str
    glob: str


@dataclass(frozen=True)
class Skill:
    name: str  # directory name, e.g. "tdd"
    ident: str  # pack-relative identity, e.g. "mattpocock/engineering/tdd"
    dir: Path  # absolute path to the skill directory


def load_manifest(path: Path) -> list[SkillPack]:
    data = yaml.safe_load(path.read_text())
    return [
        SkillPack(name=p["name"], path=p["path"], prefix=p["prefix"], glob=p["glob"])
        for p in data.get("packs", [])
    ]


def load_ignore_patterns(path: Path) -> list[str]:
    if not path.exists():
        return []
    patterns: list[str] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def is_ignored(ident: str, patterns: list[str]) -> bool:
    return any(fnmatch(ident, pat) for pat in patterns)


def discover_skills(repo_root: Path, pack: SkillPack) -> list[Skill]:
    pack_root = repo_root / pack.path
    skills: list[Skill] = []
    for skill_md in sorted(pack_root.glob(pack.glob)):
        skill_dir = skill_md.parent
        rel = skill_dir.relative_to(pack_root)
        # identity drops the leading layout dir (e.g. "skills/") down to
        # <category>/<name> so .skillignore patterns stay layout-agnostic
        parts = rel.parts[-2:] if len(rel.parts) >= 2 else rel.parts
        ident = "/".join((pack.name, *parts))
        skills.append(Skill(name=skill_dir.name, ident=ident, dir=skill_dir))
    return skills


def plan_links(
    repo_root: Path, packs: list[SkillPack], patterns: list[str]
) -> dict[str, Path]:
    """Map of link name → symlink target relative to .claude/skills/."""
    links: dict[str, Path] = {}
    skills_dir = repo_root / SKILLS_DIR
    for pack in packs:
        for skill in discover_skills(repo_root, pack):
            if is_ignored(skill.ident, patterns):
                continue
            link_name = f"{pack.prefix}{skill.name}"
            if link_name in links:
                print(
                    f"WARN: duplicate skill name '{link_name}' ({skill.ident} skipped)",
                    file=sys.stderr,
                )
                continue
            rel_target = Path(
                *[".."] * len(SKILLS_DIR.parts),
                *skill.dir.relative_to(repo_root).parts,
            )
            # equivalent to os.path.relpath(skill.dir, skills_dir), kept
            # explicit so the link stays stable regardless of cwd
            _ = skills_dir
            links[link_name] = rel_target
    return links


def sync_links(
    skills_dir: Path, links: dict[str, Path], dry_run: bool = False
) -> tuple[list[str], list[str]]:
    """Create planned symlinks, prune pack-owned strays. Returns (created, pruned).

    A link is "pack-owned" (prunable) when it is a symlink pointing into
    vendor/skill-packs/ — real directories are never touched, so a local
    skill that collides with a pack name always wins.
    """
    created: list[str] = []
    pruned: list[str] = []
    for entry in sorted(skills_dir.iterdir() if skills_dir.exists() else []):
        if not entry.is_symlink():
            continue
        target = Path(entry.readlink())
        if "skill-packs" not in target.parts:
            continue
        if entry.name not in links:
            if not dry_run:
                entry.unlink()
            pruned.append(entry.name)
    for name, target in sorted(links.items()):
        link = skills_dir / name
        if link.is_symlink():
            if Path(link.readlink()) == target:
                continue  # already correct
            if not dry_run:
                link.unlink()
        elif link.exists():
            print(
                f"WARN: {link} exists and is not a symlink — leaving it alone "
                f"(local skill wins over pack)",
                file=sys.stderr,
            )
            continue
        if not dry_run:
            link.symlink_to(target)
        created.append(name)
    return created, pruned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print plan only")
    parser.add_argument(
        "--root", default=".", help="repo root (default: current directory)"
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    packs = load_manifest(root / MANIFEST)
    patterns = load_ignore_patterns(root / SKILLIGNORE)
    links = plan_links(root, packs, patterns)
    created, pruned = sync_links(root / SKILLS_DIR, links, dry_run=args.dry_run)

    verb = "would create" if args.dry_run else "created"
    print(
        f"skill-packs: {len(links)} link(s) planned, "
        f"{verb} {len(created)}, pruned {len(pruned)} "
        f"({len(patterns)} ignore pattern(s))"
    )
    for name in created:
        print(f"  + {name}")
    for name in pruned:
        print(f"  - {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
