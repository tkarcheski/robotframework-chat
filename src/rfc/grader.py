import json
import os
from pathlib import Path

from robot.api import logger

from .models import GradeResult
from .rfc_data import emit_rfc_data
from .thinking import extract_json, parse_thinking


# --- Prompt-registry identity (RFC-008 §6, A2) -------------------------------
# The judge prompt is the measurement instrument, so it is a first-class, versioned
# artifact registered as ``grader.default_judge`` in ``core/config/prompts.yaml``.
# Externalizing the text (below) generalizes the
# ``resources/generative_mutate_prompts.resource`` precedent: the prompt lives in a
# reviewable file, is loaded at runtime (override with ``RFC_GRADER_PROMPT`` to A/B a
# variant), and falls back to a byte-identical in-code copy if the file is unreadable —
# so grading never breaks. ``check_prompt_registry.py`` guards the file against silent
# edits; ``GRADER_PROMPT_ID`` is the seam A3 (#242) uses to log the resolved hash on the spine.
GRADER_PROMPT_ID = "grader.default_judge"

_GRADER_PROMPT_ENV = "RFC_GRADER_PROMPT"
_GRADER_PROMPT_PATH = (
    Path(__file__).resolve().parent / "prompts" / "grader_default_judge.txt"
)

# Keep byte-identical to grader_default_judge.txt (test_prompt_registry.py asserts it).
_GRADER_PROMPT_FALLBACK = (
    "You are an automaed grader.\n"
    "\n"
    "Question:\n"
    "{question}\n"
    "\n"
    "Expected answer:\n"
    "{expected}\n"
    "\n"
    "Model answer:\n"
    "{actual}\n"
    "\n"
    "Rules:\n"
    "- Respond ONLY with valid JSON\n"
    "- No markdown\n"
    "- No commentary\n"
    "- score must be a number between 0.0 and 1.0\n"
    "- use partial credit when the answer is only partially correct\n"
    "\n"
    "Format:\n"
    "{\n"
    '  "score": 0.0 to 1.0,\n'
    '  "reason": "short explanation"\n'
    "}\n"
)


def _load_grader_prompt_body() -> str:
    """Return the judge-prompt template body (with ``{question}``/``{expected}``/``{actual}``).

    Resolution mirrors the generative-listener precedent: an explicit env override, then
    the registered file, then a byte-identical in-code fallback so grading is robust even
    if the file is missing.
    """
    override = os.environ.get(_GRADER_PROMPT_ENV)
    candidates = [Path(override)] if override else []
    candidates.append(_GRADER_PROMPT_PATH)
    for candidate in candidates:
        try:
            return candidate.read_text(encoding="utf-8")
        except OSError:
            continue
    return _GRADER_PROMPT_FALLBACK


class Grader:
    def __init__(self, llm_client):
        if llm_client is None:
            raise TypeError("llm_client must not be None")
        self.llm = llm_client

    def grade(self, question: str, expected: str, actual: str) -> GradeResult:
        for name, val in [
            ("question", question),
            ("expected", expected),
            ("actual", actual),
        ]:
            if not isinstance(val, str):
                raise TypeError(f"{name} must be a str, got {type(val).__name__}")
        if not question.strip():
            raise ValueError("question must be a non-empty string")
        if not actual.strip():
            # Score absent output as 0 directly rather than asking the
            # LLM judge to interpret silence (judges return charitable
            # partial credit and silently inflate pass rates). Return
            # — don't raise — so callers like
            # LLMKeywords.ask_and_grade_with_retry keep their existing
            # retry / EmptyLLMResponseError contract.
            return GradeResult(
                score=0.0,
                reason="Empty response — model produced no content to evaluate",
            )
        # Load the registered judge prompt and substitute the three fields. Plain
        # ``.replace`` (not ``str.format``) keeps the literal JSON braces in the template
        # intact; the leading newline reproduces the historical prompt byte-for-byte.
        body = (
            _load_grader_prompt_body()
            .replace("{question}", question)
            .replace("{expected}", expected)
            .replace("{actual}", actual)
        )
        prompt = "\n" + body

        raw = self._grade_generate(prompt)
        last_metrics = getattr(self.llm, "last_metrics", None)
        if isinstance(last_metrics, dict) and last_metrics:
            emit_rfc_data("llm_metrics", json.dumps(last_metrics))

        # Extract JSON from response (handle thinking tags, markdown, etc.)
        json_text = extract_json(raw)

        try:
            parsed = json.loads(json_text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Grader returned invalid JSON: {raw}") from e

        if "score" not in parsed or "reason" not in parsed:
            raise ValueError(f"Grader JSON missing required fields: {parsed}")

        return GradeResult(
            score=float(parsed["score"]),
            reason=str(parsed["reason"]),
        )

    def _grade_generate(self, prompt: str) -> str:
        """Generate the grader verdict, retrying once with think disabled.

        qwen3.6 on Ollama 0.30+ can emit its whole verdict into a ``thinking``
        field and leave the answer blank (issue #131); the OllamaClient
        surfaces that as an inline ``<think>...</think>`` block, so the usable
        (non-thinking) grader output is empty and JSON parsing would fail. When
        that happens and the client exposes a ``think`` toggle that isn't
        already off, retry once with ``think=False`` to force an inline verdict,
        restoring the prior setting afterwards.
        """
        raw = self.llm.generate(prompt)
        clean, _ = parse_thinking(raw, strip_unclosed=True)
        if clean.strip():
            return raw
        if not hasattr(self.llm, "think") or getattr(self.llm, "think") is False:
            return raw
        original = self.llm.think
        logger.warn(
            "Grader response had no usable (non-thinking) content; retrying "
            "once with think=False to force an inline verdict (issue #131)."
        )
        try:
            self.llm.think = False
            return self.llm.generate(prompt)
        finally:
            self.llm.think = original
