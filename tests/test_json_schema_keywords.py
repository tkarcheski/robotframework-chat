"""Tests for rfc.json_schema_keywords.JSONSchemaKeywords."""

from unittest.mock import MagicMock, patch

from rfc.json_schema_keywords import (
    JSONSchemaKeywords,
    _strip_code_fences,
    _validate_against_schema,
)


class TestStripCodeFences:
    def test_strips_json_code_fence(self) -> None:
        """Code fence with json type is stripped."""
        text = '```json\n{"key": "value"}\n```'
        result = _strip_code_fences(text)
        assert result == '{"key": "value"}'

    def test_strips_unmarked_code_fence(self) -> None:
        """Code fence without type is stripped."""
        text = '```\n{"key": "value"}\n```'
        result = _strip_code_fences(text)
        assert result == '{"key": "value"}'

    def test_no_code_fence_returns_original(self) -> None:
        """Text without code fence is returned unchanged."""
        text = '{"key": "value"}'
        result = _strip_code_fences(text)
        assert result == '{"key": "value"}'

    def test_preserves_newlines_in_json(self) -> None:
        """Newlines within JSON are preserved."""
        text = '```json\n{"key": "value",\n"other": "data"}\n```'
        result = _strip_code_fences(text)
        assert '{"key": "value",' in result
        assert '"other": "data"}' in result

    def test_strips_leading_trailing_whitespace(self) -> None:
        """Leading and trailing whitespace is removed."""
        text = '  ```json\n  {"key": "value"}  \n```  '
        result = _strip_code_fences(text)
        assert result == '{"key": "value"}'


class TestValidateAgainstSchema:
    def test_validates_required_fields_present(self) -> None:
        """Data with all required fields passes."""
        schema = {"required": ["name", "age"]}
        data = {"name": "Alice", "age": 30}
        is_valid, errors = _validate_against_schema(data, schema)
        assert is_valid
        assert errors == []

    def test_rejects_missing_required_fields(self) -> None:
        """Data missing required fields fails."""
        schema = {"required": ["name", "age"]}
        data = {"name": "Alice"}
        is_valid, errors = _validate_against_schema(data, schema)
        assert not is_valid
        assert "Missing required field: age" in errors

    def test_validates_field_types(self) -> None:
        """Field types are validated correctly."""
        schema = {
            "required": ["name", "age"],
            "types": {"name": "string", "age": "number"},
        }
        data = {"name": "Alice", "age": 30}
        is_valid, errors = _validate_against_schema(data, schema)
        assert is_valid
        assert errors == []

    def test_rejects_wrong_field_type(self) -> None:
        """Wrong field type causes validation to fail."""
        schema = {"types": {"age": "string"}}
        data = {"age": 30}
        is_valid, errors = _validate_against_schema(data, schema)
        assert not is_valid
        assert any("should be string" in e for e in errors)

    def test_rejects_non_dict(self) -> None:
        """Non-dict data fails validation."""
        schema = {"required": ["name"]}
        data = ["Alice"]
        is_valid, errors = _validate_against_schema(data, schema)
        assert not is_valid
        assert "Expected dict" in errors[0]

    def test_allows_extra_fields(self) -> None:
        """Extra fields beyond schema don't cause failure."""
        schema = {"required": ["name"]}
        data = {"name": "Alice", "age": 30, "email": "alice@example.com"}
        is_valid, errors = _validate_against_schema(data, schema)
        assert is_valid

    def test_type_validation_for_boolean(self) -> None:
        """Boolean type is correctly validated."""
        schema = {"types": {"active": "boolean"}}
        data = {"active": True}
        is_valid, errors = _validate_against_schema(data, schema)
        assert is_valid

        data = {"active": "true"}
        is_valid, errors = _validate_against_schema(data, schema)
        assert not is_valid

    def test_type_validation_for_array(self) -> None:
        """Array type is correctly validated."""
        schema = {"types": {"items": "array"}}
        data = {"items": [1, 2, 3]}
        is_valid, errors = _validate_against_schema(data, schema)
        assert is_valid

        data = {"items": "not an array"}
        is_valid, errors = _validate_against_schema(data, schema)
        assert not is_valid

    def test_type_validation_for_object(self) -> None:
        """Object type is correctly validated."""
        schema = {"types": {"metadata": "object"}}
        data = {"metadata": {"key": "value"}}
        is_valid, errors = _validate_against_schema(data, schema)
        assert is_valid

        data = {"metadata": ["not", "an", "object"]}
        is_valid, errors = _validate_against_schema(data, schema)
        assert not is_valid

    def test_ignores_missing_optional_fields(self) -> None:
        """Missing optional fields don't trigger type validation."""
        schema = {"types": {"optional_field": "string"}}
        data = {"other": "value"}
        is_valid, errors = _validate_against_schema(data, schema)
        assert is_valid


