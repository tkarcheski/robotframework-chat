"""Prompt registry — versioned, content-hashed identity for prompts (RFC-008 A2).

A prompt becomes a first-class artifact ``(name, version, content_hash)`` resolvable
by id, so an edit to a prompt's text is *detectable* rather than silent. This
generalizes the externalize-and-fallback precedent already used for the generative
listener's prompts (``resources/generative_mutate_prompts.resource``) and reuses the
same SHA-256 content-hashing that :mod:`rfc.answer_cache` folds into its cache key.

The registry is deliberately small (RFC-008 §6.2 — "not a prompt-management product"):

* an **identity** — a catalog maps ``prompt_id -> {path, version, sha256}``; the hash
  recorded in the catalog is the *blessed* hash of that version's text on disk;
* a **drift check** — :meth:`PromptRegistry.check` recomputes each referenced file's
  hash and reports every prompt whose text diverges from its recorded hash, exactly as
  an unreserved RFC fails ``check_rfc_index.py``; an edit without a matching catalog /
  version update is caught;
* a **provenance seam** — :meth:`PromptRegistry.provenance` returns
  ``(prompt_id, version, content_hash)`` for a run to log on the spine (RFC-008 §5).
  A3 (#242) writes it to ``agentic_harnesses``; this module only exposes it.

Registry *home* is split to keep the promotion gate clean (RFC-008 §6.3 / §10): the
public catalog (``core/config/prompts.yaml``) carries product prompts and ships to the
mirror; private fleet charters live in a separate monorepo-private catalog that
the public mirror never sees. This module is
catalog-agnostic — it loads whichever catalog file it is handed — so no private path is
ever hard-coded in mirrored code.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import yaml


def sha256_hex(text: str) -> str:
    """Return the hex SHA-256 of ``text`` (UTF-8).

    The single content-hash primitive for prompt identity — the same digest
    :mod:`rfc.answer_cache` folds into its cache key, applied here to a prompt's raw
    text so that "the version a suite thinks it ran" and "the text that actually ran"
    are comparable.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class PromptRegistryError(ValueError):
    """A structural problem with a catalog (bad shape, unknown id, missing text)."""


@dataclass(frozen=True)
class PromptEntry:
    """One catalog row: a prompt's declared identity and where its text lives."""

    prompt_id: str
    version: int
    path: Path
    recorded_hash: str


@dataclass(frozen=True)
class PromptRecord:
    """A resolved prompt: its declared identity plus the text actually on disk."""

    prompt_id: str
    version: int
    content_hash: str
    text: str
    path: Path


def _parse_entry(
    prompt_id: str, spec: Any, base_dir: Path, catalog_path: Path
) -> PromptEntry:
    if not isinstance(spec, dict):
        raise PromptRegistryError(
            f"{catalog_path}: entry '{prompt_id}' must be a mapping"
        )
    rel = spec.get("path")
    version = spec.get("version")
    recorded = spec.get("sha256")
    if not isinstance(rel, str):
        raise PromptRegistryError(
            f"{catalog_path}: '{prompt_id}' needs a string 'path'"
        )
    # bool is an int subclass; a version of True/False is a mistake, not a version.
    if not isinstance(version, int) or isinstance(version, bool):
        raise PromptRegistryError(
            f"{catalog_path}: '{prompt_id}' needs an int 'version'"
        )
    if not isinstance(recorded, str):
        raise PromptRegistryError(
            f"{catalog_path}: '{prompt_id}' needs a string 'sha256'"
        )
    return PromptEntry(
        prompt_id=prompt_id,
        version=version,
        path=(base_dir / rel).resolve(),
        recorded_hash=recorded,
    )


