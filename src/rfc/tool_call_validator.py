"""Validation of tool calls and results."""

from __future__ import annotations

import json
import re
from typing import Callable

from math import isfinite

from .agent_tool import ToolCall, ToolResult, ToolSchema

_JSON_SCHEMA_TYPE_NAMES = frozenset(
    {"string", "integer", "number", "boolean", "object", "array", "null"}
)


def _value_matches_json_schema_type(value: object, type_name: str) -> bool:
    """True iff `value` matches the named JSON Schema primitive type.

    Per https://json-schema.org/draft/2020-12/json-schema-validation#name-type:
    - "integer" matches any number with a zero fractional part, so integral
      floats like 1.0 are valid. Booleans are NOT valid (JSON Schema treats
      bool and int as distinct types even though bool ⊂ int in Python).
    - "number" matches int or float, but again excludes bool.
    """
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "integer":
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        if isinstance(value, float):
            return isfinite(value) and value.is_integer()
        return False
    if type_name == "number":
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        if isinstance(value, float):
            return isfinite(value)
        return False
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "array":
        # JSON arrays deserialise to lists; tuples are not JSON arrays.
        return isinstance(value, list)
    if type_name == "null":
        return value is None
    return False


class ToolCallValidator:
    """Validate tool calls against schemas, ordering, and results."""

    def __init__(self) -> None:
        self.schemas: dict[str, ToolSchema] = {}

    def register_tool(self, schema: ToolSchema) -> None:
        """Register tool with its schema."""
        self.schemas[schema.name] = schema

    def validate_call_schema(self, call: ToolCall) -> tuple[bool, str]:
        """Check call parameters against registered schema."""
        if call.tool_name not in self.schemas:
            return False, f"Tool '{call.tool_name}' not registered"

        schema = self.schemas[call.tool_name]

        # Check required parameters are present
        for required_param in schema.required:
            if required_param not in call.arguments:
                return False, f"Missing required parameter: {required_param}"

        # Check declared parameter types match argument types
        for param_name, param_value in call.arguments.items():
            param_schema = schema.parameters.get(param_name)
            if not isinstance(param_schema, dict):
                continue
            declared = param_schema.get("type")
            # JSON Schema allows `type` to be a string OR a list of strings
            # (a union); the instance must match at least one listed type.
            if isinstance(declared, str):
                candidates: list[str] = [declared]
            elif isinstance(declared, list) and all(
                isinstance(t, str) for t in declared
            ):
                candidates = list(declared)
            else:
                continue
            # Drop any unknown type names so they don't force a false negative;
            # if none are recognised, fall through (untyped, like before).
            known = [t for t in candidates if t in _JSON_SCHEMA_TYPE_NAMES]
            if not known:
                continue
            if not any(_value_matches_json_schema_type(param_value, t) for t in known):
                expected = known[0] if len(known) == 1 else f"one of {known}"
                return False, (
                    f"Parameter '{param_name}' expected {expected}, "
                    f"got {type(param_value).__name__}"
                )

        return True, ""

    def validate_call_sequence(
        self,
        calls: list[ToolCall],
        expected_order: list[str] | None = None,
    ) -> tuple[bool, str]:
        """Verify calls appeared in expected order."""
        if expected_order is None:
            return True, ""

        if not calls:
            return False, "No tool calls to validate"

        actual_order = [c.tool_name for c in calls]
        if actual_order != expected_order:
            return False, f"Expected {expected_order}, got {actual_order}"

        return True, ""

    def validate_result(
        self,
        call: ToolCall,
        result: ToolResult,
        expected_type: type | None = None,
    ) -> tuple[bool, str]:
        """Check result matches expectations."""
        if result.tool_call_id != call.id:
            return (
                False,
                f"Result tool_call_id '{result.tool_call_id}' does not match call.id '{call.id}'",
            )

        if not result.success:
            return False, f"Tool call failed: {result.error}"

        if expected_type is not None:
            try:
                if expected_type is int:
                    int(result.output)
                elif expected_type is dict:
                    parsed = json.loads(result.output)
                    if not isinstance(parsed, dict):
                        return False, f"Expected dict, got {type(parsed).__name__}"
            except (ValueError, json.JSONDecodeError) as e:
                return False, f"Result type mismatch: {e}"

        return True, ""


class ToolResultValidator:
    """Validate tool results against assertions."""

    def __init__(self, confidence_threshold: float = 0.8) -> None:
        self.confidence_threshold = confidence_threshold
        self.assertions: list[tuple[str, Callable[[str], bool]]] = []

    def assert_output_contains(self, substring: str) -> None:
        """Assert result output contains substring."""
        self.assertions.append(("contains", lambda output: substring in output))

    def assert_output_matches_regex(self, pattern: str) -> None:
        """Assert result matches regex."""
        self.assertions.append(
            ("regex", lambda output: re.search(pattern, output) is not None)
        )

    def assert_result_valid_json(self) -> None:
        """Assert result is valid JSON."""

        def is_valid_json(output: str) -> bool:
            try:
                json.loads(output)
                return True
            except (json.JSONDecodeError, ValueError):
                return False

        self.assertions.append(("json", is_valid_json))

    def validate(self, result: ToolResult) -> tuple[bool, list[str]]:
        """Run all assertions, return pass/failures."""
        failures: list[str] = []
        for name, assertion in self.assertions:
            try:
                if not assertion(result.output):
                    failures.append(f"Assertion '{name}' failed")
            except Exception as e:
                failures.append(f"Assertion '{name}' error: {e}")

        return len(failures) == 0, failures
