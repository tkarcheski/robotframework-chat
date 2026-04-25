"""Tests for rfc.json_schema_keywords.JSONSchemaKeywords."""

from unittest.mock import patch

from rfc.json_schema_keywords import JSONSchemaKeywords, _validate_against_schema


class TestValidateAgainstSchema:
    def test_validates_required_fields_present(self) -> None:
        schema = {"required": ["name", "age"]}
        data = {"name": "Alice", "age": 30}
        is_valid, errors = _validate_against_schema(data, schema)
        assert is_valid
        assert errors == []

    def test_rejects_missing_required_fields(self) -> None:
        schema = {"required": ["name", "age"]}
        data = {"name": "Alice"}
        is_valid, errors = _validate_against_schema(data, schema)
        assert not is_valid
        assert "Missing required field: age" in errors

    def test_validates_field_types(self) -> None:
        schema = {
            "required": ["name", "age"],
            "types": {"name": "string", "age": "number"},
        }
        data = {"name": "Alice", "age": 30}
        is_valid, errors = _validate_against_schema(data, schema)
        assert is_valid
        assert errors == []

    def test_rejects_wrong_field_type(self) -> None:
        schema = {"types": {"age": "string"}}
        data = {"age": 30}
        is_valid, errors = _validate_against_schema(data, schema)
        assert not is_valid
        assert any("should be string" in e for e in errors)

    def test_rejects_non_dict(self) -> None:
        schema = {"required": ["name"]}
        is_valid, errors = _validate_against_schema(["Alice"], schema)
        assert not is_valid
        assert "Expected dict" in errors[0]

    def test_allows_extra_fields(self) -> None:
        schema = {"required": ["name"]}
        data = {"name": "Alice", "age": 30, "email": "alice@example.com"}
        is_valid, _ = _validate_against_schema(data, schema)
        assert is_valid

    def test_type_validation_for_boolean(self) -> None:
        schema = {"types": {"active": "boolean"}}
        is_valid, _ = _validate_against_schema({"active": True}, schema)
        assert is_valid
        is_valid, _ = _validate_against_schema({"active": "true"}, schema)
        assert not is_valid

    def test_type_validation_for_array(self) -> None:
        schema = {"types": {"items": "array"}}
        is_valid, _ = _validate_against_schema({"items": [1, 2, 3]}, schema)
        assert is_valid
        is_valid, _ = _validate_against_schema({"items": "not an array"}, schema)
        assert not is_valid

    def test_type_validation_for_object(self) -> None:
        schema = {"types": {"metadata": "object"}}
        is_valid, _ = _validate_against_schema({"metadata": {"k": "v"}}, schema)
        assert is_valid
        is_valid, _ = _validate_against_schema({"metadata": ["x"]}, schema)
        assert not is_valid

    def test_ignores_missing_optional_fields(self) -> None:
        schema = {"types": {"optional_field": "string"}}
        is_valid, _ = _validate_against_schema({"other": "value"}, schema)
        assert is_valid


class TestValidateJsonWithSchema:
    def setup_method(self) -> None:
        self.jk = JSONSchemaKeywords()

    def test_invalid_schema_returns_zero(self) -> None:
        with patch("rfc.json_schema_keywords.emit_rfc_data") as mock_emit:
            score = self.jk.validate_json_with_schema('{"name": "Alice"}', "not json")
            assert score == 0.0
            mock_emit.assert_any_call("schema_valid", "false")

    def test_valid_schema_recorded(self) -> None:
        with patch("rfc.json_schema_keywords.emit_rfc_data") as mock_emit:
            self.jk.validate_json_with_schema(
                '{"name": "Alice"}', '{"required": ["name"]}'
            )
            mock_emit.assert_any_call("schema_valid", "true")

    def test_parse_failure_returns_zero(self) -> None:
        with patch("rfc.json_schema_keywords.emit_rfc_data") as mock_emit:
            score = self.jk.validate_json_with_schema("not json", '{"required": []}')
            assert score == 0.0
            mock_emit.assert_any_call("parse_valid", "false")

    def test_parse_success_recorded(self) -> None:
        with patch("rfc.json_schema_keywords.emit_rfc_data") as mock_emit:
            self.jk.validate_json_with_schema('{"name": "Alice"}', '{"required": []}')
            mock_emit.assert_any_call("parse_valid", "true")

    def test_valid_json_valid_schema_scores_1_0(self) -> None:
        with patch("rfc.json_schema_keywords.emit_rfc_data") as mock_emit:
            schema = (
                '{"required": ["name", "age"], '
                '"types": {"name": "string", "age": "number"}}'
            )
            score = self.jk.validate_json_with_schema(
                '{"name": "Alice", "age": 30}', schema
            )
            assert score == 1.0
            mock_emit.assert_any_call("validation_valid", "true")

    def test_valid_json_invalid_schema_scores_0_5(self) -> None:
        with patch("rfc.json_schema_keywords.emit_rfc_data") as mock_emit:
            score = self.jk.validate_json_with_schema(
                '{"name": "Alice"}', '{"required": ["name", "age"]}'
            )
            assert score == 0.5
            mock_emit.assert_any_call("validation_valid", "false")

    def test_json_in_code_fence_is_extracted(self) -> None:
        with patch("rfc.json_schema_keywords.emit_rfc_data"):
            score = self.jk.validate_json_with_schema(
                '```json\n{"name": "Alice"}\n```', '{"required": ["name"]}'
            )
            assert score == 1.0

    def test_schema_name_recorded(self) -> None:
        with patch("rfc.json_schema_keywords.emit_rfc_data") as mock_emit:
            self.jk.validate_json_with_schema(
                "{}", '{"required": []}', schema_name="test_schema"
            )
            mock_emit.assert_any_call("schema_name", "test_schema")

    def test_validation_errors_recorded(self) -> None:
        with patch("rfc.json_schema_keywords.emit_rfc_data") as mock_emit:
            self.jk.validate_json_with_schema(
                '{"name": "Alice"}', '{"required": ["name", "age"]}'
            )
            errors_calls = [
                c.args[1]
                for c in mock_emit.call_args_list
                if c.args[0] == "validation_errors"
            ]
            assert errors_calls
            assert "Missing required field: age" in errors_calls[0]

    def test_score_formatted_correctly(self) -> None:
        with patch("rfc.json_schema_keywords.emit_rfc_data") as mock_emit:
            score = self.jk.validate_json_with_schema("{}", '{"required": []}')
            score_calls = [
                c.args[1] for c in mock_emit.call_args_list if c.args[0] == "score"
            ]
            assert score_calls and score_calls[-1] == f"{score:.4f}"


