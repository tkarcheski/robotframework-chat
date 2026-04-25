"""Validation of tool calls and results."""

from __future__ import annotations

import json
import re
from typing import Callable

from .agent_tool import ToolCall, ToolResult, ToolSchema


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
            return False, f"Result tool_call_id '{result.tool_call_id}' does not match call.id '{call.id}'"

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
        self.assertions.append(
            ("contains", lambda output: substring in output)
        )

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
