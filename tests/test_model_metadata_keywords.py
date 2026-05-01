"""Tests for rfc.model_metadata_keywords."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from robot.api.exceptions import SkipExecution

from rfc.model_metadata_keywords import (
    ModelMetadataKeywords,
    _build_metadata_payload,
    _ollama_to_hf,
)


def test_build_metadata_payload_has_required_fields() -> None:
    payload = _build_metadata_payload({"llama3": {"name": "llama3"}}, "2026-05-01")
    assert payload["version"] == "1.0"
    assert payload["generated_at"] == "2026-05-01"
    assert payload["models"] == {"llama3": {"name": "llama3"}}


def test_ollama_to_hf_maps_known_model() -> None:
    assert _ollama_to_hf("llama3") == "meta-llama/Meta-Llama-3-8B"


def test_ollama_to_hf_passthrough_for_unknown() -> None:
    assert _ollama_to_hf("mistral") == "mistral"


def test_save_model_metadata_yaml_writes_valid_yaml(tmp_path: Path) -> None:
    keywords = ModelMetadataKeywords()
    target = tmp_path / "models.yaml"
    keywords.save_model_metadata_yaml(
        {"mistral": {"name": "mistral", "title": "Mistral"}},
        str(target),
        generated_at="2026-05-01",
    )
    assert target.exists()
    loaded = yaml.safe_load(target.read_text())
    assert loaded["version"] == "1.0"
    assert loaded["generated_at"] == "2026-05-01"
    assert loaded["models"]["mistral"]["title"] == "Mistral"


def test_save_model_metadata_yaml_creates_parent_dirs(tmp_path: Path) -> None:
    keywords = ModelMetadataKeywords()
    target = tmp_path / "nested" / "subdir" / "models.yaml"
    keywords.save_model_metadata_yaml({}, str(target), generated_at="2026-05-01")
    assert target.exists()


def test_save_model_metadata_yaml_defaults_generated_at(tmp_path: Path) -> None:
    keywords = ModelMetadataKeywords()
    target = tmp_path / "models.yaml"
    keywords.save_model_metadata_yaml({"llama3": {}}, str(target))
    loaded = yaml.safe_load(target.read_text())
    assert loaded["generated_at"]  # non-empty string


def test_research_models_metadata_skips_when_browser_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the Browser library is not installed, the keyword must Skip."""
    monkeypatch.setitem(sys.modules, "Browser", None)
    keywords = ModelMetadataKeywords()
    with pytest.raises(SkipExecution, match="Browser library not installed"):
        keywords.research_models_metadata(["llama3"])


def test_research_models_metadata_drives_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Browser is available, the keyword orchestrates page visits."""
    fake_browser_instance = MagicMock()
    fake_browser_instance.get_text.side_effect = [
        "Llama 3",  # ollama h1
        "Llama 3 on HF",  # hf h1
    ]
    fake_browser_module = MagicMock()
    fake_browser_module.Browser.return_value = fake_browser_instance
    monkeypatch.setitem(sys.modules, "Browser", fake_browser_module)

    keywords = ModelMetadataKeywords()
    with patch("rfc.model_metadata_keywords.date") as fake_date:
        fake_date.today.return_value.isoformat.return_value = "2026-05-01"
        results = keywords.research_models_metadata(["llama3"])

    assert "llama3" in results
    assert results["llama3"]["title"] == "Llama 3"
    assert results["llama3"]["hugging_face_title"] == "Llama 3 on HF"
    assert results["llama3"]["researched_at"] == "2026-05-01"
    fake_browser_instance.new_browser.assert_called_once()
    fake_browser_instance.new_page.assert_called_once()
    fake_browser_instance.close_browser.assert_called_once()


def test_research_models_metadata_records_error_on_ollama_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_browser_instance = MagicMock()
    fake_browser_instance.go_to.side_effect = RuntimeError("boom")
    fake_browser_module = MagicMock()
    fake_browser_module.Browser.return_value = fake_browser_instance
    monkeypatch.setitem(sys.modules, "Browser", fake_browser_module)

    keywords = ModelMetadataKeywords()
    results = keywords.research_models_metadata(["mistral"])

    assert results["mistral"]["error"] == "boom"
    assert "title" not in results["mistral"]
    fake_browser_instance.close_browser.assert_called_once()