class TestValidateJsonWithRetries:
    def setup_method(self) -> None:
        self.jk = JSONSchemaKeywords(max_retries=3)

    def _patched(self, validate_return: float | list[float]) -> patch:
        kwarg = (
            {"side_effect": validate_return}
            if isinstance(validate_return, list)
            else {"return_value": validate_return}
        )
        return patch("rfc.json_schema_keywords._validate_parsed", **kwarg)

    def test_returns_on_first_success(self) -> None:
        with (
            self._patched(1.0) as mock_validate,
            patch.object(self.jk.client, "generate", return_value="{}"),
            patch("rfc.json_schema_keywords.emit_rfc_data"),
        ):
            score, attempt = self.jk.validate_json_with_retries(
                "Generate JSON", '{"required": []}'
            )
            assert (score, attempt) == (1.0, 1)
            assert mock_validate.call_count == 1

    def test_retries_on_failure(self) -> None:
        with (
            self._patched([0.5, 0.5, 1.0]),
            patch.object(self.jk.client, "generate", return_value="{}"),
            patch("rfc.json_schema_keywords.emit_rfc_data"),
        ):
            score, attempt = self.jk.validate_json_with_retries(
                "Generate JSON", '{"required": []}'
            )
            assert (score, attempt) == (1.0, 3)

    def test_respects_max_retries(self) -> None:
        with (
            self._patched(0.5) as mock_validate,
            patch.object(self.jk.client, "generate", return_value="{}"),
            patch("rfc.json_schema_keywords.emit_rfc_data"),
        ):
            _, attempt = self.jk.validate_json_with_retries(
                "Generate JSON", '{"required": []}', max_retries=2
            )
            assert attempt == 2
            assert mock_validate.call_count == 2

    def test_empty_response_skips_validation(self) -> None:
        with (
            self._patched(1.0) as mock_validate,
            patch.object(self.jk.client, "generate", return_value=""),
            patch("rfc.json_schema_keywords.emit_rfc_data"),
        ):
            self.jk.validate_json_with_retries("Generate JSON", '{"required": []}')
            assert mock_validate.call_count == 0

    def test_empty_llm_response_exception_skips_validation(self) -> None:
        from rfc.exceptions import EmptyLLMResponseError

        with (
            patch.object(
                self.jk.client,
                "generate",
                side_effect=EmptyLLMResponseError("test-model"),
            ),
            patch("rfc.json_schema_keywords.emit_rfc_data"),
        ):
            _, attempt = self.jk.validate_json_with_retries(
                "Generate JSON", '{"required": []}', max_retries=2
            )
            assert attempt == 2

    def test_emits_attempt_number(self) -> None:
        with (
            self._patched(1.0),
            patch.object(self.jk.client, "generate", return_value="{}"),
            patch("rfc.json_schema_keywords.emit_rfc_data") as mock_emit,
        ):
            self.jk.validate_json_with_retries("Generate JSON", '{"required": []}')
            mock_emit.assert_any_call("attempt_number", "1")

    def test_emits_final_score(self) -> None:
        with (
            self._patched(0.75),
            patch.object(self.jk.client, "generate", return_value="{}"),
            patch("rfc.json_schema_keywords.emit_rfc_data") as mock_emit,
        ):
            self.jk.validate_json_with_retries("Generate JSON", '{"required": []}')
            final_calls = [
                c.args[1]
                for c in mock_emit.call_args_list
                if c.args[0] == "final_score"
            ]
            assert final_calls and final_calls[-1] == "0.7500"

    def test_invalid_schema_short_circuits(self) -> None:
        """An unparseable schema returns immediately without calling the LLM."""
        with (
            patch.object(self.jk.client, "generate") as mock_gen,
            patch("rfc.json_schema_keywords.emit_rfc_data"),
        ):
            score, attempt = self.jk.validate_json_with_retries(
                "Generate JSON", "not valid schema"
            )
            assert (score, attempt) == (0.0, 0)
            assert mock_gen.call_count == 0
