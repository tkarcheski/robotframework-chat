"""Tests for the opencode comparability gate module + VerifiedLocalModel (#278).

The ``rfc.opencode_config`` module is the durable home of the #191/#273 gate; the
resolution rules themselves are exercised end-to-end through
``rfc.harness_comparison`` in ``test_harness_comparison.py``. This file focuses on
the module's own surface: the gate-minted Tier-A capability token and the
token-returning gate functions. (``test_opencode_config.py`` is a separate,
unrelated shape guard for the repo's ``core/opencode.json`` *file*.)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rfc.opencode_config import (
    ComparabilityError,
    VerifiedLocalModel,
    assert_model_resolves_local,
    assert_opencode_comparable,
    gate_config,
    load_opencode_config,
)

_LOCAL_CFG = {
    "model": "ollama/my-model",
    "provider": {
        "ollama": {
            "options": {"baseURL": "http://localhost:11434/v1"},
            "models": {"my-model": {}},
        }
    },
}


class TestVerifiedLocalModelToken:
    def test_direct_construction_is_refused(self) -> None:
        # A hand-built token fails closed, so a runner that accidentally omits
        # the gate cannot mint Tier-A provenance for a remote model. (Deliberate
        # in-process forgery via the importable mint key remains possible; #314
        # tracks hardening.)
        with pytest.raises(ComparabilityError, match="only be minted by the"):
            VerifiedLocalModel("openai/gpt-4o")

    def test_gate_mints_token_for_local_model(self) -> None:
        token = assert_model_resolves_local(
            "ollama/my-model", _LOCAL_CFG, source="test"
        )
        assert isinstance(token, VerifiedLocalModel)
        assert token.model_id == "ollama/my-model"

    def test_gate_config_returns_token_for_pinned_default(self) -> None:
        token = gate_config(_LOCAL_CFG, source="test")
        assert isinstance(token, VerifiedLocalModel)
        assert token.model_id == "ollama/my-model"

    def test_gate_refuses_remote_model_no_token(self) -> None:
        with pytest.raises(ComparabilityError, match="not declared"):
            assert_model_resolves_local("openai/gpt-4o", _LOCAL_CFG, source="test")

    def test_tokens_compare_equal_on_model_id(self) -> None:
        # The mint key is an InitVar, never a stored field: two tokens for the same
        # model are equal and hashable (so they can key/dedupe without surprises).
        a = assert_model_resolves_local("ollama/my-model", _LOCAL_CFG, source="t")
        b = assert_model_resolves_local("ollama/my-model", _LOCAL_CFG, source="t")
        assert a == b
        assert len({a, b}) == 1


class TestAssertOpencodeComparableStr:
    def test_returns_plain_model_id_string(self, tmp_path: Path) -> None:
        # Back-compat: the public helper still returns the model id *string*, not
        # the token, so existing callers keep working.
        cfg = tmp_path / "opencode.json"
        cfg.write_text(json.dumps(_LOCAL_CFG))
        result = assert_opencode_comparable(cfg)
        assert result == "ollama/my-model"
        assert isinstance(result, str)

    def test_load_opencode_config_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ComparabilityError, match="not found"):
            load_opencode_config(tmp_path / "nope.json")