class TestValidateJsonWithSchema:
    def setup_method(self) -> None:
        self.jk = JSONSchemaKeywords()

    def test_invalid_schema_returns_zero(self) -> None:
        """Invalid schema JSON returns 0.0."""
        with patch("rfc.json_schema_keywords.emit_rfc_data") as mock_emit:
            schema = "not valid json"
            response = '{"name": "Alice"}'
            score = self.jk.validate_json_with_schema(response, schema)
            assert score == 0.0
            mock_emit.assert_any_call("schema_valid", "false")

    def test_valid_schema_recorded(self) -> None:
        """Valid schema is recorded."""
        with patch("rfc.json_schema_keywords.emit_rfc_data") as mock_emit:
            schema = '{"required": ["name"]}'
            response = '{"name": "Alice"}'
            self.jk.validate_json_with_schema(response, schema)
            mock_emit.assert_any_call("schema_valid", "true")

    def test_parse_failure_returns_zero(self) -> None:
        """Unparseable JSON returns 0.0."""
        with patch("rfc.json_schema_keywords.emit_rfc_data") as mock_emit:
            schema = '{"required": []}'
            response = "not json"
            score = self.jk.validate_json_with_schema(response, schema)
            assert score == 0.0
            mock_emit.assert_any_call("parse_valid", "false")

    def test_parse_success_recorded(self) -> None:
        """Successful parse is recorded."""
        with patch("rfc.json_schema_keywords.emit_rfc_data") as mock_emit:
            schema = '{"required": []}'
            response = '{"name": "Alice"}'
            self.jk.validate_json_with_schema(response, schema)
            mock_emit.assert_any_call("parse_valid", "true")

    def test_valid_json_valid_schema_scores_1_0(self) -> None:
        """Valid JSON matching schema scores 1.0."""
        with patch("rfc.json_schema_keywords.emit_rfc_data") as mock_emit:
            schema = '{"required": ["name", "age"], "types": {"name": "string", "age": "number"}}'
            response = '{"name": "Alice", "age": 30}'
            score = self.jk.validate_json_with_schema(response, schema)
            assert score == 1.0
            mock_emit.assert_any_call("validation_valid", "true")

    def test_valid_json_invalid_schema_scores_0_5(self) -> None:
        """Valid JSON but missing required fields scores 0.5."""
        with patch("rfc.json_schema_keywords.emit_rfc_data") as mock_emit:
            schema = '{"required": ["name", "age"]}'
            response = '{"name": "Alice"}'
            score = self.jk.validate_json_with_schema(response, schema)
            assert score == 0.5
            mock_emit.assert_any_call("validation_valid", "false")

    def test_json_in_code_fence_is_extracted(self) -> None:
        """JSON wrapped in code fence is extracted."""
        with patch("rfc.json_schema_keywords.emit_rfc_data"):
            schema = '{"required": ["name"]}'
            response = '```json\n{"name": "Alice"}\n```'
            score = self.jk.validate_json_with_schema(response, schema)
            assert score == 1.0

    def test_schema_name_recorded(self) -> None:
        """Schema name is recorded in RFC data."""
        with patch("rfc.json_schema_keywords.emit_rfc_data") as mock_emit:
            schema = '{"required": []}'
            response = "{}"
            self.jk.validate_json_with_schema(
                response, schema, schema_name="test_schema"
            )
            mock_emit.assert_any_call("schema_name", "test_schema")

    def test_validation_errors_recorded(self) -> None:
        """Validation errors are recorded."""
        with patch("rfc.json_schema_keywords.emit_rfc_data") as mock_emit:
            schema = '{"required": ["name", "age"]}'
            response = '{"name": "Alice"}'
            self.jk.validate_json_with_schema(response, schema)
            calls = [
                call
                for call in mock_emit.call_args_list
                if call[0][0] == "validation_errors"
            ]
            assert len(calls) > 0
            assert "Missing required field: age" in calls[0][0][1]

    def test_score_formatted_correctly(self) -> None:
        """Score is formatted to 4 decimal places."""
        with patch("rfc.json_schema_keywords.emit_rfc_data") as mock_emit:
            schema = '{"required": []}'
            response = "{}"
            score = self.jk.validate_json_with_schema(response, schema)
            calls = [call for call in mock_emit.call_args_list if call[0][0] == "score"]
            assert len(calls) > 0
            assert calls[-1][0][1] == f"{score:.4f}"


