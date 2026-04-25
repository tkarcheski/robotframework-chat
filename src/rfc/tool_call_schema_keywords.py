"""Tool/function-call schema accuracy keywords for Robot Framework.

Tests whether an LLM emits a *correctly-typed* function call for a
given task: right tool name, required fields present, no extra fields,
type-correct values, and enum-constrained fields restricted to allowed
options.

The tool schema format mirrors the OpenAI / Anthropic function-calling
convention so test cases stay portable::

    {
        "name": "create_user",
        "description": "Create a new user account.",
        "parameters": {
            "type": "object",
            "properties": {
                "username": {"type": "string"},
                "role": {"type": "string", "enum": ["admin", "viewer"]},
            },
            "required": ["username", "role"],
        },
    }
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterator, List, Optional

from robot.api import logger
from robot.api.deco import keyword

from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data

# Map JSON-schema "type" strings to acceptable Python types.
# bool is intentionally excluded from numeric types — Python's
# ``isinstance(True, int)`` is True, which would silently let
# the model pass a boolean for an integer field.
_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


def _strip_markdown_fence(text: str) -> str:
    fence = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)
    match = fence.search(text.strip())
    if match:
        return match.group(1)
    return text


def _iter_balanced_json_objects(text: str) -> Iterator[str]:
    """Yield every balanced ``{...}`` substring in *text*, in order."""
    depth = 0
    start = -1
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


_ARG_KEYS = ("arguments", "input")


def _try_parse_call(blob: str) -> Optional[Dict[str, Any]]:
    """Parse one balanced JSON blob into a normalized tool call, or None.

    A blob is treated as a tool call only if it has the unambiguous
    ``tool`` key, OR it has a ``name`` plus at least one arguments-shaped
    key (``arguments`` / ``parameters`` / ``input``).  Bare ``{"name":
    "..."}`` metadata blobs are rejected so the caller can keep scanning
    for the real call.
    """
    try:
        parsed = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None

    # Unwrap {"function": {...}} / {"tool_call": {...}} / {"tool_use": {...}} envelopes.
    for wrapper in ("function", "tool_call", "tool_use"):
        if wrapper in parsed and isinstance(parsed[wrapper], dict):
            parsed = parsed[wrapper]
            break

    has_tool_key = isinstance(parsed.get("tool"), str) and parsed["tool"]
    has_args_key = any(k in parsed for k in _ARG_KEYS)
    name = parsed.get("tool") or parsed.get("name")
    if not isinstance(name, str) or not name:
        return None
    if not has_tool_key and not has_args_key:
        # Bare {"name": "..."} — likely metadata, not a call.
        return None

    args: Any = {}
    for key in _ARG_KEYS:
        if key in parsed:
            args = parsed[key]
            break
    if isinstance(args, str):
        # OpenAI emits arguments as a JSON string; parse it.
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return None
    if not isinstance(args, dict):
        args = {}

    return {"tool": name, "arguments": args}


def extract_tool_call(response: str) -> Optional[Dict[str, Any]]:
    """Pull a normalized ``{"tool", "arguments"}`` dict from an LLM response.

    Tolerates markdown fences, surrounding prose, OpenAI-style
    ``{"name", "arguments"}``, Anthropic-style ``{"function": {...}}``
    wrappers, and ``arguments`` emitted as a stringified JSON blob.
    Iterates through every balanced ``{...}`` block so that auxiliary
    JSON (thinking traces, metadata) preceding the real call does not
    cause a false ``no_call_detected``.

    Returns None if no recognizable tool call is found.
    """
    if not response:
        return None
    cleaned = _strip_markdown_fence(response)
    for blob in _iter_balanced_json_objects(cleaned):
        call = _try_parse_call(blob)
        if call is not None:
            return call
    return None


def _empty_validation_result() -> Dict[str, Any]:
    return {
        "schema_valid": False,
        "selected_tool": None,
        "unknown_tool": False,
        "no_call_detected": False,
        "missing_required": [],
        "extra_fields": [],
        "type_errors": [],
        "enum_violations": [],
    }


def validate_against_schema(
    call: Optional[Dict[str, Any]],
    tools: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Validate a parsed tool call against a list of tool schemas.

    Returns a result dict with detailed per-category errors and a
    single ``schema_valid`` boolean that is True only when every
    category is clean.
    """
    result = _empty_validation_result()

    if call is None:
        result["no_call_detected"] = True
        return result

    name = call.get("tool")
    args = call.get("arguments", {}) or {}
    result["selected_tool"] = name

    schema = next(
        (t for t in tools if isinstance(t, dict) and t.get("name") == name), None
    )
    if schema is None:
        result["unknown_tool"] = True
        return result

    params = schema.get("parameters", {}) or {}
    if not isinstance(params, dict):
        params = {}
    properties = params.get("properties", {}) or {}
    if not isinstance(properties, dict):
        properties = {}
    required = params.get("required", []) or []
    if not isinstance(required, list):
        required = []

    for field in required:
        if field not in args:
            result["missing_required"].append(field)

    for field in args:
        if field not in properties:
            result["extra_fields"].append(field)

    for field, value in args.items():
        prop = properties.get(field)
        if not prop or not isinstance(prop, dict):
            continue
        expected_type = prop.get("type")
        if expected_type:
            expected_types = (
                expected_type if isinstance(expected_type, list) else [expected_type]
            )
            type_checks = [_TYPE_CHECKS.get(t) for t in expected_types]
            if any(c is None for c in type_checks):
                continue
            checks = [c for c in type_checks if c is not None]
            if not any(check(value) for check in checks):
                result["type_errors"].append(
                    {
                        "field": field,
                        "expected_type": expected_type,
                        "actual_value": value,
                    }
                )
                continue
        allowed = prop.get("enum")
        if allowed is not None and value not in allowed:
            result["enum_violations"].append(
                {"field": field, "allowed": allowed, "actual": value}
            )

    result["schema_valid"] = (
        not result["missing_required"]
        and not result["extra_fields"]
        and not result["type_errors"]
        and not result["enum_violations"]
    )
    return result


