"""LLM-as-judge grader for AgentSkill behavioral test cases.

A skill test case asserts the agent (with a SKILL.md context loaded) exhibits
expected behaviors and avoids prohibited ones, each scored by an LLM judge in
[0.0, 1.0]. Two-phase: one call per must_not behavior (any violation fails the
test), then one batched call over all expected behaviors. A test passes when no
must_not behavior is violated and ``behavior_pass_rate >= pass_threshold``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List

from .thinking import extract_json


def _parse_judge_json(raw: str) -> Any:
    """Parse JSON from a judge response, tolerating wrapping text.

    The judge prompts ask for bare JSON, but models often add prose or
    markdown fences around it. Try a strict parse first so well-formed
    responses with nested arrays are not corrupted by :func:`extract_json`
    (whose non-greedy fallback can truncate at the first ``}``). If the
    strict parse fails, fall back to :func:`extract_json` for thinking-tag
    and markdown-block stripping.
    """
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass
    return json.loads(extract_json(raw))


_TRUTHY_STRINGS = frozenset({"true", "1", "yes"})
_FALSY_STRINGS = frozenset({"false", "0", "no"})


def _coerce_bool(value: Any, default: bool) -> bool:
    """Coerce a JSON-decoded judge value to ``bool`` without truthy-string traps.

    ``bool("false")`` is ``True`` in Python, so a judge returning the *string*
    ``"false"`` for a boolean field would otherwise be misread as ``True``.
    Accept real JSON booleans, numeric 0/1, and the common string spellings of
    true/false; anything unrecognized (including ``None`` for a missing key)
    falls back to *default*.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUTHY_STRINGS:
            return True
        if normalized in _FALSY_STRINGS:
            return False
    return default


@dataclass
class BehaviorResult:
    """Outcome of grading a single behavioral assertion."""

    assertion: str
    passed: bool
    score: float
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.assertion, str):
            raise TypeError(
                f"assertion must be a str, got {type(self.assertion).__name__}"
            )
        if not isinstance(self.passed, bool):
            raise TypeError(f"passed must be a bool, got {type(self.passed).__name__}")
        if not isinstance(self.score, (int, float)):
            raise TypeError(f"score must be a float, got {type(self.score).__name__}")
        self.score = float(self.score)
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"score must be between 0.0 and 1.0, got {self.score}")
        if not isinstance(self.reason, str):
            raise TypeError(f"reason must be a str, got {type(self.reason).__name__}")


@dataclass
class SkillGradeResult:
    """Aggregate outcome of grading a single skill test case."""

    test_id: str
    passed: bool
    behavior_pass_rate: float
    must_not_violations: List[BehaviorResult]
    behavior_results: List[BehaviorResult]
    response: str
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.test_id, str):
            raise TypeError(f"test_id must be a str, got {type(self.test_id).__name__}")
        if not isinstance(self.passed, bool):
            raise TypeError(f"passed must be a bool, got {type(self.passed).__name__}")
        if not isinstance(self.behavior_pass_rate, (int, float)):
            raise TypeError(
                f"behavior_pass_rate must be a float, "
                f"got {type(self.behavior_pass_rate).__name__}"
            )
        self.behavior_pass_rate = float(self.behavior_pass_rate)
        if not 0.0 <= self.behavior_pass_rate <= 1.0:
            raise ValueError(
                f"behavior_pass_rate must be between 0.0 and 1.0, "
                f"got {self.behavior_pass_rate}"
            )


