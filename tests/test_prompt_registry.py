"""Tests for rfc.prompt_registry — versioned, content-hashed prompt identity (RFC-008 A2).

Covers the three MVP guarantees (RFC-008 §6.2): identity round-trip, drift detection,
and the provenance seam — plus that the real PUBLIC catalog (core/config/prompts.yaml)
is drift-free and registers the grader tranche. The private charter catalog lives in the
monorepo (modules/agents/) and is exercised by modules/ops/tests/test_check_prompt_registry.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rfc.prompt_registry import (
    PromptRegistry,
    PromptRegistryError,
    sha256_hex,
)

CORE_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_CATALOG = CORE_ROOT / "config" / "prompts.yaml"


def _write_catalog(
    tmp_path: Path, text: str, *, version: int = 1, sha: str | None = None
) -> Path:
    """Write a prompt file + a single-entry catalog into tmp_path; return the catalog path."""
    prompt_file = tmp_path / "prompts" / "sample.txt"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(text, encoding="utf-8")
    catalog = tmp_path / "prompts.yaml"
    catalog.write_text(
        "catalog_version: 1\n"
        'base: "."\n'
        "prompts:\n"
        "  sample.prompt:\n"
        "    path: prompts/sample.txt\n"
        f"    version: {version}\n"
        f'    sha256: "{sha if sha is not None else sha256_hex(text)}"\n',
        encoding="utf-8",
    )
    return catalog


class TestSha256Hex:
    def test_known_value(self):
        # echo -n '' | sha256sum
        assert sha256_hex("") == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )

    def test_is_utf8_of_text(self):
        import hashlib

        assert (
            sha256_hex("héllo") == hashlib.sha256("héllo".encode("utf-8")).hexdigest()
        )


class TestIdentity:
    def test_round_trip(self, tmp_path):
        text = "You are a judge.\n{question}\n"
        catalog = _write_catalog(tmp_path, text, version=3)
        reg = PromptRegistry.from_catalog(catalog)

        assert "sample.prompt" in reg
        assert list(reg) == ["sample.prompt"]

        rec = reg.resolve("sample.prompt")
        assert rec.prompt_id == "sample.prompt"
        assert rec.version == 3
        assert rec.text == text
        assert rec.content_hash == sha256_hex(text)

    def test_unknown_id_raises(self, tmp_path):
        reg = PromptRegistry.from_catalog(_write_catalog(tmp_path, "x\n"))
        with pytest.raises(PromptRegistryError, match="unknown prompt id"):
            reg.resolve("nope")

    def test_base_resolves_relative_to_catalog(self, tmp_path):
        # A default base of "." resolves entry paths against the catalog's own directory.
        catalog = _write_catalog(tmp_path, "abc\n")
        rec = PromptRegistry.from_catalog(catalog).resolve("sample.prompt")
        assert rec.path == (tmp_path / "prompts" / "sample.txt").resolve()


class TestDrift:
    def test_clean_when_hash_matches(self, tmp_path):
        reg = PromptRegistry.from_catalog(_write_catalog(tmp_path, "stable text\n"))
        assert reg.drift("sample.prompt") is None
        assert reg.check() == []

    def test_edit_without_bump_trips(self, tmp_path):
        text = "original judge prompt\n"
        catalog = _write_catalog(tmp_path, text)  # sha recorded for `text`
        # Mutate the referenced file WITHOUT updating the catalog's recorded hash.
        (tmp_path / "prompts" / "sample.txt").write_text("mutated!\n", encoding="utf-8")
        reg = PromptRegistry.from_catalog(catalog)

        msg = reg.drift("sample.prompt")
        assert msg is not None
        assert "sample.prompt" in msg
        assert reg.check() == [msg]

    def test_missing_file_reported_not_crashed(self, tmp_path):
        catalog = _write_catalog(tmp_path, "text\n")
        (tmp_path / "prompts" / "sample.txt").unlink()
        reg = PromptRegistry.from_catalog(catalog)
        msg = reg.drift("sample.prompt")
        assert msg is not None and "not readable" in msg
        assert len(reg.check()) == 1


class TestProvenanceSeam:
    def test_returns_id_version_live_hash(self, tmp_path):
        text = "judge {question}\n"
        reg = PromptRegistry.from_catalog(_write_catalog(tmp_path, text, version=2))
        assert reg.provenance("sample.prompt") == ("sample.prompt", 2, sha256_hex(text))


class TestCatalogStructure:
    def test_missing_catalog(self, tmp_path):
        with pytest.raises(PromptRegistryError, match="catalog not found"):
            PromptRegistry.from_catalog(tmp_path / "absent.yaml")

    def test_not_a_mapping(self, tmp_path):
        bad = tmp_path / "c.yaml"
        bad.write_text("- just\n- a\n- list\n", encoding="utf-8")
        with pytest.raises(PromptRegistryError, match="not a mapping"):
            PromptRegistry.from_catalog(bad)

    def test_prompts_missing(self, tmp_path):
        bad = tmp_path / "c.yaml"
        bad.write_text("catalog_version: 1\n", encoding="utf-8")
        with pytest.raises(PromptRegistryError, match="'prompts' must be a mapping"):
            PromptRegistry.from_catalog(bad)

    def test_entry_missing_fields(self, tmp_path):
        bad = tmp_path / "c.yaml"
        bad.write_text(
            "prompts:\n  x:\n    path: p.txt\n    version: 1\n", encoding="utf-8"
        )
        with pytest.raises(PromptRegistryError, match="needs a string 'sha256'"):
            PromptRegistry.from_catalog(bad)

    def test_non_int_version_rejected(self, tmp_path):
        bad = tmp_path / "c.yaml"
        bad.write_text(
            'prompts:\n  x:\n    path: p.txt\n    version: "1"\n    sha256: "a"\n',
            encoding="utf-8",
        )
        with pytest.raises(PromptRegistryError, match="needs an int 'version'"):
            PromptRegistry.from_catalog(bad)

    def test_entry_not_a_mapping(self, tmp_path):
        bad = tmp_path / "c.yaml"
        bad.write_text("prompts:\n  x: just-a-string\n", encoding="utf-8")
        with pytest.raises(PromptRegistryError, match="must be a mapping"):
            PromptRegistry.from_catalog(bad)

    def test_entry_missing_path(self, tmp_path):
        bad = tmp_path / "c.yaml"
        bad.write_text(
            'prompts:\n  x:\n    version: 1\n    sha256: "a"\n', encoding="utf-8"
        )
        with pytest.raises(PromptRegistryError, match="needs a string 'path'"):
            PromptRegistry.from_catalog(bad)

    def test_bad_base_type(self, tmp_path):
        bad = tmp_path / "c.yaml"
        bad.write_text("base: 3\nprompts: {}\n", encoding="utf-8")
        with pytest.raises(PromptRegistryError, match="'base' must be a string"):
            PromptRegistry.from_catalog(bad)


class TestRealPublicCatalog:
    """The shipped public catalog must be drift-free and register the grader tranche."""

    def test_public_catalog_drift_free(self):
        reg = PromptRegistry.from_catalog(PUBLIC_CATALOG)
        assert reg.check() == []

    def test_grader_prompt_registered(self):
        reg = PromptRegistry.from_catalog(PUBLIC_CATALOG)
        assert "grader.default_judge" in reg
        rec = reg.resolve("grader.default_judge")
        assert rec.version == 1
        # Identity round-trip against the real, shipped file.
        assert rec.content_hash == sha256_hex(rec.text)
        assert reg.entries["grader.default_judge"].recorded_hash == rec.content_hash
        assert "You are an automaed grader." in rec.text
