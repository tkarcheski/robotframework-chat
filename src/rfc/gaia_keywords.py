"""GAIA-style tool-use testing keywords for Robot Framework.

Tests whether local LLMs can correctly identify and invoke Robot Framework
custom keywords when presented with tool descriptions in a prompt.  Inspired
by the GAIA benchmark which evaluates LLMs augmented with tools.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple

from robot.api import logger
from robot.api.deco import keyword

from .grader import Grader
from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data
from .thinking import extract_json, parse_thinking


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ToolDefinition:
    """A single tool (keyword) presented to the LLM."""

    name: str
    description: str
    library: str = ""
    arguments: List[Dict[str, Any]] = field(default_factory=list)
    returns: str = ""

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ToolDefinition:
        return cls(
            name=d["name"],
            description=d["description"],
            library=d.get("library", ""),
            arguments=d.get("arguments", []),
            returns=d.get("returns", ""),
        )


@dataclass
class ToolCall:
    """A parsed tool invocation from an LLM response."""

    tool: str
    arguments: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Keyword library
# ---------------------------------------------------------------------------


class GaiaKeywords:
    """Robot Framework keywords for GAIA-style tool-use testing.

    Evaluates whether an LLM can select the correct tool(s) from a set of
    available keyword descriptions and provide correct arguments.
    """

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_retries: int = 2,
    ) -> None:
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))
        self.grader = Grader(self.client)

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    @keyword("Build Tool Prompt")
    def build_tool_prompt(self, tools: List[Dict[str, Any]], question: str) -> str:
        """Build a prompt presenting available tools and a task question.

        Args:
            tools: List of tool definition dicts (name, description, arguments).
            question: The task the LLM must solve by selecting tools.

        Returns:
            A formatted prompt string.

        Raises:
            ValueError: If tools is empty or question is blank.
        """
        if not tools:
            raise ValueError("tools must contain at least one tool definition")
        if not question or not question.strip():
            raise ValueError("question must be a non-empty string")

        tool_defs = [ToolDefinition.from_dict(t) for t in tools]
        sections: list[str] = []

        for i, td in enumerate(tool_defs, 1):
            args_lines: list[str] = []
            for arg in td.arguments:
                req = "required" if arg.get("required") else "optional"
                desc = arg.get("description", "")
                desc_suffix = f" — {desc}" if desc else ""
                args_lines.append(
                    f"    - {arg['name']} ({arg.get('type', 'any')}, {req}){desc_suffix}"
                )
            args_block = "\n".join(args_lines) if args_lines else "    (none)"
            ret = f"  Returns: {td.returns}" if td.returns else ""
            lib = f" ({td.library})" if td.library else ""
            sections.append(
                f"{i}. **{td.name}**{lib}\n"
                f"  Description: {td.description}\n"
                f"  Arguments:\n{args_block}\n"
                f"{ret}"
            )

        tools_text = "\n\n".join(sections)

        return (
            "You are a test automation assistant. You have access to the "
            "following tools:\n\n"
            "## Available Tools\n\n"
            f"{tools_text}\n\n"
            "## Task\n"
            f"{question}\n\n"
            "## Response Format\n"
            "Respond ONLY with a JSON object. No markdown fences, no commentary.\n"
            "If a suitable tool exists, include it in tool_calls. "
            "If no suitable tool is available, return an empty tool_calls list "
            "and explain why in the reasoning field.\n\n"
            "{\n"
            '  "tool_calls": [\n'
            "    {\n"
            '      "tool": "Tool Name",\n'
            '      "arguments": {"arg1": "value1"}\n'
            "    }\n"
            "  ],\n"
            '  "reasoning": "Brief explanation of your choice"\n'
            "}"
        )

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @keyword("Parse Tool Calls")
    def parse_tool_calls(self, response: str) -> List[ToolCall]:
        """Extract tool calls from an LLM response.

        Handles JSON in plain text, markdown code blocks, and thinking tags.

        Args:
            response: Raw LLM response text.

        Returns:
            List of ToolCall objects (empty if parsing fails or no calls).
        """
        clean, _ = parse_thinking(response)
        text = clean if clean.strip() else response

        parsed = _try_parse_json(text)
        if parsed is None:
            # Fallback 1: brace-counting scan iterates EVERY balanced JSON
            # object in the text and prefers the first one containing
            # ``tool_calls``.  Handles "Sure, here is the JSON: {...}",
            # trailing commentary, AND auxiliary objects like
            # `{"note": "..."}` that appear before the real envelope.
            parsed = _find_tool_calls_envelope(text)
        if parsed is None:
            # Fallback 2: markdown code block extraction (legacy).
            json_text = extract_json(text)
            parsed = _try_parse_json(json_text)

        if not isinstance(parsed, dict):
            return []

        raw_calls = parsed.get("tool_calls")
        if not isinstance(raw_calls, list):
            return []

        calls: list[ToolCall] = []
        for item in raw_calls:
            if isinstance(item, dict) and "tool" in item:
                # Coerce non-mapping arguments (null, list, string, etc.) to
                # an empty dict so downstream grading never sees a malformed
                # payload and can score the call cleanly.
                raw_args = item.get("arguments")
                args = raw_args if isinstance(raw_args, dict) else {}
                calls.append(
                    ToolCall(
                        tool=str(item["tool"]),
                        arguments=args,
                    )
                )
        return calls

    # ------------------------------------------------------------------
    # Grading
    # ------------------------------------------------------------------

    @keyword("Grade Tool Selection")
    def grade_tool_selection(
        self,
        expected_tools: List[str],
        actual_calls: List[ToolCall],
    ) -> Dict[str, Any]:
        """Grade whether the LLM selected the correct tool(s) in order.

        Uses multiset (Counter) comparison so that repeated tool calls are
        preserved — tasks legitimately requiring the same tool multiple
        times (e.g. two ``Ask LLM`` steps) are scored on occurrence count,
        not mere presence.

        Args:
            expected_tools: Ordered list of expected tool names (duplicates allowed).
            actual_calls: Parsed ToolCall list from the LLM response.

        Returns:
            Dict with score (0.0–1.0), reason, selected_tools, order_correct.
        """
        from collections import Counter

        actual_names = [c.tool for c in actual_calls]

        if not expected_tools:
            # Edge case: nothing expected
            score = 1.0 if not actual_names else 0.0
            return {
                "score": score,
                "reason": "No tools expected",
                "selected_tools": actual_names,
                "order_correct": True,
            }

        expected_counts = Counter(expected_tools)
        actual_counts = Counter(actual_names)

        # Multiset intersection: how many expected occurrences are matched,
        # capped per-tool so extra actual occurrences never inflate the score.
        matched_total = sum(
            min(count, actual_counts.get(tool, 0))
            for tool, count in expected_counts.items()
        )
        selection_score = matched_total / len(expected_tools)

        all_matched = matched_total == len(expected_tools)

        # Order check only meaningful when every expected occurrence is present.
        order_correct = actual_names == list(expected_tools)
        if all_matched and not order_correct:
            # All occurrences present but wrong order — heavy penalty so that
            # even with perfect arguments (combined 0.5*sel + 0.5*args) the
            # final score sits below the strict multi-step pass threshold.
            selection_score *= 0.5

        reason_parts: list[str] = []
        if all_matched and order_correct:
            reason_parts.append("All tools selected in correct order")
        elif all_matched:
            reason_parts.append("All tools selected but wrong order")
        else:
            missing_mset = expected_counts - actual_counts
            extra_mset = actual_counts - expected_counts
            if missing_mset:
                missing_list = sorted(missing_mset.elements())
                reason_parts.append(f"Missing: {missing_list}")
            if extra_mset:
                extra_list = sorted(extra_mset.elements())
                reason_parts.append(f"Extra: {extra_list}")

        return {
            "score": round(selection_score, 4),
            "reason": "; ".join(reason_parts) if reason_parts else "No match",
            "selected_tools": actual_names,
            "order_correct": order_correct,
        }

    @keyword("Grade Tool Arguments")
    def grade_tool_arguments(
        self,
        expected_args: Dict[str, Any],
        actual_call: ToolCall,
    ) -> Dict[str, Any]:
        """Grade whether the LLM provided correct arguments.

        Args:
            expected_args: Dict of expected argument key-value pairs.
            actual_call: The ToolCall to evaluate.

        Returns:
            Dict with score (0.0–1.0), reason, matched_keys, missing_keys.
        """
        if not expected_args:
            return {
                "score": 1.0,
                "reason": "No arguments expected",
                "matched_keys": [],
                "missing_keys": [],
            }

        actual = actual_call.arguments
        matched: list[str] = []
        mismatched: list[str] = []
        missing: list[str] = []

        for key, expected_val in expected_args.items():
            if key not in actual:
                missing.append(key)
                continue
            actual_val = actual[key]
            if _values_match(expected_val, actual_val):
                matched.append(key)
            else:
                mismatched.append(key)

        total = len(expected_args)
        score = len(matched) / total

        reason_parts: list[str] = []
        if matched:
            reason_parts.append(f"Matched: {matched}")
        if mismatched:
            reason_parts.append(f"Wrong values: {mismatched}")
        if missing:
            reason_parts.append(f"Missing: {missing}")

        return {
            "score": round(score, 4),
            "reason": "; ".join(reason_parts),
            "matched_keys": matched,
            "missing_keys": missing,
        }

    @keyword("Grade Tool Refusal")
    def grade_tool_refusal(self, response: str) -> Dict[str, Any]:
        """Grade whether the LLM *explicitly* refused to call a tool.

        A correct refusal requires either:

        1. A valid JSON response with an empty ``tool_calls`` list AND a
           non-empty ``reasoning`` field explaining why no tool fits, OR
        2. A free-text response containing an explicit refusal phrase
           (e.g. "no tool", "cannot", "unable to", "none of") that names
           the lack of a suitable tool.

        Garbage / unparsable text and empty responses are NOT counted as
        refusals — they're scored 0.0 because we can't distinguish a
        deliberate refusal from a model crash or empty completion.

        Args:
            response: Raw LLM response text.

        Returns:
            Dict with score (0.0 or 1.0) and reason.
        """
        if not response or not response.strip():
            return {
                "score": 0.0,
                "reason": "Empty response — not an explicit refusal",
            }

        calls = self.parse_tool_calls(response)
        if calls:
            return {
                "score": 0.0,
                "reason": f"Incorrectly called {len(calls)} tool(s): "
                f"{[c.tool for c in calls]}",
            }

        # No tool calls extracted.  Check whether the response is a valid
        # JSON refusal envelope or contains an explicit refusal phrase.
        clean, _ = parse_thinking(response)
        text = clean if clean.strip() else response

        parsed = _try_parse_json(text)
        if parsed is None:
            parsed = _find_tool_calls_envelope(text)

        if isinstance(parsed, dict) and "tool_calls" in parsed:
            raw_calls = parsed.get("tool_calls")
            # Enforce the documented contract: tool_calls must be a *list*
            # AND must be empty.  A non-list value (string, dict, null) or
            # any non-empty list — even one full of malformed call items —
            # is not a refusal, regardless of the reasoning text.
            if not isinstance(raw_calls, list):
                return {
                    "score": 0.0,
                    "reason": (
                        f"tool_calls must be a list, got {type(raw_calls).__name__}"
                    ),
                }
            if raw_calls:
                return {
                    "score": 0.0,
                    "reason": (
                        f"tool_calls is non-empty ({len(raw_calls)} item(s)) "
                        "— not a refusal"
                    ),
                }
            reasoning = parsed.get("reasoning", "")
            if isinstance(reasoning, str) and reasoning.strip():
                return {
                    "score": 1.0,
                    "reason": "Explicit JSON refusal with reasoning",
                }
            return {
                "score": 0.0,
                "reason": "Empty tool_calls but no reasoning provided",
            }

        # Plain-text fallback: look for refusal phrases.
        if _looks_like_refusal(text):
            return {
                "score": 1.0,
                "reason": "Plain-text refusal phrase detected",
            }
        return {
            "score": 0.0,
            "reason": "No tool calls and no explicit refusal — unparseable",
        }

    # ------------------------------------------------------------------
    # End-to-end test runner
    # ------------------------------------------------------------------

    @keyword("Run GAIA Tool Use Test")
    def run_gaia_tool_use_test(
        self,
        tools: List[Dict[str, Any]],
        question: str,
        expected_calls: List[Dict[str, Any]],
        max_retries: int = 3,
    ) -> Tuple[float, str, str]:
        """End-to-end GAIA tool-use test: prompt → ask → grade.

        Args:
            tools: Tool definitions to present.
            question: Task question for the LLM.
            expected_calls: Expected tool call dicts (tool + arguments).
                Empty list means the LLM should refuse.
            max_retries: Max retry attempts on failure.

        Returns:
            Tuple of (score, reason, raw_response).
        """
        max_retries = int(max_retries)
        prompt = self.build_tool_prompt(tools, question)
        logger.info(f"GAIA prompt:\n{prompt}")

        best_score = -1.0  # sentinel: any real score updates on first attempt
        best_reason = ""
        best_response = ""

        for attempt in range(1 + max_retries):
            raw_response = self.client.generate(prompt)
            clean_response, thinking = parse_thinking(raw_response)
            logger.info(f"LLM response (attempt {attempt + 1}):\n{clean_response}")
            emit_rfc_data("actual_answer", clean_response)

            if thinking is not None:
                emit_rfc_data("thinking_text", thinking)

            if self.client.last_metrics is not None:
                emit_rfc_data("llm_metrics", json.dumps(self.client.last_metrics))

            # Refusal scenario
            if not expected_calls:
                result = self.grade_tool_refusal(clean_response)
                score = result["score"]
                reason = result["reason"]
            else:
                actual_calls = self.parse_tool_calls(clean_response)
                expected_tool_names = [c["tool"] for c in expected_calls]

                sel_result = self.grade_tool_selection(
                    expected_tool_names, actual_calls
                )
                sel_score = sel_result["score"]

                # Grade arguments for each expected call.  Pair each expected
                # occurrence with a *distinct* actual call by consuming matches
                # left-to-right — preserves multiplicity for workflows that
                # legitimately reuse the same tool with different arguments.
                arg_scores: list[float] = []
                remaining = list(actual_calls)
                for exp in expected_calls:
                    match_idx = next(
                        (i for i, c in enumerate(remaining) if c.tool == exp["tool"]),
                        None,
                    )
                    if match_idx is not None:
                        actual = remaining.pop(match_idx)
                        arg_result = self.grade_tool_arguments(
                            exp.get("arguments", {}), actual
                        )
                        arg_scores.append(arg_result["score"])
                    else:
                        arg_scores.append(0.0)

                avg_arg_score = sum(arg_scores) / len(arg_scores) if arg_scores else 0.0
                score = round(0.5 * sel_score + 0.5 * avg_arg_score, 4)
                reason = (
                    f"selection={sel_score:.2f}, arguments={avg_arg_score:.2f}"
                    f" | {sel_result['reason']}"
                )

            emit_rfc_data("score", str(score))
            emit_rfc_data(
                "expected_answer",
                json.dumps(expected_calls) if expected_calls else "refusal",
            )
            emit_rfc_data("grading_reason", reason)

            if score >= 1.0:
                logger.info(f"GAIA test passed on attempt {attempt + 1}")
                return score, reason, raw_response

            if score > best_score:
                best_score = score
                best_reason = reason
                best_response = raw_response

            if attempt < max_retries:
                logger.warn(
                    f"GAIA test score={score:.2f} on attempt {attempt + 1}, "
                    f"retrying ({max_retries - attempt} left)"
                )

        logger.info(
            f"GAIA test finished with best score={best_score:.2f} "
            f"after {max_retries + 1} attempts"
        )
        return best_score, best_reason, best_response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _try_parse_json(text: str) -> Any:
    """Try to parse JSON from text, returning None on failure."""
    text = text.strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _iter_balanced_json_objects(text: str) -> Iterator[str]:
    """Yield every balanced JSON object substring in *text*, in order.

    Walks the string character by character, tracking string-literal state
    (with backslash escapes) and brace depth, yielding each complete
    top-level ``{...}`` block as a substring.

    Handles common LLM response formats like:
        "Sure, here is the JSON: {\"tool_calls\": [...]}"
        "{\"note\":\"...\"} {\"tool_calls\": [...]}"
        "{\"tool_calls\": [...]}\n\nLet me know if you need more!"
    where ``json.loads`` on the whole string fails but one or more valid
    objects are embedded inside it.
    """
    start = -1
    depth = 0
    in_string = False
    escape = False

    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    yield text[start : i + 1]
                    start = -1


def _find_tool_calls_envelope(text: str) -> Any:
    """Scan *text* for a JSON object containing a ``tool_calls`` key.

    Returns the first balanced object that parses as a dict with a
    ``tool_calls`` key (preferred over auxiliary objects like
    ``{"note": ...}``).  Falls back to the first parseable dict if no
    envelope is found, or ``None`` if nothing parses.
    """
    first_dict: Any = None
    for candidate in _iter_balanced_json_objects(text):
        parsed = _try_parse_json(candidate)
        if not isinstance(parsed, dict):
            continue
        if "tool_calls" in parsed:
            return parsed
        if first_dict is None:
            first_dict = parsed
    return first_dict


# Phrases that explicitly signal "no tool fits this task".  Generic inability
# wording (e.g. "unable to", "I cannot") is intentionally excluded — those
# can appear in responses that still recommend a tool, which would inflate
# refusal metrics.  Each phrase here must name the lack of a *tool*.
_REFUSAL_PHRASES = (
    "no tool",
    "no suitable tool",
    "no available tool",
    "no available keyword",
    "none of the available tools",
    "none of the tools",
    "no tool can",
    "no tool is",
    "no tool that",
    "cannot be done with the available tools",
    "cannot be done with any of the available tools",
    "cannot be accomplished with the available tools",
    "no keyword",
)


# Word-boundary patterns that indicate the model is recommending a tool —
# used to reject mixed-message responses that contain a refusal phrase but
# still suggest invoking a keyword.
_TOOL_RECOMMENDATION_PATTERNS = (
    re.compile(r"\buse\s+\w", re.IGNORECASE),
    re.compile(r"\bcall\s+\w", re.IGNORECASE),
    re.compile(r"\binvoke\s+\w", re.IGNORECASE),
    re.compile(r"\btry\s+using\b", re.IGNORECASE),
    re.compile(r"\byou\s+should\s+use\b", re.IGNORECASE),
)


def _looks_like_refusal(text: str) -> bool:
    """True if *text* contains an explicit no-tool refusal phrase.

    Requires both:
    1. A phrase from :data:`_REFUSAL_PHRASES` that names a missing tool, AND
    2. The response must NOT also recommend invoking any tool by name —
       this rejects mixed messages like "I am unable to verify this,
       but use Ask LLM..." which inflate refusal metrics despite
       recommending a tool.
    """
    lowered = text.lower()
    if not any(phrase in lowered for phrase in _REFUSAL_PHRASES):
        return False
    # Reject mixed messages that still recommend invoking a tool — match
    # on word boundaries so substrings like "becaUSE " do not trigger.
    for pattern in _TOOL_RECOMMENDATION_PATTERNS:
        if pattern.search(text):
            return False
    return True


def _values_match(expected: Any, actual: Any) -> bool:
    """Compare expected and actual values.

    Strings are matched case-sensitively after whitespace trimming so that
    code, model IDs, and other tokens with semantic case differences are
    not silently considered equivalent.  Numeric values are coerced from
    strings (e.g. ``"0.7" == 0.7``) since LLMs often serialise numbers
    inside JSON strings.
    """
    if expected == actual:
        return True

    # Numeric coercion: "0.7" == 0.7, "1024" == 1024
    try:
        if isinstance(expected, (int, float)) and isinstance(actual, str):
            return float(expected) == float(actual)
        if isinstance(actual, (int, float)) and isinstance(expected, str):
            return float(actual) == float(expected)
    except (ValueError, TypeError):
        pass

    # Case-sensitive string comparison (only whitespace is trimmed).
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip() == actual.strip()

    return False
