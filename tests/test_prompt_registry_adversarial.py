"""Adversarial coverage for the prompt registry / grader externalization (RFC-008 A2).

Added by test-design to attack gaps the PR's own tests leave open:

* the fallback fires when the *registered file itself* is unreadable (the PR tests
  only cover a missing env override), and yields byte-identical legacy text;
* the provenance seam reports the *registered* coordinate, which can differ from the
  text that actually ran under an RFC_GRADER_PROMPT override (an honesty caveat for A3);
* content hashing has no canonicalization — a trailing-newline / CRLF twin hashes
  differently (a real cross-platform drift-check caveat given no .gitattributes eol rule).

The real charters live in the monorepo-private modules/agents/ catalog and are
round-tripped by modules/ops/tests/ (a *core* test must not read that path — it would
break on the public mirror).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import rfc.grader as grader_mod
from rfc.grader import Grader
from rfc.prompt_registry import PromptRegistry, sha256_hex


def _legacy_prompt(question: str, expected: str, actual: str) -> str:
    return f"""
You are an automaed grader.

Question:
{question}

Expected answer:
{expected}

Model answer:
{actual}

Rules:
- Respond ONLY with valid JSON
- No markdown
- No commentary
- score must be a number between 0.0 and 1.0
- use partial credit when the answer is only partially correct

Format:
{{
  "score": 0.0 to 1.0,
  "reason": "short explanation"
}}
"""


def test_fallback_fires_when_registered_file_unreadable(monkeypatch, tmp_path):
    """Not just a missing override — if the registered .txt is gone, grading still
    produces the byte-identical legacy prompt from the in-code fallback."""
    monkeypatch.delenv("RFC_GRADER_PROMPT", raising=False)
    monkeypatch.setattr(grader_mod, "_GRADER_PROMPT_PATH", tmp_path / "gone.txt")
    client = MagicMock()
    client.generate.return_value = '{"score": 1, "reason": "ok"}'
    Grader(client).grade("What is 2+2?", "4", "4")
    client.generate.assert_called_once_with(_legacy_prompt("What is 2+2?", "4", "4"))


def test_provenance_reports_registered_hash_not_the_env_override(tmp_path):
    """The registry resolves the *registered* file. Under an RFC_GRADER_PROMPT override
    the grader actually runs a DIFFERENT prompt, but provenance() still reports the
    registered coordinate — a seam-honesty caveat A3 (#242) must handle."""
    registered_text = "REGISTERED {question}\n"
    (tmp_path / "registered.txt").write_text(registered_text, encoding="utf-8")
    override_text = "VARIANT {question}\n"
    (tmp_path / "variant.txt").write_text(override_text, encoding="utf-8")
    catalog = tmp_path / "prompts.yaml"
    catalog.write_text(
        "catalog_version: 1\n"
        'base: "."\n'
        "prompts:\n"
        "  grader.default_judge:\n"
        "    path: registered.txt\n"
        "    version: 1\n"
        f'    sha256: "{sha256_hex(registered_text)}"\n',
        encoding="utf-8",
    )
    reg = PromptRegistry.from_catalog(catalog)
    _pid, _ver, prov_hash = reg.provenance("grader.default_judge")
    # provenance == registered file's hash, NOT the override's — documents the gap.
    assert prov_hash == sha256_hex(registered_text)
    assert prov_hash != sha256_hex(override_text)


def test_hashing_is_not_canonicalized_newline_and_crlf_differ():
    """sha256_hex hashes raw UTF-8: visually-identical text with a different trailing
    newline or CRLF hashes differently. Documents the drift-check portability caveat."""
    assert sha256_hex("judge prompt") != sha256_hex("judge prompt\n")
    assert sha256_hex("a\nb\n") != sha256_hex("a\r\nb\r\n")
