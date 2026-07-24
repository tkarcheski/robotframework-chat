"""Tests for rfc.grader.Grader."""

from unittest.mock import MagicMock

import pytest

from rfc.exceptions import GraderUnavailableError
from rfc.grader import Grader
from rfc.models import GradeResult


class TestGrader:
    def test_init_none_client_rejected(self):
        with pytest.raises(TypeError, match="must not be None"):
            Grader(None)

    def test_init_with_client(self):
        client = MagicMock()
        grader = Grader(client)
        assert grader.llm is client

    def test_grade_correct_answer(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 1, "reason": "correct"}'
        grader = Grader(client)
        result = grader.grade("What is 2+2?", "4", "4")
        assert isinstance(result, GradeResult)
        assert result.score == 1.0
        assert isinstance(result.score, float)
        assert result.reason == "correct"

    def test_grade_incorrect_answer(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 0, "reason": "wrong"}'
        grader = Grader(client)
        result = grader.grade("What is 2+2?", "4", "5")
        assert result.score == 0.0

    def test_grade_invalid_json(self):
        # A judge that cannot emit a verdict is an instrument outage, so the
        # test skips rather than blaming the model under test (see
        # tests/test_gold_judge.py for the full contract).
        client = MagicMock()
        client.generate.return_value = "not valid json"
        grader = Grader(client)
        with pytest.raises(GraderUnavailableError):
            grader.grade("q", "e", "a")

    def test_grade_missing_score_field(self):
        client = MagicMock()
        client.generate.return_value = '{"reason": "x"}'
        grader = Grader(client)
        with pytest.raises(GraderUnavailableError):
            grader.grade("q", "e", "a")

    def test_grade_missing_reason_field(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 1}'
        grader = Grader(client)
        with pytest.raises(GraderUnavailableError):
            grader.grade("q", "e", "a")

    def test_grade_empty_question(self):
        client = MagicMock()
        grader = Grader(client)
        with pytest.raises(ValueError, match="non-empty string"):
            grader.grade("", "expected", "actual")

    def test_grade_non_string_input(self):
        client = MagicMock()
        grader = Grader(client)
        with pytest.raises(TypeError, match="question must be a str"):
            grader.grade(123, "expected", "actual")

    def test_grade_non_string_expected(self):
        client = MagicMock()
        grader = Grader(client)
        with pytest.raises(TypeError, match="expected must be a str"):
            grader.grade("q", 123, "actual")

    def test_grade_partial_score(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 0.4, "reason": "partially correct"}'
        grader = Grader(client)
        result = grader.grade("What is 2+2?", "4", "It might be 3 or 4")
        assert result.score == 0.4

    def test_grade_prompt_requests_fractional_scores(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 0.5, "reason": "partial"}'
        grader = Grader(client)
        grader.grade("q", "e", "a")
        prompt = client.generate.call_args[0][0]
        assert "score must be a number between 0.0 and 1.0" in prompt
        assert "use partial credit" in prompt
        assert '"score": 0.0 to 1.0' in prompt


class _ThinkingGraderClient:
    """Fake grader LLM that returns thinking-only output until think=False.

    Mimics qwen3.6 on Ollama 0.30+ (issue #131): the OllamaClient surfaces a
    blank `response` + non-empty `thinking` as an inline <think> block, so the
    usable grader answer is empty until reasoning is turned off.
    """

    def __init__(self):
        self.think = None
        self.last_metrics = None
        self.calls = []
        self.think_seen = []

    def generate(self, prompt):
        self.calls.append(prompt)
        self.think_seen.append(self.think)
        if self.think is False:
            return '{"score": 0.5, "reason": "graded after think disabled"}'
        return "<think>reasoning but no verdict</think>"


class _NoThinkClient:
    def __init__(self, response):
        self._response = response
        self.last_metrics = None
        self.calls = 0

    def generate(self, prompt):
        self.calls += 1
        return self._response


class TestGraderThinkRetry:
    def test_empty_verdict_retries_with_think_false(self):
        client = _ThinkingGraderClient()
        result = Grader(client).grade("q", "e", "a")
        assert result.score == 0.5
        # Two calls: thinking-only, then the retry with think disabled.
        assert len(client.calls) == 2
        assert client.think_seen == [None, False]
        # Original think setting restored after the retry.
        assert client.think is None

    def test_retry_logs_warning(self):
        from unittest.mock import patch

        client = _ThinkingGraderClient()
        with patch("rfc.grader.logger") as mock_logger:
            Grader(client).grade("q", "e", "a")
        assert mock_logger.warn.called

    def test_no_retry_when_first_verdict_nonempty(self):
        client = _ThinkingGraderClient()
        # Pre-answer so the first generate already yields a usable verdict.
        client.generate = lambda prompt: '{"score": 1.0, "reason": "ok"}'  # type: ignore[method-assign]
        result = Grader(client).grade("q", "e", "a")
        assert result.score == 1.0
        # think must remain untouched (no retry path).
        assert client.think is None

    def test_no_retry_when_think_already_false(self):
        client = _ThinkingGraderClient()
        client.think = False  # already disabled; retrying can't help
        with pytest.raises(GraderUnavailableError):
            # think=False path returns valid JSON in the fake, so force empty:
            client.generate = lambda prompt: "<think>still nothing</think>"  # type: ignore[method-assign]
            Grader(client).grade("q", "e", "a")

    def test_client_without_think_attr_does_not_retry(self):
        client = _NoThinkClient("<think>no verdict</think>")
        with pytest.raises(GraderUnavailableError):
            Grader(client).grade("q", "e", "a")
        # One call per unparseable-verdict attempt and no more: a client with no
        # `think` toggle never takes the think-disabled retry within an attempt.
        assert client.calls == 2
        assert not hasattr(client, "think")

    def test_think_restored_even_if_retry_raises(self):
        client = _ThinkingGraderClient()

        def boom(prompt):
            client.calls.append(prompt)
            if client.think is False:
                raise RuntimeError("provider down")
            return "<think>nothing</think>"

        client.generate = boom  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="provider down"):
            Grader(client).grade("q", "e", "a")
        assert client.think is None  # restored despite the exception