def _build_prompt(prompt: str, tools: List[Dict[str, Any]]) -> str:
    schema_block = json.dumps(tools, indent=2)
    return (
        "You have access to the following tools. Each tool's parameters are "
        "described as a JSON Schema:\n"
        f"{schema_block}\n\n"
        f"Task: {prompt}\n\n"
        "Respond with EXACTLY ONE JSON object and nothing else, in the form:\n"
        '{"tool": "<tool_name>", "arguments": {<field>: <value>, ...}}\n'
        "Use only fields defined in the chosen tool's schema. "
        "Use exact enum values where specified. "
        "Do not invent fields or tool names."
    )


class ToolCallSchemaKeywords:
    """Robot Framework keywords for tool-call schema validation."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_retries: int = 2,
    ) -> None:
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))

    @keyword("Evaluate Tool Call")
    def evaluate_tool_call(
        self,
        prompt: str,
        tools: str,
        expected_tool: str = "",
        expected_args: str = "",
    ) -> Dict[str, Any]:
        """Ask the LLM to emit a tool call and grade it against the schemas.

        Args:
            prompt: The task description shown to the LLM.
            tools: JSON list of tool schemas (OpenAI/Anthropic format).
            expected_tool: Optional tool name we expect the model to pick.
                Empty string means any tool from ``tools`` is acceptable.
            expected_args: Optional JSON dict of argument values that the
                model's call should match exactly. Useful for verifying
                that the model extracted the right values from the prompt.

        Returns:
            Dict with keys: schema_valid, tool_correct, selected_tool,
            unknown_tool, no_call_detected, missing_required, extra_fields,
            type_errors, enum_violations, arg_value_errors, response.
        """
        tool_list: List[Dict[str, Any]] = json.loads(tools)
        if not isinstance(tool_list, list):
            result = _empty_validation_result()
            result["response"] = f"tools must be a JSON list, got {type(tool_list).__name__}"
            emit_rfc_data("score", "0.0")
            emit_rfc_data("actual_answer", result["response"])
            emit_rfc_data("expected_answer", "tools: list of schema objects")
            emit_rfc_data("grading_reason", "tools payload not a list")
            return result
        expected_args_dict: Dict[str, Any] = (
            json.loads(expected_args) if expected_args else {}
        )
        if not isinstance(expected_args_dict, dict):
            result = _empty_validation_result()
            result["response"] = f"expected_args must be a JSON object, got {type(expected_args_dict).__name__}"
            emit_rfc_data("score", "0.0")
            emit_rfc_data("actual_answer", result["response"])
            emit_rfc_data("expected_answer", "expected_args: dict or empty string")
            emit_rfc_data("grading_reason", "expected_args payload not a dict")
            return result

        full_prompt = _build_prompt(prompt, tool_list)
        logger.info(
            f"Tool call prompt with {len(tool_list)} tool(s); "
            f"expected={expected_tool or 'any'}"
        )
        response = self.client.generate(full_prompt)
        logger.info(f"LLM response: {response}")

        call = extract_tool_call(response)
        result = validate_against_schema(call, tool_list)

        result["tool_correct"] = (
            (result["selected_tool"] == expected_tool)
            if expected_tool
            else (result["selected_tool"] is not None and not result["unknown_tool"])
        )

        arg_errors: List[Dict[str, Any]] = []
        if expected_args_dict:
            if call is None:
                for field, want in expected_args_dict.items():
                    arg_errors.append(
                        {"field": field, "expected": want, "actual": _MISSING}
                    )
            else:
                for field, want in expected_args_dict.items():
                    got = call.get("arguments", {}).get(field, _MISSING)
                    if got != want:
                        arg_errors.append(
                            {"field": field, "expected": want, "actual": got}
                        )
        result["arg_value_errors"] = arg_errors
        result["response"] = response
        result["overall_pass"] = bool(
            result["schema_valid"] and result["tool_correct"] and not arg_errors
        )

        emit_rfc_data("score", "1.0" if result["overall_pass"] else "0.0")
        emit_rfc_data("actual_answer", response)
        emit_rfc_data(
            "expected_answer",
            f"tool={expected_tool or 'any'} args={expected_args_dict or 'any'}",
        )
        emit_rfc_data(
            "grading_reason",
            (
                f"selected={result['selected_tool']} "
                f"missing={result['missing_required']} "
                f"extra={result['extra_fields']} "
                f"type_errors={len(result['type_errors'])} "
                f"enum_violations={len(result['enum_violations'])} "
                f"arg_value_errors={len(arg_errors)}"
            ),
        )
        return result


_MISSING = object()
