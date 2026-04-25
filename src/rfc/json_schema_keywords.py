"""Robot Framework keywords for JSON schema validation.

Provides keywords to validate JSON against schemas with retry logic
and support for multiple schema types. Useful for testing LLM output
compliance with expected structured formats.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from robot.api import logger
from robot.api.deco import keyword

from .exceptions import EmptyLLMResponseError
from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data


def _strip_code_fences(text: str) -> str:
    """Extract JSON from markdown code fences if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return text


def _validate_against_schema(
    data: Any, schema: dict[str, Any]
) -> tuple[bool, list[str]]:
    """Validate data against a simple schema.

    Schema format: {"required": ["field1", "field2"], "types": {"field1": "string"}}

    Returns (is_valid, error_messages).
    """
    errors = []

    if not isinstance(data, dict):
        errors.append(f"Expected dict, got {type(data).__name__}")
        return False, errors

    required_fields = schema.get("required", [])
    for field in required_fields:
        if field not in data:
            errors.append(f"Missing required field: {field}")

    type_specs = schema.get("types", {})
    for field, expected_type in type_specs.items():
        if field not in data:
            continue
        value = data[field]
        if expected_type == "string" and not isinstance(value, str):
            errors.append(
                f"Field '{field}' should be string, got {type(value).__name__}"
            )
        elif expected_type == "number" and not isinstance(value, (int, float)):
            errors.append(
                f"Field '{field}' should be number, got {type(value).__name__}"
            )
        elif expected_type == "boolean" and not isinstance(value, bool):
            errors.append(
                f"Field '{field}' should be boolean, got {type(value).__name__}"
            )
        elif expected_type == "array" and not isinstance(value, list):
            errors.append(
                f"Field '{field}' should be array, got {type(value).__name__}"
            )
        elif expected_type == "object" and not isinstance(value, dict):
            errors.append(
                f"Field '{field}' should be object, got {type(value).__name__}"
            )

    return len(errors) == 0, errors


class JSONSchemaKeywords:
    """Robot Framework keywords for JSON schema validation."""

    ROBOT_LIBRARY_SCOPE = "SUITE"

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_retries: int = 5,
    ) -> None:
        timeout = resolve_timeout(timeout)
        self.client: Any = create_provider(
            timeout=timeout, max_retries=int(max_retries)
        )
        self.max_retries = int(max_retries)

    @keyword("Validate JSON With Schema")
    def validate_json_with_schema(
        self,
        response: str,
        schema: str,
        schema_name: str = "custom",
    ) -> float:
        """Validate JSON response against a schema with retry logic.

        Attempts to parse JSON and validate against schema. If parsing fails,
        retries with escalating prompts up to max_retries times.

        Args:
            response: Raw LLM response containing JSON.
            schema: JSON string defining the schema with required fields and types.
            schema_name: Name of the schema for logging.

        Returns:
            Score from 0.0 to 1.0. Factors: parse success (0.5), validation (0.5).
        """
        try:
            schema_obj = json.loads(schema)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Invalid schema: {e}")
            emit_rfc_data("schema_valid", "false")
            return 0.0

        emit_rfc_data("schema_valid", "true")
        emit_rfc_data("schema_name", schema_name)

        text = _strip_code_fences(response)

        try:
            parsed = json.loads(text)
            emit_rfc_data("parse_valid", "true")
        except (json.JSONDecodeError, ValueError) as e:
            logger.warn(f"Parse failed: {e}")
            emit_rfc_data("parse_valid", "false")
            emit_rfc_data("parse_error", str(e))
            return 0.0

        is_valid, errors = _validate_against_schema(parsed, schema_obj)

        if is_valid:
            score = 1.0
            emit_rfc_data("validation_valid", "true")
        else:
            score = 0.5
            emit_rfc_data("validation_valid", "false")
            emit_rfc_data("validation_errors", ";".join(errors))

        emit_rfc_data("score", f"{score:.4f}")
        return score

    @keyword("Validate JSON With Retries")
    def validate_json_with_retries(
        self,
        prompt: str,
        schema: str,
        schema_name: str = "custom",
        max_retries: Optional[int] = None,
    ) -> tuple[float, int]:
        """Ask LLM for JSON and validate against schema with retries.

        Asks LLM to generate JSON matching the schema. If parsing or validation
        fails, retries with escalating prompts.

        Args:
            prompt: Base prompt asking for JSON response.
            schema: JSON string defining the schema.
            schema_name: Name of the schema for logging.
            max_retries: Override default max retries.

        Returns:
            Tuple of (final_score, attempt_number).
        """
        max_retries = int(max_retries) if max_retries is not None else self.max_retries

        retry_hints = [
            "",
            "\n\nPlease provide valid JSON that strictly follows this schema.",
            "\n\nEnsure the JSON is valid and complete. Double-check all required fields.",
            "\n\nThis is your final attempt. Provide valid JSON matching the schema exactly.",
        ]

        last_score = 0.0
        last_attempt = max_retries

        for attempt in range(max_retries):
            hint = retry_hints[min(attempt, len(retry_hints) - 1)]
            full_prompt = prompt + hint

            try:
                response = self.client.generate(full_prompt)
                if not response or not response.strip():
                    logger.warn(f"Attempt {attempt + 1}: Empty response")
                    last_attempt = attempt + 1
                    continue
            except EmptyLLMResponseError:
                logger.warn(f"Attempt {attempt + 1}: Empty LLM response")
                last_attempt = attempt + 1
                continue

            score = self.validate_json_with_schema(response, schema, schema_name)
            last_score = score
            last_attempt = attempt + 1

            emit_rfc_data("attempt_number", str(attempt + 1))
            emit_rfc_data("final_score", f"{score:.4f}")

            if score == 1.0:
                return score, attempt + 1

        return last_score, last_attempt