@dataclass
class PromptRegistry:
    """The prompts declared by a single catalog file, resolvable by id."""

    catalog_path: Path
    entries: dict[str, PromptEntry] = field(default_factory=dict)

    @classmethod
    def from_catalog(cls, catalog_path: str | Path) -> PromptRegistry:
        """Load a catalog file.

        The catalog is a mapping with an optional ``base`` (a directory, relative to the
        catalog file, that entry ``path``s resolve against — default the catalog's own
        directory) and a ``prompts`` mapping of ``prompt_id -> {path, version, sha256}``.
        """
        path = Path(catalog_path)
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise PromptRegistryError(f"catalog not found: {path}") from exc
        if not isinstance(raw, dict):
            raise PromptRegistryError(f"catalog {path} is not a mapping")
        base = raw.get("base", ".")
        if not isinstance(base, str):
            raise PromptRegistryError(f"catalog {path}: 'base' must be a string")
        base_dir = (path.parent / base).resolve()
        prompts = raw.get("prompts")
        if not isinstance(prompts, dict):
            raise PromptRegistryError(f"catalog {path}: 'prompts' must be a mapping")
        entries = {
            str(pid): _parse_entry(str(pid), spec, base_dir, path)
            for pid, spec in prompts.items()
        }
        return cls(catalog_path=path, entries=entries)

    def __iter__(self) -> Iterator[str]:
        return iter(self.entries)

    def __contains__(self, prompt_id: object) -> bool:
        return prompt_id in self.entries

    def resolve(self, prompt_id: str) -> PromptRecord:
        """Return the resolved record for ``prompt_id`` (identity + on-disk text).

        The ``content_hash`` is the live sha256 of the **registered file** on disk, so it
        catches drift from the catalog's recorded hash (an edit without a version bump).
        It is *not*, on its own, "what actually ran": a runtime may resolve a **different**
        text via an env override (e.g. the grader's ``RFC_GRADER_PROMPT``) before executing.
        The spine (RFC-008 §5) therefore logs the *resolved* hash of the text that actually
        ran — see :func:`rfc.grader.resolved_grader_provenance` — which equals this
        registered hash only when no override is in effect.
        """
        try:
            entry = self.entries[prompt_id]
        except KeyError as exc:
            raise PromptRegistryError(
                f"unknown prompt id '{prompt_id}' in {self.catalog_path}"
            ) from exc
        try:
            text = entry.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PromptRegistryError(
                f"'{prompt_id}': text file not readable: {entry.path} ({exc})"
            ) from exc
        return PromptRecord(
            prompt_id=prompt_id,
            version=entry.version,
            content_hash=sha256_hex(text),
            text=text,
            path=entry.path,
        )

    def drift(self, prompt_id: str) -> str | None:
        """Return a violation message if ``prompt_id``'s text has drifted, else ``None``."""
        try:
            record = self.resolve(prompt_id)
        except PromptRegistryError as exc:
            return str(exc)
        recorded = self.entries[prompt_id].recorded_hash
        if record.content_hash != recorded:
            return (
                f"'{prompt_id}' (v{record.version}): {record.path.name} hashes to "
                f"{record.content_hash} but the catalog records {recorded} — bump "
                f"'version' and update 'sha256' to bless the new text, or revert the edit"
            )
        return None

    def check(self) -> list[str]:
        """Return every drift / structural violation across the catalog (empty = clean)."""
        return [msg for pid in self.entries if (msg := self.drift(pid)) is not None]

    def provenance(self, prompt_id: str) -> tuple[str, int, str]:
        """Return the ``(prompt_id, version, content_hash)`` **registered** coordinate.

        This is the id's *registered* coordinate — the version and the live hash of the
        registered file — NOT necessarily what actually ran. Under an env override (e.g.
        the grader's ``RFC_GRADER_PROMPT``) the runtime executes a *different* prompt, so a
        spine write must record the **resolved** hash of the text that ran
        (:func:`rfc.grader.resolved_grader_provenance`), not this registered coordinate.
        Wiring ``provenance(id)`` straight to the spine would make both arms of an override
        A/B log the same coordinate while running different text (RFC-008 §5/§7). This
        method is a valid primitive for the registered coordinate; the resolved-hash
        obligation lives at the spine seam (design's bound A3 criterion, pinned green in A2
        by ``test_provenance_reports_registered_hash_not_the_env_override``).
        """
        record = self.resolve(prompt_id)
        return (record.prompt_id, record.version, record.content_hash)