class TestGraderPromptRegistry:
    """The judge prompt is externalized (RFC-008 A2) but the instrument is unchanged."""

    @staticmethod
    def _legacy_prompt(question: str, expected: str, actual: str) -> str:
        # The exact f-string grader.py used before the prompt was externalized.
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

    def test_prompt_is_byte_identical_to_legacy(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 1, "reason": "ok"}'
        Grader(client).grade("What is 2+2?", "4", "4")
        client.generate.assert_called_once_with(
            self._legacy_prompt("What is 2+2?", "4", "4")
        )

    def test_prompt_id_is_registered_identity(self):
        from rfc.grader import GRADER_PROMPT_ID

        assert GRADER_PROMPT_ID == "grader.default_judge"

    def test_env_override_swaps_the_prompt(self, tmp_path, monkeypatch):
        override = tmp_path / "judge.txt"
        override.write_text("VARIANT {question} :: {actual}\n", encoding="utf-8")
        monkeypatch.setenv("RFC_GRADER_PROMPT", str(override))

        client = MagicMock()
        client.generate.return_value = '{"score": 0.5, "reason": "x"}'
        Grader(client).grade("Q?", "E", "A")

        sent = client.generate.call_args.args[0]
        assert sent == "\nVARIANT Q? :: A\n"

    def test_falls_back_when_override_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RFC_GRADER_PROMPT", str(tmp_path / "absent.txt"))
        client = MagicMock()
        client.generate.return_value = '{"score": 1, "reason": "ok"}'
        Grader(client).grade("What is 2+2?", "4", "4")
        # A missing override falls through to the registered file / in-code fallback.
        client.generate.assert_called_once_with(
            self._legacy_prompt("What is 2+2?", "4", "4")
        )


class TestResolvedGraderProvenance:
    """RFC-008 A3 (#242): the seam that logs what ACTUALLY ran, not the registered coordinate."""

    def test_reflects_env_override_hash_not_registered(self, tmp_path, monkeypatch):
        # Under RFC_GRADER_PROMPT the grader runs a DIFFERENT prompt; the seam must
        # report the OVERRIDE's hash (design's bound A3 criterion), not the file on disk.
        from rfc.grader import (
            GRADER_PROMPT_ID,
            GRADER_VERSION,
            _GRADER_PROMPT_PATH,
            resolved_grader_provenance,
        )
        from rfc.prompt_registry import sha256_hex

        override_text = "VARIANT JUDGE {question} {expected} {actual}\n"
        override = tmp_path / "variant.txt"
        override.write_text(override_text, encoding="utf-8")
        monkeypatch.setenv("RFC_GRADER_PROMPT", str(override))

        prompt_id, prompt_hash, grader_version = resolved_grader_provenance()
        assert prompt_id == GRADER_PROMPT_ID
        assert grader_version == GRADER_VERSION
        assert prompt_hash == sha256_hex(override_text)  # what actually ran
        # ...and it is NOT the registered coordinate.
        registered = _GRADER_PROMPT_PATH.read_text(encoding="utf-8")
        assert prompt_hash != sha256_hex(registered)

    def test_reports_registered_hash_without_override(self, monkeypatch):
        from rfc.grader import (
            _GRADER_PROMPT_PATH,
            _load_grader_prompt_body,
            resolved_grader_provenance,
        )
        from rfc.prompt_registry import sha256_hex

        monkeypatch.delenv("RFC_GRADER_PROMPT", raising=False)
        _pid, prompt_hash, _gver = resolved_grader_provenance()
        # With no override the resolved hash == the registered file's live hash.
        assert prompt_hash == sha256_hex(_load_grader_prompt_body())
        assert prompt_hash == sha256_hex(
            _GRADER_PROMPT_PATH.read_text(encoding="utf-8")
        )

    def test_grader_version_is_package_version(self):
        from rfc import __version__
        from rfc.grader import GRADER_VERSION

        assert GRADER_VERSION == __version__
