"""Tests for scripts/sync_skill_packs.py — external skill-pack symlink sync.

Skill packs are forked external repos submoduled under vendor/skill-packs/.
The sync script reads config/skill_packs.yaml plus the gitignore-style
.skillignore file and materializes prefixed symlinks in .claude/skills/ so
Claude Code's flat <name>/SKILL.md discovery finds them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.sync_skill_packs import (
    SkillPack,
    discover_skills,
    is_ignored,
    load_ignore_patterns,
    load_manifest,
    plan_links,
    sync_links,
)


@pytest.fixture()
def pack_tree(tmp_path: Path) -> Path:
    """A fake skill-pack checkout shaped like mattpocock/skills."""
    pack = tmp_path / "vendor" / "skill-packs" / "mattpocock"
    for rel in [
        "skills/engineering/tdd",
        "skills/engineering/diagnose",
        "skills/productivity/teach",
        "skills/deprecated/qa",
        "skills/personal/obsidian-vault",
    ]:
        d = pack / rel
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"# {d.name}\n")
    # a non-skill dir (no SKILL.md) must be ignored by discovery
    (pack / "skills" / "engineering" / "notes").mkdir(parents=True)
    return pack


@pytest.fixture()
def repo(tmp_path: Path, pack_tree: Path) -> Path:
    (tmp_path / ".claude" / "skills").mkdir(parents=True)
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "skill_packs.yaml").write_text(
        "packs:\n"
        "  - name: mattpocock\n"
        "    path: vendor/skill-packs/mattpocock\n"
        "    prefix: mp-\n"
        '    glob: "skills/*/*/SKILL.md"\n'
        "    upstream: https://github.com/mattpocock/skills\n"
        "    fork: git@github.com:tkarcheski/mattpocock-skills.git\n"
    )
    return tmp_path


class TestManifest:
    def test_load_manifest(self, repo: Path) -> None:
        packs = load_manifest(repo / "config" / "skill_packs.yaml")
        assert packs == [
            SkillPack(
                name="mattpocock",
                path="vendor/skill-packs/mattpocock",
                prefix="mp-",
                glob="skills/*/*/SKILL.md",
            )
        ]


class TestDiscovery:
    def test_discovers_only_skill_dirs(self, repo: Path) -> None:
        pack = load_manifest(repo / "config" / "skill_packs.yaml")[0]
        skills = discover_skills(repo, pack)
        names = sorted(s.name for s in skills)
        assert names == ["diagnose", "obsidian-vault", "qa", "tdd", "teach"]
        # identity is pack-relative: <pack>/<category>/<name>
        tdd = next(s for s in skills if s.name == "tdd")
        assert tdd.ident == "mattpocock/engineering/tdd"


class TestIgnore:
    def test_ignore_patterns_match_category_and_name(self) -> None:
        patterns = ["mattpocock/deprecated/*", "*/personal/*", "mattpocock/*/teach"]
        assert is_ignored("mattpocock/deprecated/qa", patterns)
        assert is_ignored("mattpocock/personal/obsidian-vault", patterns)
        assert is_ignored("mattpocock/productivity/teach", patterns)
        assert not is_ignored("mattpocock/engineering/tdd", patterns)

    def test_comments_and_blanks_skipped(self, tmp_path: Path) -> None:
        f = tmp_path / ".skillignore"
        f.write_text("# comment\n\nmattpocock/deprecated/*\n")
        assert load_ignore_patterns(f) == ["mattpocock/deprecated/*"]

    def test_missing_ignore_file_is_empty(self, tmp_path: Path) -> None:
        assert load_ignore_patterns(tmp_path / "nope") == []


class TestPlanAndSync:
    def test_plan_prefixes_and_filters(self, repo: Path) -> None:
        pack = load_manifest(repo / "config" / "skill_packs.yaml")[0]
        links = plan_links(repo, [pack], ["mattpocock/deprecated/*"])
        assert "mp-tdd" in links
        assert "mp-qa" not in links  # ignored
        # targets are relative paths from .claude/skills/ into the pack
        assert links["mp-tdd"] == Path(
            "../../vendor/skill-packs/mattpocock/skills/engineering/tdd"
        )

    def test_sync_creates_and_prunes_symlinks(self, repo: Path) -> None:
        pack = load_manifest(repo / "config" / "skill_packs.yaml")[0]
        skills_dir = repo / ".claude" / "skills"
        links = plan_links(repo, [pack], [])
        created, pruned = sync_links(skills_dir, links)
        assert (skills_dir / "mp-tdd").is_symlink()
        assert (skills_dir / "mp-tdd" / "SKILL.md").read_text() == "# tdd\n"
        assert len(created) == 5 and pruned == []
        # now ignore one skill and re-sync: its link is pruned, others survive
        links2 = plan_links(repo, [pack], ["mattpocock/personal/*"])
        created2, pruned2 = sync_links(skills_dir, links2)
        assert created2 == []
        assert pruned2 == ["mp-obsidian-vault"]
        assert not (skills_dir / "mp-obsidian-vault").exists()
        assert (skills_dir / "mp-tdd").is_symlink()

    def test_sync_never_touches_real_dirs(self, repo: Path) -> None:
        """A real (non-symlink) skill dir with a colliding name is left alone."""
        skills_dir = repo / ".claude" / "skills"
        real = skills_dir / "mp-tdd"
        real.mkdir(parents=True)
        (real / "SKILL.md").write_text("local skill, do not clobber\n")
        pack = load_manifest(repo / "config" / "skill_packs.yaml")[0]
        links = plan_links(repo, [pack], [])
        created, _ = sync_links(skills_dir, links)
        assert "mp-tdd" not in created
        assert not real.is_symlink()
        assert (real / "SKILL.md").read_text() == "local skill, do not clobber\n"

    def test_sync_idempotent(self, repo: Path) -> None:
        pack = load_manifest(repo / "config" / "skill_packs.yaml")[0]
        skills_dir = repo / ".claude" / "skills"
        links = plan_links(repo, [pack], [])
        sync_links(skills_dir, links)
        created, pruned = sync_links(skills_dir, links)
        assert created == [] and pruned == []


class TestTopLevelPackPruning:
    """Links of packs mounted outside vendor/skill-packs/ must be prunable (#463)."""

    @pytest.fixture()
    def knowledge_repo(self, tmp_path: Path) -> Path:
        (tmp_path / ".claude" / "skills").mkdir(parents=True)
        (tmp_path / "config").mkdir(exist_ok=True)
        (tmp_path / "config" / "skill_packs.yaml").write_text(
            "packs:\n"
            "  - name: knowledge\n"
            "    path: knowledge\n"
            '    prefix: ""\n'
            '    glob: "skills/*/SKILL.md"\n'
            "    upstream: https://github.com/tkarcheski/knowledge\n"
            "    fork: git@github.com:tkarcheski/knowledge.git\n"
        )
        for name in ["writing-prose", "tiered-recall"]:
            d = tmp_path / "knowledge" / "skills" / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(f"# {name}\n")
        return tmp_path

    def test_removed_knowledge_skill_link_is_pruned(self, knowledge_repo: Path) -> None:
        import shutil

        from scripts.sync_skill_packs import main

        assert main(["--root", str(knowledge_repo)]) == 0
        skills_dir = knowledge_repo / ".claude" / "skills"
        assert (skills_dir / "writing-prose").is_symlink()

        # The skill disappears upstream; the committed link must be pruned.
        shutil.rmtree(knowledge_repo / "knowledge" / "skills" / "writing-prose")
        assert main(["--root", str(knowledge_repo)]) == 0
        assert not (skills_dir / "writing-prose").is_symlink(), (
            "stale (broken) link of a top-level pack must be pruned"
        )
        assert (skills_dir / "tiered-recall").is_symlink()


class TestUninitializedPack:
    """A clone without --recurse-submodules must not nuke committed links (#453)."""

    def test_pack_is_initialized(self, repo: Path) -> None:
        from scripts.sync_skill_packs import pack_is_initialized

        packs = load_manifest(repo / "config" / "skill_packs.yaml")
        assert pack_is_initialized(repo, packs[0]) is True
        # Uninitialized submodule == existing but empty directory
        import shutil

        pack_dir = repo / packs[0].path
        shutil.rmtree(pack_dir)
        pack_dir.mkdir(parents=True)
        assert pack_is_initialized(repo, packs[0]) is False

    def test_uninitialized_pack_preserves_committed_links(self, repo: Path) -> None:
        """Empty pack dir → zero planned links → prune must NOT fire."""
        import shutil

        from scripts.sync_skill_packs import main

        # First sync with the pack present creates the committed links.
        assert main(["--root", str(repo)]) == 0
        skills_dir = repo / ".claude" / "skills"
        before = sorted(p.name for p in skills_dir.iterdir() if p.is_symlink())
        assert before, "fixture should have created pack links"

        # Simulate a fresh clone: submodule dir exists but is empty.
        pack_dir = repo / "vendor" / "skill-packs" / "mattpocock"
        shutil.rmtree(pack_dir)
        pack_dir.mkdir(parents=True)

        assert main(["--root", str(repo)]) == 0
        after = sorted(p.name for p in skills_dir.iterdir() if p.is_symlink())
        assert after == before, "links must survive an uninitialized pack"