class SkillGrader:
    """LLM-as-judge grader for AgentSkill behavioral assertions."""

    def __init__(self, llm_client: Any, pass_threshold: float = 0.8) -> None:
        if llm_client is None:
            raise TypeError("llm_client must not be None")
        if not 0.0 < pass_threshold <= 1.0:
            raise ValueError(
                f"pass_threshold must be in (0.0, 1.0], got {pass_threshold}"
            )
        self.llm = llm_client
        self.pass_threshold = float(pass_threshold)

    def grade(
        self,
        test_id: str,
        response: str,
        expected_behaviors: List[str],
        must_not: List[str] | None = None,
    ) -> SkillGradeResult:
        """Grade a skill response against expected and prohibited behaviors.

        An empty/whitespace-only response short-circuits to a fail: every
        expected behavior scores 0.0 without invoking the judge, and must_not
        checks are skipped (nothing to violate).
        """
        must_not = list(must_not or [])

        if not response.strip():
            behavior_results = [
                BehaviorResult(
                    assertion=b,
                    passed=False,
                    score=0.0,
                    reason="empty response",
                )
                for b in expected_behaviors
            ]
            return SkillGradeResult(
                test_id=test_id,
                passed=False,
                behavior_pass_rate=0.0,
                must_not_violations=[],
                behavior_results=behavior_results,
                response=response,
                details={"empty_response": True},
            )

        must_not_violations: List[BehaviorResult] = []
        for prohibited in must_not:
            check = self._check_must_not(prohibited, response)
            if not check.passed:
                must_not_violations.append(check)

        behavior_results = self._grade_behaviors_batch(expected_behaviors, response)

        if behavior_results:
            num_passed = sum(1 for r in behavior_results if r.passed)
            behavior_pass_rate = num_passed / len(behavior_results)
        else:
            behavior_pass_rate = 1.0

        passed = not must_not_violations and behavior_pass_rate >= self.pass_threshold

        return SkillGradeResult(
            test_id=test_id,
            passed=passed,
            behavior_pass_rate=round(behavior_pass_rate, 4),
            must_not_violations=must_not_violations,
            behavior_results=behavior_results,
            response=response,
            details={
                "pass_threshold": self.pass_threshold,
                "num_behaviors": len(behavior_results),
                "num_must_not": len(must_not),
            },
        )

    def _check_must_not(self, prohibited: str, response: str) -> BehaviorResult:
        """Check a single prohibited behavior; ``passed=True`` means NOT violated."""
        prompt = f"""You are auditing an AI response for a single prohibited behavior.

Prohibited behavior:
{prohibited}

Response:
{response}

Decide whether the response violates this prohibition.

Respond ONLY with valid JSON. No markdown. No commentary.

Format:
{{
  "violated": true or false,
  "reason": "short explanation"
}}"""

        raw = self.llm.generate(prompt)

        try:
            parsed = _parse_judge_json(raw)
            violated = _coerce_bool(parsed.get("violated"), default=False)
            reason = str(parsed.get("reason", ""))
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            # Conservative fallback: treat malformed judge output as a
            # violation so a broken judge cannot silently mask real
            # prohibited behavior.
            violated = True
            reason = f"judge returned invalid JSON: {raw[:200]}"

        return BehaviorResult(
            assertion=prohibited,
            passed=not violated,
            score=0.0 if violated else 1.0,
            reason=reason,
        )

    def _grade_behaviors_batch(
        self, expected_behaviors: List[str], response: str
    ) -> List[BehaviorResult]:
        """Grade all expected behaviors in a single LLM call."""
        if not expected_behaviors:
            return []

        numbered = "\n".join(f"{i + 1}. {b}" for i, b in enumerate(expected_behaviors))
        prompt = f"""You are an evaluator grading whether an AI response exhibits a set of expected behaviors.

Expected behaviors:
{numbered}

Response:
{response}

For EACH numbered behavior, decide how well the response exhibits it.

Respond ONLY with valid JSON. No markdown. No commentary.

Format:
{{
  "results": [
    {{"index": 1, "score": 0.0 to 1.0, "passed": true or false, "reason": "short explanation"}},
    ...
  ]
}}

A behavior is "passed" when its score is at least 0.7."""

        raw = self.llm.generate(prompt)

        try:
            parsed = _parse_judge_json(raw)
            results = parsed.get("results", [])
            if not isinstance(results, list):
                raise ValueError("results must be a list")
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            return [
                BehaviorResult(
                    assertion=b,
                    passed=False,
                    score=0.0,
                    reason=f"judge returned invalid JSON: {raw[:200]}",
                )
                for b in expected_behaviors
            ]

        by_index: Dict[int, Dict[str, Any]] = {}
        for entry in results:
            if not isinstance(entry, dict):
                continue
            idx = entry.get("index")
            if isinstance(idx, int):
                by_index[idx] = entry

        out: List[BehaviorResult] = []
        for i, behavior in enumerate(expected_behaviors, start=1):
            entry = by_index.get(i)
            if entry is None:
                out.append(
                    BehaviorResult(
                        assertion=behavior,
                        passed=False,
                        score=0.0,
                        reason="judge omitted this behavior",
                    )
                )
                continue
            try:
                score = float(entry.get("score", 0.0))
            except (TypeError, ValueError):
                score = 0.0
            score = max(0.0, min(1.0, score))
            passed = _coerce_bool(entry.get("passed"), default=score >= 0.7)
            reason = str(entry.get("reason", ""))
            out.append(
                BehaviorResult(
                    assertion=behavior,
                    passed=passed,
                    score=score,
                    reason=reason,
                )
            )
        return out
