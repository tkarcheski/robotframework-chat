"""Robot Framework keywords for JSON schema validation.

Validates LLM JSON output against a lightweight schema (required fields and
field types) with retry-on-failure support for measuring parse failure rates.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from robot.api import logger
from robot.api.deco import keyword

from .exceptions import EmptyLLMResponseError
from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data
from .thinking import extract_json

_TYPE_CHECKS: dict[str, tuple[type | tuple[type, ...], str]] = {
    "string": (str, "string"),
    "number": ((int, float), "number"),
    "boolean": (bool, "boolean"),
    "array": (list, "array"),
    "object": (dict, "object"),
}

_RETRY_HINTS = [
    "",
    "\n\nPlease provide valid JSON that strictly follows this schema.",
    "\n\nEnsure the JSON is valid and complete. Double-check all required fields.",
    "\n\nThis is your final attempt. Provide valid JSON matching the schema exactly.",
]


def _validate_against_schema(
    data: Any, schema: dict[str, Any]
) -> tuple[bool, list[str]]:
    """Validate data against a simple {"required": [...], "types": {...}} schema."""
    if not isinstance(data, dict):
        return False, [f"Expected dict, got {type(data).__name__}"]

    errors: list[str] = []
    for field in schema.get("required", []):
        if field not in data:
            errors.append(f"Missing required field: {field}")

    for field, expected_type in schema.get("types", {}).items():
        if field not in data:
            continue
        check = _TYPE_CHECKS.get(expected_type)
        if check is None:
            continue
        py_type, label = check
        value = data[field]
        if not isinstance(value, py_type):
            errors.append(
                f"Field '{field}' should be {label}, got {type(value).__name__}"
            )
        elif expected_type == "number" and isinstance(value, bool):
            errors.append(f"Field '{field}' should be {label}, got boolean")

    return not errors, errors


def _validate_parsed(
    response: str, schema_obj: dict[str, Any], schema_name: str
) -> float:
    """Parse `response` and validate against an already-parsed schema object."""
    emit_rfc_data("schema_valid", "true")
    emit_rfc_data("schema_name", schema_name)

    text = extract_json(response)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warn(f"Parse failed: {e}")
        emit_rfc_data("parse_valid", "false")
        emit_rfc_data("parse_error", str(e))
        return 0.0

    emit_rfc_data("parse_valid", "true")
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

    def _get_configured_client(self) -> Any:
        """Get the currently configured LLM client from LLMKeywords, or fall back to self.client.

        In Robot Framework suite execution, this returns the LLMKeywords instance's
        client, which respects LLM.Set LLM Parameters() configuration. In unit tests
        or non-Robot contexts, falls back to self.client.
        """
        try:
            from robot.libraries.BuiltIn import BuiltIn  # type: ignore[import-not-found]

            llm_library = BuiltIn().get_library_instance("LLM")
            return llm_library.client  # type: ignore[attr-defined]
        except Exception:
            return self.client

    @keyword("Validate JSON With Schema")
    def validate_json_with_schema(
        self,
        response: str,
        schema: str,
        schema_name: str = "custom",
    ) -> float:
        """Parse `response` as JSON and validate against `schema`.

        Returns 1.0 for full pass, 0.5 for valid parse with schema errors,
        and 0.0 for parse failure or invalid schema.
        """
        try:
            schema_obj = json.loads(schema)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Invalid schema: {e}")
            emit_rfc_data("schema_valid", "false")
            return 0.0

        # Validate schema structure: both "required" and "types" must be dicts/lists
        if not isinstance(schema_obj, dict):
            logger.error("Schema must be a JSON object")
            emit_rfc_data("schema_valid", "false")
            return 0.0

        if "types" in schema_obj and not isinstance(schema_obj["types"], dict):
            logger.error("Schema 'types' field must be a JSON object, not a list")
            emit_rfc_data("schema_valid", "false")
            return 0.0

        if "required" in schema_obj and not isinstance(schema_obj["required"], list):
            logger.error("Schema 'required' field must be a JSON array")
            emit_rfc_data("schema_valid", "false")
            return 0.0

        return _validate_parsed(response, schema_obj, schema_name)

    @keyword("Validate JSON With Retries")
    def validate_json_with_retries(
        self,
        prompt: str,
        schema: str,
        schema_name: str = "custom",
        max_retries: Optional[int] = None,
    ) -> tuple[float, int]:
        """Ask the LLM for JSON and validate it, retrying on failure.

        Returns (final_score, attempt_number). Stops early on a perfect score.
        Uses the configured LLM client from LLMKeywords if available.
        """
        retries = int(max_retries) if max_retries is not None else self.max_retries

        try:
            schema_obj = json.loads(schema)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Invalid schema: {e}")
            emit_rfc_data("schema_valid", "false")
            return 0.0, 0

        # Validate schema structure: both "required" and "types" must be dicts/lists
        if not isinstance(schema_obj, dict):
            logger.error("Schema must be a JSON object")
            emit_rfc_data("schema_valid", "false")
            return 0.0, 0

        if "types" in schema_obj and not isinstance(schema_obj["types"], dict):
            logger.error("Schema 'types' field must be a JSON object, not a list")
            emit_rfc_data("schema_valid", "false")
            return 0.0, 0

        if "required" in schema_obj and not isinstance(schema_obj["required"], list):
            logger.error("Schema 'required' field must be a JSON array")
            emit_rfc_data("schema_valid", "false")
            return 0.0, 0

        client = self._get_configured_client()
        last_score = 0.0
        for attempt in range(1, retries + 1):
            full_prompt = prompt + _RETRY_HINTS[min(attempt - 1, len(_RETRY_HINTS) - 1)]
            response = _generate_or_skip(client.generate, full_prompt, attempt)
            if response is None:
                continue

            last_score = _validate_parsed(response, schema_obj, schema_name)
            emit_rfc_data("attempt_number", str(attempt))
            emit_rfc_data("final_score", f"{last_score:.4f}")

            if last_score == 1.0:
                return last_score, attempt

        return last_score, retries


def _generate_or_skip(
    generate: Callable[[str], str], prompt: str, attempt: int
) -> Optional[str]:
    """Call `generate`; return None and log if response is empty or LLM raises."""
    try:
        response = generate(prompt)
    except EmptyLLMResponseError:
        logger.warn(f"Attempt {attempt}: Empty LLM response")
        return None
    if not response or not response.strip():
        logger.warn(f"Attempt {attempt}: Empty response")
        return None
    return response