class TestValidateJsonWithRetries:
    def setup_method(self) -> None:
        self.jk = JSONSchemaKeywords(max_retries=3)

    @patch("rfc.json_schema_keywords.JSONSchemaKeywords.validate_json_with_schema")
    def test_returns_on_first_success(self, mock_validate: MagicMock) -> None:
        """Returns immediately on first attempt success."""
        mock_validate.return_value = 1.0
        with patch.object(self.jk.client, "generate", return_value='{"data": "value"}'):
            with patch("rfc.json_schema_keywords.emit_rfc_data"):
                schema = '{"required": []}'
                score, attempt = self.jk.validate_json_with_retries(
                    "Generate JSON", schema
                )
                assert score == 1.0
                assert attempt == 1

    @patch("rfc.json_schema_keywords.JSONSchemaKeywords.validate_json_with_schema")
    def test_retries_on_failure(self, mock_validate: MagicMock) -> None:
        """Retries when validation fails."""
        mock_validate.side_effect = [0.5, 0.5, 1.0]
        with patch.object(self.jk.client, "generate", return_value='{"data": "value"}'):
            with patch("rfc.json_schema_keywords.emit_rfc_data"):
                schema = '{"required": []}'
                score, attempt = self.jk.validate_json_with_retries(
                    "Generate JSON", schema
                )
                assert score == 1.0
                assert attempt == 3

    @patch("rfc.json_schema_keywords.JSONSchemaKeywords.validate_json_with_schema")
    def test_respects_max_retries(self, mock_validate: MagicMock) -> None:
        """Stops retrying after max_retries attempts."""
        mock_validate.return_value = 0.5
        with patch.object(self.jk.client, "generate", return_value='{"data": "value"}'):
            with patch("rfc.json_schema_keywords.emit_rfc_data"):
                schema = '{"required": []}'
                score, attempt = self.jk.validate_json_with_retries(
                    "Generate JSON", schema, max_retries=2
                )
                assert attempt == 2
                assert mock_validate.call_count == 2

    @patch("rfc.json_schema_keywords.JSONSchemaKeywords.validate_json_with_schema")
    def test_empty_response_skips_retry(self, mock_validate: MagicMock) -> None:
        """Empty LLM response is skipped without validation."""
        with patch.object(self.jk.client, "generate", return_value=""):
            with patch("rfc.json_schema_keywords.emit_rfc_data"):
                schema = '{"required": []}'
                score, attempt = self.jk.validate_json_with_retries(
                    "Generate JSON", schema
                )
                assert mock_validate.call_count == 0

    def test_respects_custom_max_retries_parameter(self) -> None:
        """Custom max_retries parameter overrides default."""
        from rfc.exceptions import EmptyLLMResponseError

        with patch.object(
            self.jk.client, "generate", side_effect=EmptyLLMResponseError("test-model")
        ):
            with patch("rfc.json_schema_keywords.emit_rfc_data"):
                schema = '{"required": []}'
                score, attempt = self.jk.validate_json_with_retries(
                    "Generate JSON", schema, max_retries=2
                )
                assert attempt == 2

    def test_emits_attempt_number(self) -> None:
        """Attempt number is recorded in RFC data."""
        with patch(
            "rfc.json_schema_keywords.JSONSchemaKeywords.validate_json_with_schema",
            return_value=1.0,
        ):
            with patch.object(self.jk.client, "generate", return_value="{}"):
                with patch("rfc.json_schema_keywords.emit_rfc_data") as mock_emit:
                    schema = '{"required": []}'
                    self.jk.validate_json_with_retries("Generate JSON", schema)
                    mock_emit.assert_any_call("attempt_number", "1")

    def test_emits_final_score(self) -> None:
        """Final score is recorded in RFC data."""
        with patch.object(self.jk, "validate_json_with_schema", return_value=0.75):
            with patch.object(self.jk.client, "generate", return_value="{}"):
                with patch("rfc.json_schema_keywords.emit_rfc_data") as mock_emit:
                    schema = '{"required": []}'
                    self.jk.validate_json_with_retries("Generate JSON", schema)
                    calls = [
                        call
                        for call in mock_emit.call_args_list
                        if call[0][0] == "final_score"
                    ]
                    assert len(calls) > 0
                    assert calls[-1][0][1] == "0.7500"
